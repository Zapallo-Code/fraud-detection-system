# Historia de implementacion

Este documento narra, de forma detallada, todo lo que se fue construyendo desde el inicio del proyecto hasta la finalizacion de la Fase 3 (ingesta y streaming). El foco esta en decisiones, artefactos creados y el orden en que se consolidaron.

## Momento cero: vision y plan base

El proyecto arranco con una vision clara: deteccion de fraude en tiempo real con latencia baja y una plataforma MLOps completa (tracking, reentrenamiento, drift y monitoreo). Para asegurar ejecucion ordenada se definio un plan maestro en `docs/PLAN.md` con fases, tareas y tiempos estimados. Ese plan fijo el stack tecnico, las responsabilidades por capa y el flujo principal de datos.

Desde este punto se establecio un criterio: construir primero una base operativa solida (infraestructura, bases de datos y streaming) antes de atacar el entrenamiento del modelo y el serving avanzado. Esto reduce riesgos y habilita pruebas end-to-end tempranas.

## Fase 1: setup e infraestructura base

### 1.1 Estructura del repositorio y configuracion base

Se organizo el repositorio con carpetas separadas por dominio (ingestion, database, docker, serving, mlops, monitoring). La estructura quedo alineada con la arquitectura definida en el plan.

Se estandarizo la configuracion central en `config.py` usando Pydantic Settings. Esta decision permite validar variables criticas y compartir la misma fuente de verdad entre servicios. Se definieron settings para Kafka, PostgreSQL, TimescaleDB, Redis, MLflow, modelo, Airflow y Grafana.

### 1.2 Dockerizacion del stack

Se construyo un `docker-compose.yml` completo que levanta:

- Kafka + Zookeeper
- Schema Registry
- Kafka UI
- Redis
- TimescaleDB
- PostgreSQL
- MLflow
- Airflow (webserver y scheduler)
- FastAPI
- Grafana

Cada servicio cuenta con healthchecks para garantizar que el bootstrap sea confiable. Se definio una red interna `mlops-net` y volumenes persistentes para bases de datos, MLflow y Grafana.

Se agregaron Dockerfiles especificos para:

- FastAPI (Python 3.11, uv, user no-root, healthcheck)
- Airflow (imagen oficial, dependencias MLflow/Evidently/psycopg2)
- Kafka producer (Python 3.11 con dependencias de ingestion)
- Grafana (provisioning de datasources y dashboards)
- MLflow (dependencia psycopg2 para backend store)

Adicionalmente se incluyo `docker-compose.override.yml` para desarrollo local con montajes de codigo, logs mas verbosos y un listener extra de Kafka para debugging.

### 1.3 Script de setup idempotente

Se creo `scripts/setup.sh` como entrada unica para el bootstrap. Este script:

- Valida prerequisitos (Docker + Compose)
- Genera `.env` desde `.env.example` si no existe
- Construye imagenes y levanta el stack
- Espera healthchecks
- Inicializa la base de Airflow y crea usuario admin
- Crea topics Kafka base
- Ejecuta migraciones SQL en PostgreSQL y TimescaleDB
- Verifica el estado final de servicios

El script es idempotente: puede correrse multiples veces sin efectos destructivos. Esto reduce friccion en entornos nuevos.

### 1.4 Ajustes operativos y fixes tempranos

Durante la estabilizacion se incorporaron mejoras:

- Separacion de bases de datos de Airflow y MLflow para evitar colisiones de metadata.
- Ajuste de bootstrap para evitar deadlocks al iniciar Airflow.
- Restriccion de exposicion de Kafka UI al host.
- Alineacion de `.env.example` con el stack real.

Estos cambios dejaron el entorno listo para iterar sobre bases de datos e ingestion.

## Fase 2: bases de datos

### 2.1 TimescaleDB: series temporales

Se implemento la migracion `database/timescaledb/migrations/001_initial_schema.sql` con los siguientes componentes:

- Tabla `public.transactions` con PK `(transaction_id, timestamp)` para compatibilidad con hypertable.
- Hypertable por columna `timestamp` con chunk diario.
- Indices para consultas por usuario y por tiempo.
- Indice parcial para fraude (optimiza dashboards de fraude).
- Continuous aggregates:
  - `fraud_volume_hourly` (tasa de fraude por hora)
  - `merchant_amount_daily` (monto diario por merchant)
- Politicas:
  - Refresh de cagg cada 5 minutos
  - Compresion despues de 7 dias
  - Retencion y drop despues de 2 anios

Se incluyeron queries de verificacion manual para validar tablas, indices y policies.

### 2.2 PostgreSQL: metadata y auditoria

Se creo la migracion `database/postgresql/migrations/001_initial_schema.sql` con tablas operativas:

- `model_deployments`: versiones de modelos y metricas.
- `predictions_history`: historico de predicciones y latencia.
- `drift_reports`: reportes de drift por feature.
- `alert_log`: alertas operativas.
- `audit_log`: auditoria de cambios.

Se agregaron constraints y checks para asegurar calidad de datos (rangos de scores, orden temporal, severities permitidas). Tambien se crearon indices para consultas frecuentes por fecha, version y estado.

En `database/postgresql/stored_procedures/001_initial_stored_procedures.sql` se incorporaron funciones:

- `activate_model_version`: activa una version y desactiva el resto, con registro en audit_log.
- `calculate_model_metrics`: calcula precision/recall/f1 desde `predictions_history`.
- `check_fraud_rate`: evalua tasa de fraude y emite alertas.
- `audit_trigger`: genera eventos de auditoria para INSERT/UPDATE/DELETE.

Finalmente, en `database/postgresql/triggers/001_initial_triggers.sql` se registraron triggers para:

- Alertar sobre tasas de fraude altas en `predictions_history`.
- Auditar cambios en `model_deployments` y `predictions_history`.

### 2.3 Seeds y soporte de datos

Se agrego un generador de seeds para TimescaleDB en `database/timescaledb/seeds/seed_transactions.py` con guia en `database/timescaledb/seeds/README.md`. El objetivo fue contar con datos sinteticos para pruebas de dashboards y validacion de queries.

## Fase 3: ingesta y streaming con Kafka

### 3.1 Contratos de datos y schemas

Se crearon schemas Avro en `ingestion/schemas` para estandarizar mensajes:

- `transaction_raw.avsc`
- `transaction_features.avsc`
- `transaction_prediction.avsc`
- `fraud_alert.avsc`

Se levanto Schema Registry y se configuro compatibilidad backward. Esto garantiza evolucion controlada de los eventos.

### 3.2 Producer: simulacion realista de transacciones

Se definio el modelo base `Transaction` en `ingestion/producer/models.py` y se implemento un generador de transacciones legitimas en `generator.py`, con:

- Distribuciones log-normales por categoria
- Preferencias por pais y dispositivo
- Sesiones y hashes de IP consistentes
- Sesgos de actividad diaria

Se agrego un generador de fraude (`FraudPatternGenerator`) con cuatro patrones:

- Monto atipico
- Pais inusual
- Rafaga de alta frecuencia
- Merchant desconocido con monto alto

En `ingestion/producer/main.py` se expusieron modos CLI:

- `live`: mezcla de legitimas y fraude a tasa configurable
- `replay`: reproduce CSV historico
- `scenario`: inyecta un patron especifico o mixto

El producer reporta estadisticas y soporta TPS configurable.

### 3.3 Kafka producer con Avro

En `ingestion/producer/kafka_producer.py` se construyo un productor con:

- Serializacion Avro con `fastavro`
- Idempotencia habilitada
- Compresion snappy
- Retries y acks=all
- Logs de entrega y manejo de errores

Esto permite un pipeline robusto desde el inicio.

### 3.4 Consumer base y deserializacion

Se implemento `ingestion/consumer/kafka_consumer.py` para:

- Consumir mensajes Avro de `transactions.raw`
- Convertir a `TransactionRaw`
- Manejar timestamps con timezone
- Retry simple para fallos de deserializacion

El consumer evita autocommit y solo confirma offsets una vez procesada la transaccion.

### 3.5 Feature engineering online

Se construyo el pipeline en `ingestion/consumer/main.py`:

1. Consume transaccion
2. Calcula features de ventana (1h, 24h, 7d)
3. Calcula features historicas por usuario
4. Actualiza estado en memoria
5. Persiste estado en Redis (si disponible)
6. Inserta en TimescaleDB (si disponible)
7. Publica evento enriquecido en `transactions.features`

Los calculos de ventana viven en `windows.py` y los historicos en `historical.py`. Los modelos de features estan en `feature_models.py`.

### 3.6 Redis como feature store

Se agrego `redis_store.py` para guardar y rehidratar el estado por usuario:

- Ventanas: `features:window:<user_id>`
- Historico: `features:historical:<user_id>`
- TTL de 7 dias

El consumer hidrata el estado al primer evento de cada usuario, lo que permite continuidad aun tras reinicios.

### 3.7 TimescaleDB writer

En `timescale_writer.py` se implemento insercion idempotente en `public.transactions`, con pool de conexiones y manejo de errores. Si Timescale no esta disponible, el consumer sigue procesando el stream sin persistencia, evitando bloqueos.

### 3.8 Publicacion de features

`feature_publisher.py` serializa las features en Avro y publica en `transactions.features`. Se flatean los valores de ventana e historico en un `map<string,double>` para compatibilidad con el schema.
