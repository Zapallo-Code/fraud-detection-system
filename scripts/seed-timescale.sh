#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

require_command() {
  local cmd="$1"
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    printf "Error: missing required command: %s\n" "${cmd}" >&2
    exit 1
  fi
}

prompt_value() {
  local label="$1"
  local default_value="$2"
  local input_value=""

  read -r -p "${label} [${default_value}]: " input_value
  if [[ -z "${input_value}" ]]; then
    input_value="${default_value}"
  fi

  printf "%s" "${input_value}"
}

require_command docker
if ! docker compose version >/dev/null 2>&1; then
  printf "Error: Docker Compose v2 is required (docker compose).\n" >&2
  exit 1
fi

if [[ ! -f .env ]]; then
  printf "Error: .env not found. Run ./scripts/setup.sh first.\n" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1091
source .env
set +a

required_env_vars=(
  TIMESCALE_USER
  TIMESCALE_PASSWORD
  TIMESCALE_DB
)

for var_name in "${required_env_vars[@]}"; do
  if [[ -z "${!var_name:-}" ]]; then
    printf "Error: missing %s in .env\n" "${var_name}" >&2
    exit 1
  fi
done

printf "\nTimescaleDB seed wizard\n"
printf "Select a dataset size preset (you can still edit values):\n"
printf "  1) small  (1,000 rows)\n"
printf "  2) medium (10,000 rows) [default]\n"
printf "  3) large  (50,000 rows)\n"
printf "  4) custom\n\n"

read -r -p "Preset [2]: " preset
case "${preset}" in
  1)
    count="1000"
    ;;
  2|"")
    count="10000"
    ;;
  3)
    count="50000"
    ;;
  4)
    count="10000"
    ;;
  *)
    printf "Unknown option, using medium.\n"
    count="10000"
    ;;
esac

if [[ "${preset}" == "4" ]]; then
  count="$(prompt_value "Row count" "${count}")"
else
  count="$(prompt_value "Row count" "${count}")"
fi

fraud_rate_default="0.02"
seed_default="42"
batch_size_default="500"

fraud_rate="$(prompt_value "Fraud rate (0-1)" "${fraud_rate_default}")"
seed="$(prompt_value "Seed" "${seed_default}")"
batch_size="$(prompt_value "Batch size" "${batch_size_default}")"

printf "\nConfiguration summary:\n"
printf "  count:      %s\n" "${count}"
printf "  fraud-rate: %s\n" "${fraud_rate}"
printf "  seed:       %s\n" "${seed}"
printf "  batch-size: %s\n" "${batch_size}"
printf "\n"

printf "Running seed inside Docker (service: airflow-webserver)...\n"
printf "If the stack is not up, run: docker compose up -d timescaledb\n\n"

docker compose run --rm \
  --no-deps \
  --entrypoint python \
  -v "$(pwd)":/app \
  -w /app \
  -e TIMESCALE_HOST=timescaledb \
  -e TIMESCALE_PORT=5432 \
  -e TIMESCALE_USER="${TIMESCALE_USER}" \
  -e TIMESCALE_PASSWORD="${TIMESCALE_PASSWORD}" \
  -e TIMESCALE_DB="${TIMESCALE_DB}" \
  airflow-webserver \
  database/timescaledb/seeds/seed_transactions.py \
  --count "${count}" \
  --fraud-rate "${fraud_rate}" \
  --seed "${seed}" \
  --batch-size "${batch_size}"
