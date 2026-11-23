#!/bin/sh
set -e

# Role from SERVICE_ROLE (handy on hosts like Railway: one image, several services),
# else from the first argument: api (default) | jobs | worker | beat
ROLE="${SERVICE_ROLE:-${1:-api}}"

case "$ROLE" in
  api)
    echo "Running database migrations..."
    alembic upgrade head
    if [ "${SEED_DEMO_DATA:-true}" = "true" ]; then
      python -m data_pipeline.seed_data
    fi
    if [ "${SEED_PUBLIC_DATASET:-true}" = "true" ]; then
      python -m data_pipeline.seed_public_dataset  # ~2,800 sample products; skipped once loaded
    fi
    python -m data_pipeline.coupon_collector
    exec uvicorn main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips="*"
    ;;
  jobs)
    # Worker with the scheduler built in: one service for small deployments
    exec celery -A celery_app worker --beat --loglevel="${LOG_LEVEL:-info}" \
      --concurrency="${CELERY_CONCURRENCY:-2}" --schedule /tmp/celerybeat-schedule
    ;;
  worker)
    exec celery -A celery_app worker --loglevel="${LOG_LEVEL:-info}" --concurrency="${CELERY_CONCURRENCY:-2}"
    ;;
  beat)
    exec celery -A celery_app beat --loglevel="${LOG_LEVEL:-info}" --schedule /tmp/celerybeat-schedule
    ;;
  *)
    exec "$@"
    ;;
esac
