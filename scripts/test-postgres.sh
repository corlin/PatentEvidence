#!/bin/sh
set -eu

repository_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
container_name="patent-evidence-postgres-test-$$"

cleanup() {
  docker rm --force "$container_name" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

docker run --detach --rm --name "$container_name" \
  --publish 127.0.0.1::5432 \
  --env POSTGRES_DB=patent_evidence_test \
  --env POSTGRES_USER=postgres \
  --env POSTGRES_PASSWORD=postgres-test-only \
  --env PATENT_EVIDENCE_MIGRATION_DB_PASSWORD=migration-test-only \
  --env PATENT_EVIDENCE_APP_DB_PASSWORD=app-test-only \
  --env PATENT_EVIDENCE_PLATFORM_DB_PASSWORD=platform-test-only \
  --env PATENT_EVIDENCE_WORKER_DB_PASSWORD=worker-test-only \
  --volume "$repository_root/ops/postgres/init-roles.sh:/docker-entrypoint-initdb.d/10-roles.sh:ro" \
  postgres:16-alpine >/dev/null

attempt=0
until docker exec "$container_name" pg_isready --host 127.0.0.1 --username postgres --dbname patent_evidence_test >/dev/null 2>&1; do
  attempt=$((attempt + 1))
  if [ "$attempt" -ge 30 ]; then
    docker logs "$container_name"
    exit 1
  fi
  sleep 1
done

host_port=$(docker port "$container_name" 5432/tcp | sed 's/.*://')
export PATENT_EVIDENCE_MIGRATION_DATABASE_URL="postgresql+psycopg://patent_evidence_migration:migration-test-only@127.0.0.1:${host_port}/patent_evidence_test"
export PE_TEST_MIGRATION_DATABASE_URL="postgresql://patent_evidence_migration:migration-test-only@127.0.0.1:${host_port}/patent_evidence_test"
export PE_TEST_APPLICATION_DATABASE_URL="postgresql://patent_evidence_app:app-test-only@127.0.0.1:${host_port}/patent_evidence_test"
export PE_TEST_PLATFORM_DATABASE_URL="postgresql://patent_evidence_platform:platform-test-only@127.0.0.1:${host_port}/patent_evidence_test"
export PE_TEST_WORKER_DATABASE_URL="postgresql://patent_evidence_worker:worker-test-only@127.0.0.1:${host_port}/patent_evidence_test"
export PYTHONPATH="$repository_root/apps/api/src"

cd "$repository_root"
uv sync --frozen --no-install-project
.venv/bin/alembic -c apps/api/alembic.ini upgrade head
.venv/bin/pytest \
  apps/api/tests/integration/test_database_roles_and_rls.py \
  apps/api/tests/integration/test_database_context.py \
  apps/api/tests/integration/test_authentication_api.py
