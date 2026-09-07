#!/usr/bin/env bash
# Executed only by the pgvector/PostgreSQL image when its data volume is empty.
set -euo pipefail
export RETAILOPS_DB_PASSWORD
RETAILOPS_DB_PASSWORD=$(cat /run/secrets/postgres_app_password)
psql --username postgres --dbname postgres --set ON_ERROR_STOP=1 <<'SQL'
\getenv app_password RETAILOPS_DB_PASSWORD
CREATE ROLE retailops LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD :'app_password';
CREATE DATABASE retailops OWNER retailops;
\connect retailops
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
CREATE SCHEMA retailops_extensions AUTHORIZATION postgres;
REVOKE ALL ON SCHEMA retailops_extensions FROM PUBLIC;
GRANT USAGE ON SCHEMA retailops_extensions TO retailops;
CREATE EXTENSION vector WITH SCHEMA retailops_extensions;
SQL
unset RETAILOPS_DB_PASSWORD
