#!/bin/sh
# First-start provisioning (runs once on an empty volume). Roles (guide 07 §8):
#   cognuance_owner — owns the database/schema; used only by the one-shot `migrate` service.
#   cognuance_app   — API/ops runtime: SELECT/INSERT/UPDATE on application tables, nothing else.
# The bootstrap superuser (POSTGRES_USER) stays inside the db container.
set -eu
: "${MIGRATOR_DB_PASSWORD:?MIGRATOR_DB_PASSWORD is required}"
: "${APP_DB_PASSWORD:?APP_DB_PASSWORD is required}"
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v db="$POSTGRES_DB" -v owner_pw="$MIGRATOR_DB_PASSWORD" -v app_pw="$APP_DB_PASSWORD" <<'SQL'
CREATE ROLE cognuance_owner LOGIN PASSWORD :'owner_pw' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
CREATE ROLE cognuance_app LOGIN PASSWORD :'app_pw' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
ALTER DATABASE :"db" OWNER TO cognuance_owner;
ALTER SCHEMA public OWNER TO cognuance_owner;
REVOKE ALL ON DATABASE :"db" FROM PUBLIC;
GRANT CONNECT, TEMPORARY ON DATABASE :"db" TO cognuance_owner;
GRANT CONNECT ON DATABASE :"db" TO cognuance_app;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO cognuance_app;
ALTER DEFAULT PRIVILEGES FOR ROLE cognuance_owner IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE ON TABLES TO cognuance_app;
ALTER DEFAULT PRIVILEGES FOR ROLE cognuance_owner IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO cognuance_app;
SQL
