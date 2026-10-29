#!/bin/bash
set -euo pipefail
psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  --set=ON_ERROR_STOP=1 --set=app_password="$APP_DB_PASSWORD" \
  --file=/docker-entrypoint-initdb.d/01-create-app-role.sql
