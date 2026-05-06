# Fraud Detection System (MLOps)

Proyecto para detectar fraude en transacciones en tiempo real (objetivo: respuesta < 100ms) y, al mismo tiempo, tener un setup MLOps completo: tracking, reentrenamiento automático, drift y monitoreo.

## Stack

- Ingesta/stream: Kafka
- Feature engineering: Python
- Modelo: XGBoost
- API de inferencia: FastAPI
- Orquestación: Airflow
- Experimentos/registry: MLflow
- Drift: Evidently AI
- DB temporal: TimescaleDB
- DB relacional/auditoría: PostgreSQL
- Monitoreo: Grafana (+ Prometheus para métricas)
- Infra local: Docker + Docker Compose
- CI/CD: GitHub Actions

## Levantar el proyecto con script

Desde la raíz del repo ejecutá:

```bash
./scripts/setup.sh
```

El script valida prerequisitos (Docker + Compose), crea `.env` desde `.env.example` si no existe, construye imágenes, levanta los servicios y realiza las inicializaciones básicas (Airflow, Kafka y migraciones SQL). Si es la primera ejecución y se crea `.env`, editá las credenciales y volvé a correr el comando.

## Simulaciones (Producer)

Ejemplos de uso desde la raíz del repo:

```bash
# Modo live: mezcla legítimas + fraude con TPS configurable
python -m ingestion.producer.main --mode live --tps 10 --fraud-rate 0.02

# Modo scenario: inyecta un patrón de fraude específico
python -m ingestion.producer.main --mode scenario --scenario high_frequency --tps 5

# Modo scenario mixto
python -m ingestion.producer.main --mode scenario --scenario mixed --tps 8

# Modo replay: reproduce un CSV histórico
python -m ingestion.producer.main --mode replay --replay /ruta/al/archivo.csv
```

Flags útiles:

Modo y datos:

- `--mode`: `live` (flujo continuo con fraude mezclado), `scenario` (patron fijo o mixto), `replay` (reproduce un CSV).
- `--replay`: path al CSV cuando `--mode replay` (requiere columnas del schema raw; `is_fraud` es opcional).
- `--scenario`: patron de fraude cuando `--mode scenario` (`amount_anomaly`, `unusual_country`, `high_frequency`, `unknown_merchant`, `mixed`).

Control de volumen:

- `--tps`: transacciones por segundo.
- `--duration`: duracion en segundos (0 = infinito).

Control de mezcla y reproducibilidad:

- `--fraud-rate`: proporcion de fraude en `live` (0.0 a 1.0).
- `--seed`: seed para reproducibilidad.

Escala de simulacion:

- `--num-users`: usuarios simulados.
- `--num-merchants`: merchants simulados.

## Decision de migraciones

En esta fase adoptamos migraciones SQL puras versionadas con un script runner propio. La decision prioriza control total sobre features especificas de PostgreSQL/TimescaleDB y menor complejidad operativa del MVP.
