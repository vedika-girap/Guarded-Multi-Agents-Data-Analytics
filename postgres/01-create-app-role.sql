DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'assistant_app') THEN
        CREATE ROLE assistant_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
END
$$;
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'assistant_reader') THEN
        CREATE ROLE assistant_reader NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
    END IF;
END
$$;
ALTER ROLE assistant_app PASSWORD :'app_password';
GRANT CONNECT ON DATABASE analytics TO assistant_app;
