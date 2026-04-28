-- ============================================================================
-- SECTION 6: Stored functions
-- ============================================================================

CREATE OR REPLACE FUNCTION public.activate_model_version(p_model_version_id INTEGER)
RETURNS VOID
LANGUAGE plpgsql
AS $$
DECLARE
    v_target RECORD;
    v_old_active RECORD;
    v_old_values JSONB;
    v_new_values JSONB;
BEGIN
    RAISE NOTICE 'activate_model_version start: model_version_id=%', p_model_version_id;

    SELECT mv.id, mv.model_name, mv.version, mv.is_active
    INTO v_target
    FROM public.model_deployments AS mv
    WHERE mv.id = p_model_version_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION
            'activate_model_version failed: model_version_id % does not exist in model_deployments',
            p_model_version_id;
    END IF;

    SELECT mv.id, mv.model_name, mv.version, mv.is_active
    INTO v_old_active
    FROM public.model_deployments AS mv
    WHERE mv.is_active IS TRUE
      AND mv.id <> p_model_version_id
    ORDER BY mv.created_at DESC, mv.id DESC
    LIMIT 1
    FOR UPDATE;

    IF FOUND THEN
        v_old_values := jsonb_build_object(
            'id', v_old_active.id,
            'model_name', v_old_active.model_name,
            'version', v_old_active.version,
            'is_active', TRUE
        );

        RAISE NOTICE
            'Previous active model found: id=%, model_name=%, version=%',
            v_old_active.id, v_old_active.model_name, v_old_active.version;
    ELSE
        v_old_values := NULL;
        RAISE NOTICE 'No previously active model found (first activation case).';
    END IF;

    RAISE NOTICE 'Deactivating all active versions except id=%', p_model_version_id;
    UPDATE public.model_deployments
    SET is_active = FALSE
    WHERE is_active IS TRUE
      AND id <> p_model_version_id;

    RAISE NOTICE 'Activating model_version_id=%', p_model_version_id;
    UPDATE public.model_deployments
    SET is_active = TRUE
    WHERE id = p_model_version_id;

    v_new_values := jsonb_build_object(
        'id', v_target.id,
        'model_name', v_target.model_name,
        'version', v_target.version,
        'is_active', TRUE
    );

    INSERT INTO public.audit_log (
        "table",
        "operation",
        "user",
        "timestamp",
        old_values,
        new_values
    )
    VALUES (
        'model_deployments',
        'ACTIVATE',
        CURRENT_USER,
        NOW(),
        v_old_values,
        v_new_values
    );

    RAISE NOTICE 'activate_model_version complete: model_version_id=%', p_model_version_id;
END;
$$;


CREATE OR REPLACE FUNCTION public.calculate_model_metrics(
    p_model_version_id INTEGER,
    p_date_from TIMESTAMPTZ,
    p_date_to TIMESTAMPTZ
)
RETURNS TABLE (
    "precision" DOUBLE PRECISION,
    "recall" DOUBLE PRECISION,
    f1_score DOUBLE PRECISION
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_min_confirmed_records INTEGER := 100;
    v_confirmed_count INTEGER;
    v_tp INTEGER;
    v_fp INTEGER;
    v_fn INTEGER;
    v_precision DOUBLE PRECISION;
    v_recall DOUBLE PRECISION;
    v_f1_score DOUBLE PRECISION;
BEGIN
    IF p_date_from >= p_date_to THEN
        RAISE EXCEPTION
            'calculate_model_metrics failed: p_date_from (%) must be earlier than p_date_to (%)',
            p_date_from,
            p_date_to;
    END IF;

    PERFORM 1
    FROM public.model_deployments AS mv
    WHERE mv.id = p_model_version_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION
            'calculate_model_metrics failed: model_version_id % does not exist in model_deployments',
            p_model_version_id;
    END IF;

    SELECT
        COUNT(*)::INTEGER,
        COALESCE(SUM(CASE
            WHEN ph.prediction_label IS TRUE AND ph.actual_label IS TRUE THEN 1
            ELSE 0
        END), 0)::INTEGER,
        COALESCE(SUM(CASE
            WHEN ph.prediction_label IS TRUE AND ph.actual_label IS FALSE THEN 1
            ELSE 0
        END), 0)::INTEGER,
        COALESCE(SUM(CASE
            WHEN ph.prediction_label IS FALSE AND ph.actual_label IS TRUE THEN 1
            ELSE 0
        END), 0)::INTEGER
    INTO
        v_confirmed_count,
        v_tp,
        v_fp,
        v_fn
    FROM public.predictions_history AS ph
    WHERE ph.model_version_id = p_model_version_id
      AND ph."timestamp" >= p_date_from
      AND ph."timestamp" < p_date_to
      AND ph.actual_label IS NOT NULL;

    IF v_confirmed_count < v_min_confirmed_records THEN
        RAISE NOTICE
            'calculate_model_metrics skipped: confirmed_records=% is below minimum=% for model_version_id=%',
            v_confirmed_count,
            v_min_confirmed_records,
            p_model_version_id;

        RETURN QUERY
        SELECT
            NULL::DOUBLE PRECISION AS "precision",
            NULL::DOUBLE PRECISION AS "recall",
            NULL::DOUBLE PRECISION AS f1_score;
        RETURN;
    END IF;

    IF (v_tp + v_fp) > 0 THEN
        v_precision := v_tp::DOUBLE PRECISION / (v_tp + v_fp);
    ELSE
        v_precision := 0.0;
    END IF;

    IF (v_tp + v_fn) > 0 THEN
        v_recall := v_tp::DOUBLE PRECISION / (v_tp + v_fn);
    ELSE
        v_recall := 0.0;
    END IF;

    IF (v_precision + v_recall) > 0 THEN
        v_f1_score := 2.0 * (v_precision * v_recall) / (v_precision + v_recall);
    ELSE
        v_f1_score := 0.0;
    END IF;

    RAISE NOTICE
        'calculate_model_metrics: model_version_id=%, confirmed=%, tp=%, fp=%, fn=%, precision=%, recall=%, f1_score=%',
        p_model_version_id,
        v_confirmed_count,
        v_tp,
        v_fp,
        v_fn,
        v_precision,
        v_recall,
        v_f1_score;

    UPDATE public.model_deployments
    SET
        precision = v_precision,
        recall = v_recall,
        f1_score = v_f1_score
    WHERE id = p_model_version_id;

    RETURN QUERY
    SELECT
        v_precision AS "precision",
        v_recall AS "recall",
        v_f1_score AS f1_score;
END;
$$;


CREATE OR REPLACE FUNCTION public.check_fraud_rate()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_fraud_threshold DOUBLE PRECISION := 0.05;
    v_window_minutes INTEGER := 15;
    v_window_interval INTERVAL := INTERVAL '15 minutes';

    v_reference_ts TIMESTAMPTZ := COALESCE(NEW."timestamp", NOW());
    v_total_count BIGINT := 0;
    v_fraud_count BIGINT := 0;
    v_fraud_rate DOUBLE PRECISION := 0.0;
    v_has_recent_open_alert BOOLEAN := FALSE;

    v_alert_message TEXT;
    v_notify_payload TEXT;
BEGIN
    SELECT
        COUNT(*)::BIGINT,
        COALESCE(SUM(CASE WHEN ph.prediction_label IS TRUE THEN 1 ELSE 0 END), 0)::BIGINT
    INTO
        v_total_count,
        v_fraud_count
    FROM public.predictions_history AS ph
    WHERE ph."timestamp" >= (v_reference_ts - v_window_interval)
      AND ph."timestamp" <= v_reference_ts;

    IF v_total_count > 0 THEN
        v_fraud_rate := v_fraud_count::DOUBLE PRECISION / v_total_count::DOUBLE PRECISION;
    ELSE
        v_fraud_rate := 0.0;
    END IF;

    RAISE NOTICE
        'check_fraud_rate: fraud_rate=%, fraud_count=%, total_count=%, window_minutes=%',
        v_fraud_rate,
        v_fraud_count,
        v_total_count,
        v_window_minutes;

    SELECT EXISTS (
        SELECT 1
        FROM public.alert_log AS al
        WHERE al.alert_type = 'HIGH_FRAUD_RATE'
          AND al.acknowledged_at IS NULL
          AND al.triggered_at >= (v_reference_ts - v_window_interval)
    )
    INTO v_has_recent_open_alert;

    IF v_fraud_rate > v_fraud_threshold AND NOT v_has_recent_open_alert THEN
        v_alert_message := format(
            'High fraud rate detected: %s%% over the last %s minutes (%s/%s predictions).',
            to_char(v_fraud_rate * 100.0, 'FM999990.00'),
            v_window_minutes,
            v_fraud_count,
            v_total_count
        );

        INSERT INTO public.alert_log (
            alert_type,
            severity,
            message,
            triggered_at
        )
        VALUES (
            'HIGH_FRAUD_RATE',
            'HIGH',
            v_alert_message,
            v_reference_ts
        );

        v_notify_payload := jsonb_build_object(
            'fraud_rate', round(v_fraud_rate::NUMERIC, 6),
            'window_minutes', v_window_minutes,
            'triggered_at', v_reference_ts
        )::TEXT;

        PERFORM pg_notify('fraud_alerts', v_notify_payload);

        RAISE NOTICE 'check_fraud_rate: HIGH_FRAUD_RATE alert inserted and pg_notify emitted.';
    END IF;

    RETURN NEW;
END;
$$;


CREATE OR REPLACE FUNCTION public.audit_trigger()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_old_values JSONB;
    v_new_values JSONB;
BEGIN
    RAISE NOTICE 'audit_trigger: table=%, operation=%', TG_TABLE_NAME, TG_OP;

    IF TG_OP = 'INSERT' THEN
        v_old_values := NULL;
        v_new_values := row_to_json(NEW)::JSONB;

        INSERT INTO public.audit_log (
            "table",
            "operation",
            "user",
            "timestamp",
            old_values,
            new_values
        )
        VALUES (
            TG_TABLE_NAME,
            TG_OP,
            CURRENT_USER,
            NOW(),
            v_old_values,
            v_new_values
        );

        RETURN NEW;
    ELSIF TG_OP = 'UPDATE' THEN
        v_old_values := row_to_json(OLD)::JSONB;
        v_new_values := row_to_json(NEW)::JSONB;

        INSERT INTO public.audit_log (
            "table",
            "operation",
            "user",
            "timestamp",
            old_values,
            new_values
        )
        VALUES (
            TG_TABLE_NAME,
            TG_OP,
            CURRENT_USER,
            NOW(),
            v_old_values,
            v_new_values
        );

        RETURN NEW;
    ELSIF TG_OP = 'DELETE' THEN
        v_old_values := row_to_json(OLD)::JSONB;
        v_new_values := NULL;

        INSERT INTO public.audit_log (
            "table",
            "operation",
            "user",
            "timestamp",
            old_values,
            new_values
        )
        VALUES (
            TG_TABLE_NAME,
            TG_OP,
            CURRENT_USER,
            NOW(),
            v_old_values,
            v_new_values
        );

        RETURN OLD;
    ELSE
        RAISE EXCEPTION
            'audit_trigger failed: unsupported operation "%" on table "%"',
            TG_OP,
            TG_TABLE_NAME;
    END IF;
END;
$$;


-- 3) Confirm functions exist
-- SELECT n.nspname AS schema_name, p.proname AS function_name
-- FROM pg_proc p
-- JOIN pg_namespace n ON n.oid = p.pronamespace
-- WHERE n.nspname = 'public'
--   AND p.proname IN (
--       'activate_model_version',
--       'calculate_model_metrics',
--       'check_fraud_rate',
--       'audit_trigger'
--   )
-- ORDER BY function_name;
