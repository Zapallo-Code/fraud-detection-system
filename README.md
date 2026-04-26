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

## Decision de migraciones

En esta fase adoptamos migraciones SQL puras versionadas con un script runner propio. La decision prioriza control total sobre features especificas de PostgreSQL/TimescaleDB y menor complejidad operativa del MVP.
