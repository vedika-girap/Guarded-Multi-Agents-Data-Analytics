"""Database connection abstraction for the local SQLite and optional PostgreSQL backends."""
from contextlib import contextmanager
from pathlib import Path
import sqlite3
from typing import Iterator

import psycopg
from psycopg.rows import dict_row

from app.config import ROOT, Settings, get_settings


class DatabaseUnavailable(RuntimeError):
    """The configured database could not be reached."""


class DatabaseQueryTimeout(RuntimeError):
    """A read-only query exceeded its execution budget."""


def is_postgresql(settings: Settings | None = None) -> bool:
    url = (settings or get_settings()).database_url
    return url.startswith(("postgresql://", "postgres://", "postgresql+psycopg://"))


def sqlite_path(url: str) -> Path:
    if not url.startswith("sqlite:///"):
        raise ValueError("DATABASE_URL must use sqlite:/// or postgresql://")
    raw_path = url.removeprefix("sqlite:///")
    path = Path(raw_path)
    return path if path.is_absolute() else ROOT / path


@contextmanager
def connect_readonly(
    tenant_id: str,
    role: str,
    settings: Settings | None = None,
) -> Iterator[sqlite3.Connection | psycopg.Connection]:
    settings = settings or get_settings()
    if is_postgresql(settings):
        dsn = settings.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
        try:
            connection = psycopg.connect(dsn, row_factory=dict_row)
        except psycopg.OperationalError:
            raise DatabaseUnavailable("The configured PostgreSQL database is unavailable.") from None
        try:
            connection.execute("SET TRANSACTION READ ONLY")
            connection.execute(
                "SELECT set_config('statement_timeout', %s, true)",
                (f"{settings.database_statement_timeout_ms}ms",),
            )
            connection.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant_id,))
            connection.execute("SELECT set_config('app.user_role', %s, true)", (role,))
            yield connection
        except psycopg.errors.QueryCanceled:
            raise DatabaseQueryTimeout("The database query exceeded its execution time limit.") from None
        except (psycopg.OperationalError, psycopg.InterfaceError):
            raise DatabaseUnavailable("The configured PostgreSQL database is unavailable.") from None
        finally:
            try:
                connection.rollback()
            except psycopg.Error:
                pass
            finally:
                connection.close()
        return

    path = sqlite_path(settings.database_url)
    try:
        connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    except sqlite3.OperationalError:
        raise DatabaseUnavailable("The configured SQLite database is unavailable.") from None
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        connection.set_progress_handler(lambda: 1, 100_000)
        yield connection
    except sqlite3.OperationalError as exc:
        if "interrupted" in str(exc).lower():
            raise DatabaseQueryTimeout("The SQLite query exceeded its execution budget.") from None
        raise
    finally:
        connection.close()
