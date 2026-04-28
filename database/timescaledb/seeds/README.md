# Seed de transacciones en TimescaleDB

Este directorio contiene el script para generar 10.000 transacciones sinteticas e insertarlas en la hypertable `public.transactions`.

## Requisitos

- Python 3.10+
- Dependencia: `psycopg2` o `psycopg2-binary`

## Variables de entorno

El script lee la configuracion desde:

- `TIMESCALEDB_HOST` (default: `localhost`)
- `TIMESCALEDB_PORT` (default: `5432`)
- `TIMESCALEDB_USER` (default: `postgres`)
- `TIMESCALEDB_PASSWORD` (default: `postgres`)
- `TIMESCALEDB_DB` (default: `timescaledb`)

## Uso

```bash
python database/timescaledb/seeds/seed_transactions.py \
  --count 10000 \
  --fraud-rate 0.02 \
  --seed 42 \
  --batch-size 500
```

Parametros:

- `--count`: cantidad de transacciones a insertar (default 10000)
- `--fraud-rate`: proporcion de fraude (default 0.02)
- `--seed`: seed para reproducibilidad (default 42)
- `--batch-size`: tamano del batch para insertar (default 500)

El script imprime progreso cada 1000 filas y un resumen al finalizar.

## Verificacion (SQL)

```sql
-- Total de registros y fraude
SELECT
    COUNT(*) AS total,
    COUNT(*) FILTER (WHERE is_fraud IS TRUE) AS fraude
FROM public.transactions;

-- Distribucion por pais
SELECT country, COUNT(*)
FROM public.transactions
GROUP BY country
ORDER BY COUNT(*) DESC;

-- Rango de fechas
SELECT MIN("timestamp") AS min_ts, MAX("timestamp") AS max_ts
FROM public.transactions;

-- Ejemplo de verificacion de rafaga (frecuencia alta)
SELECT user_id, COUNT(*) AS tx_count
FROM public.transactions
WHERE "timestamp" >= NOW() - INTERVAL '30 minutes'
GROUP BY user_id
HAVING COUNT(*) >= 5
ORDER BY tx_count DESC;
```
