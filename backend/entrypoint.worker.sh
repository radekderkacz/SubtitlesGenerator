#!/bin/sh
set -e

echo "Starting Celery worker..."
exec celery -A app.worker.celery_app.celery_app worker \
    --loglevel=info \
    --concurrency=1 \
    --queues=celery
