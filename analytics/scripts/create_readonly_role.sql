-- Optional hardening: a dedicated read-only login for AI-generated and SQL-console queries.
-- Run as a superuser / role with CREATEROLE, then set READONLY_DATABASE_URL in backend/.env:
--   READONLY_DATABASE_URL=postgresql+psycopg://ellementry_reader@localhost:5432/ellementry_analytics
-- (store the password in pgpass.conf or PGPASSWORD rather than in the URL).
--
--   psql -U postgres -d ellementry_analytics -v pw="'choose-a-password'" -f scripts/create_readonly_role.sql

CREATE ROLE ellementry_reader LOGIN PASSWORD :pw NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
ALTER ROLE ellementry_reader SET default_transaction_read_only = on;
ALTER ROLE ellementry_reader SET statement_timeout = '15s';
REVOKE ALL ON SCHEMA public FROM ellementry_reader;
GRANT CONNECT ON DATABASE ellementry_analytics TO ellementry_reader;

-- Grant read access to every workspace schema (ws_*). Re-run after creating new workspaces,
-- or let the app owner's default privileges cover future tables:
DO $$
DECLARE s text;
BEGIN
  FOR s IN SELECT nspname FROM pg_namespace WHERE nspname LIKE 'ws\_%' LOOP
    EXECUTE format('GRANT USAGE ON SCHEMA %I TO ellementry_reader', s);
    EXECUTE format('GRANT SELECT ON ALL TABLES IN SCHEMA %I TO ellementry_reader', s);
  END LOOP;
END $$;
-- The metadata schema (ellementry_meta) is intentionally NOT granted.
