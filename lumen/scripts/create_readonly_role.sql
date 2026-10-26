-- Optional hardening: a dedicated read-only login for AI-generated and SQL-console queries.
-- Run as a superuser / role with CREATEROLE, then set READONLY_DATABASE_URL in backend/.env:
--   READONLY_DATABASE_URL=postgresql+psycopg://lumen_reader@localhost:5432/lumen_analytics
-- (store the password in pgpass.conf or PGPASSWORD rather than in the URL).
--
--   psql -U postgres -d lumen_analytics -v pw="'choose-a-password'" -f scripts/create_readonly_role.sql

CREATE ROLE lumen_reader LOGIN PASSWORD :pw NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
ALTER ROLE lumen_reader SET default_transaction_read_only = on;
ALTER ROLE lumen_reader SET statement_timeout = '15s';
REVOKE ALL ON SCHEMA public FROM lumen_reader;
GRANT CONNECT ON DATABASE lumen_analytics TO lumen_reader;

-- Grant read access to every workspace schema (ws_*). Re-run after creating new workspaces,
-- or let the app owner's default privileges cover future tables:
DO $$
DECLARE s text;
BEGIN
  FOR s IN SELECT nspname FROM pg_namespace WHERE nspname LIKE 'ws\_%' LOOP
    EXECUTE format('GRANT USAGE ON SCHEMA %I TO lumen_reader', s);
    EXECUTE format('GRANT SELECT ON ALL TABLES IN SCHEMA %I TO lumen_reader', s);
  END LOOP;
END $$;
-- The metadata schema (lumen_meta) is intentionally NOT granted.
