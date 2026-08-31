#!/bin/sh
set -eu

: "${PATENT_EVIDENCE_MIGRATION_DB_PASSWORD:?required}"
: "${PATENT_EVIDENCE_APP_DB_PASSWORD:?required}"
: "${PATENT_EVIDENCE_PLATFORM_DB_PASSWORD:?required}"
: "${PATENT_EVIDENCE_WORKER_DB_PASSWORD:?required}"

psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --set=ON_ERROR_STOP=1 \
  --set=migration_password="$PATENT_EVIDENCE_MIGRATION_DB_PASSWORD" \
  --set=app_password="$PATENT_EVIDENCE_APP_DB_PASSWORD" \
  --set=platform_password="$PATENT_EVIDENCE_PLATFORM_DB_PASSWORD" \
  --set=worker_password="$PATENT_EVIDENCE_WORKER_DB_PASSWORD" \
  --set=database_name="$POSTGRES_DB" <<'SQL'
SELECT format(
  'CREATE ROLE patent_evidence_migration LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS',
  :'migration_password'
) WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'patent_evidence_migration') \gexec
SELECT format(
  'CREATE ROLE patent_evidence_app LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS',
  :'app_password'
) WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'patent_evidence_app') \gexec
SELECT format(
  'CREATE ROLE patent_evidence_platform LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS',
  :'platform_password'
) WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'patent_evidence_platform') \gexec
SELECT format(
  'CREATE ROLE patent_evidence_worker LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS',
  :'worker_password'
) WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'patent_evidence_worker') \gexec

ALTER DATABASE :"database_name" OWNER TO patent_evidence_migration;
SQL
