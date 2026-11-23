#!/usr/bin/env bash
set -euo pipefail

: "${AIRFLOW_ADMIN_USERNAME:?AIRFLOW_ADMIN_USERNAME is required}"
: "${AIRFLOW_ADMIN_PASSWORD:?AIRFLOW_ADMIN_PASSWORD is required}"

airflow db migrate
if ! airflow users list --output json | grep -q "\"username\": \"$AIRFLOW_ADMIN_USERNAME\""; then
  airflow users create \
    --username "$AIRFLOW_ADMIN_USERNAME" \
    --firstname SurvivalLab \
    --lastname Admin \
    --role Admin \
    --email survivallab-admin@localhost \
    --password "$AIRFLOW_ADMIN_PASSWORD"
fi
