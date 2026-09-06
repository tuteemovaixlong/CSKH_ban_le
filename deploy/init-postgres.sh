#!/usr/bin/env bash
# Executed only by the official PostgreSQL image when its data volume is empty.
set -euo pipefail
export RETAILOPS_DB_PASSWORD
RETAILOPS_DB_PASSWORD=$(cat /run/secrets/postgres_app_password)
psql --username postgres --dbname postgres --set ON_ERROR_STOP=1 <<'SQL'
\getenv app_password RETAILOPS_DB_PASSWORD
CREATE ROLE retailops LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD :'app_password';
CREATE DATABASE retailops OWNER retailops;
\connect retailops
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
SQL
unset RETAILOPS_DB_PASSWORD
