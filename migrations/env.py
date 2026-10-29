from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import get_settings

config = context.config
settings = get_settings()
database_url = settings.migration_database_url or settings.database_url
if not database_url.startswith(("postgresql://", "postgres://", "postgresql+psycopg://")):
    raise RuntimeError("Alembic migrations are for PostgreSQL. SQLite demo setup runs automatically.")
sqlalchemy_url = database_url.replace("postgres://", "postgresql://", 1)
sqlalchemy_url = sqlalchemy_url.replace("postgresql://", "postgresql+psycopg://", 1)
config.set_main_option("sqlalchemy.url", sqlalchemy_url.replace("%", "%%"))

target_metadata = None


def run_migrations_offline() -> None:
    context.configure(url=sqlalchemy_url, literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
