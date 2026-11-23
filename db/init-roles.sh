#!/bin/sh
set -eu

: "${INGEST_PASSWORD:?INGEST_PASSWORD is required}"
: "${READ_PASSWORD:?READ_PASSWORD is required}"
: "${PIPELINE_PASSWORD:?PIPELINE_PASSWORD is required}"
: "${ANALYTICS_PASSWORD:?ANALYTICS_PASSWORD is required}"

psql --set=ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<SQL
CREATE ROLE survivallab_ingest LOGIN PASSWORD '${INGEST_PASSWORD}';
CREATE ROLE survivallab_reader LOGIN PASSWORD '${READ_PASSWORD}';
CREATE ROLE survivallab_pipeline LOGIN PASSWORD '${PIPELINE_PASSWORD}';
CREATE ROLE survivallab_analytics LOGIN PASSWORD '${ANALYTICS_PASSWORD}';
CREATE SCHEMA IF NOT EXISTS raw AUTHORIZATION ${POSTGRES_USER};
CREATE SCHEMA IF NOT EXISTS meta AUTHORIZATION ${POSTGRES_USER};
CREATE SCHEMA IF NOT EXISTS model AUTHORIZATION ${POSTGRES_USER};
GRANT CONNECT ON DATABASE ${POSTGRES_DB} TO survivallab_ingest, survivallab_reader,
  survivallab_pipeline, survivallab_analytics;
CREATE SCHEMA IF NOT EXISTS analytics AUTHORIZATION ${POSTGRES_USER};
GRANT USAGE ON SCHEMA raw TO survivallab_ingest, survivallab_pipeline, survivallab_analytics;
GRANT USAGE ON SCHEMA meta TO survivallab_pipeline, survivallab_reader, survivallab_analytics;
GRANT USAGE ON SCHEMA model TO survivallab_pipeline, survivallab_reader;
GRANT USAGE ON SCHEMA analytics TO survivallab_pipeline;
GRANT USAGE, CREATE ON SCHEMA analytics TO survivallab_analytics;
ALTER DEFAULT PRIVILEGES FOR ROLE survivallab_analytics IN SCHEMA analytics
  GRANT SELECT ON TABLES TO survivallab_pipeline;
SQL
