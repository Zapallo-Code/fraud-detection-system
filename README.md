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
