#!/bin/bash
set -e

echo "Slowbooks Pro 2026 — Starting up..."

# Security checks
if [ "${POSTGRES_PASSWORD:-bookkeeper}" = "bookkeeper" ]; then
    echo "WARNING: Using default database password. Set POSTGRES_PASSWORD in .env for production use."
fi
if [ "${JWT_SECRET_KEY:-}" = "change-me-in-production-use-a-real-secret" ] || [ -z "${JWT_SECRET_KEY:-}" ]; then
    echo "WARNING: JWT_SECRET_KEY not set or using default. Generate one: openssl rand -hex 32"
fi

# Wait for PostgreSQL (max 30 seconds)
echo "Waiting for PostgreSQL..."
PG_WAIT=0
until pg_isready -h "${PGHOST:-postgres}" -p "${PGPORT:-5432}" -U "${PGUSER:-bookkeeper}" -q; do
    PG_WAIT=$((PG_WAIT + 1))
    if [ "$PG_WAIT" -ge 30 ]; then
        echo "ERROR: PostgreSQL did not become ready within 30 seconds."
        exit 1
    fi
    sleep 1
done
echo "PostgreSQL is ready."

# Run migrations
echo "Running database migrations..."
alembic upgrade head

# Seed chart of accounts (idempotent — skips if accounts exist)
echo "Seeding database..."
python scripts/seed_database.py

echo "Starting Slowbooks Pro 2026 on port ${APP_PORT:-3003}..."
exec uvicorn app.main:app --host 0.0.0.0 --port "${APP_PORT:-3003}"
