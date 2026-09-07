-- Run once as the local PostgreSQL administrator, after backup/image upgrade.
-- Application DSN remains a non-superuser role; never grant it extension administration.
\set ON_ERROR_STOP on
CREATE SCHEMA IF NOT EXISTS retailops_extensions AUTHORIZATION postgres;
REVOKE ALL ON SCHEMA retailops_extensions FROM PUBLIC;
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA retailops_extensions;
GRANT USAGE ON SCHEMA retailops_extensions TO retailops;
SELECT extversion, extnamespace::regnamespace FROM pg_extension WHERE extname='vector';
