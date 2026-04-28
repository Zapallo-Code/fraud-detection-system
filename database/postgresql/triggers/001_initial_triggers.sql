-- ============================================================================
-- SECTION 7: Triggers
-- ============================================================================

DROP TRIGGER IF EXISTS alert_on_high_fraud_rate ON public.predictions_history;

CREATE TRIGGER alert_on_high_fraud_rate
AFTER INSERT ON public.predictions_history
FOR EACH ROW
EXECUTE FUNCTION public.check_fraud_rate();


DROP TRIGGER IF EXISTS audit_model_deployments ON public.model_deployments;

CREATE TRIGGER audit_model_deployments
AFTER INSERT OR UPDATE OR DELETE ON public.model_deployments
FOR EACH ROW
EXECUTE FUNCTION public.audit_trigger();


DROP TRIGGER IF EXISTS audit_predictions_history ON public.predictions_history;

CREATE TRIGGER audit_predictions_history
AFTER INSERT OR UPDATE OR DELETE ON public.predictions_history
FOR EACH ROW
EXECUTE FUNCTION public.audit_trigger();

-- 4) Confirm triggers are active
-- SELECT trigger_name, event_object_table, action_timing, event_manipulation
-- FROM information_schema.triggers
-- WHERE trigger_schema = 'public'
--   AND trigger_name IN (
--       'alert_on_high_fraud_rate',
--       'audit_model_deployments',
--       'audit_predictions_history'
--   )
-- ORDER BY trigger_name;
