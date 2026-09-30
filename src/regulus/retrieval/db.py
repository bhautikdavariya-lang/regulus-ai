"""Minimal read-only PostgreSQL access.

Read-only is enforced by the server, not by convention:
  * the connection is opened with `-c default_transaction_read_only=on`
  * psycopg's `Connection.read_only = True` additionally issues
    SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY
Any INSERT/UPDATE/DELETE/DDL raises ReadOnlySqlTransaction before touching
data. This module exposes only `query()`; there is no execute-for-write path.

The URL comes from REGULUS_DATABASE_URL (environment or .env). It is never
logged; `DatabaseConfig.redacted()` masks the password for diagnostics.
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator, Mapping, Sequence
from urllib.parse import urlsplit, urlunsplit

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

from regulus.config import PROJECT_ROOT

log = logging.getLogger("regulus.retrieval.db")

ENV_VAR = "REGULUS_DATABASE_URL"
APPLICATION_NAME = "regulus-retrieval"


class DatabaseConfigError(RuntimeError):
    """Missing or malformed database configuration."""


@dataclass(frozen=True)
class DatabaseConfig:
    url: str
    connect_timeout: int = 10
    statement_timeout_ms: int = 15000

    @classmethod
    def from_env(cls, *, use_dotenv: bool = True) -> "DatabaseConfig":
        if use_dotenv:
            load_dotenv(PROJECT_ROOT / ".env", override=False)
        url = (os.environ.get(ENV_VAR) or "").strip()
        if not url:
            raise DatabaseConfigError(
                f"{ENV_VAR} is not set. Add it to .env (see .env.example); never commit it."
            )
        if not url.startswith(("postgresql://", "postgres://")):
            raise DatabaseConfigError(f"{ENV_VAR} must be a postgresql:// URL")
        return cls(url=url)

    def redacted(self) -> str:
        """URL with the password replaced, safe for logs and error messages."""
        try:
            parts = urlsplit(self.url)
        except ValueError:
            return "<unparseable url>"
        netloc = parts.netloc
        if "@" in netloc:
            creds, host = netloc.rsplit("@", 1)
            user = creds.split(":", 1)[0]
            netloc = f"{user}:***@{host}" if ":" in creds else f"{user}@{host}"
        return urlunsplit((parts.scheme, netloc, parts.path, "", ""))

    def __repr__(self) -> str:  # never leak the password through repr()
        return f"DatabaseConfig(url={self.redacted()!r})"


class Database:
    """One lazily opened, server-enforced read-only connection."""

    def __init__(self, config: DatabaseConfig) -> None:
        self.config = config
        self._conn: psycopg.Connection | None = None

    @classmethod
    def from_env(cls, *, use_dotenv: bool = True) -> "Database":
        return cls(DatabaseConfig.from_env(use_dotenv=use_dotenv))

    # -- lifecycle ---------------------------------------------------------

    def connect(self) -> psycopg.Connection:
        if self._conn is None or self._conn.closed:
            options = (
                "-c default_transaction_read_only=on "
                f"-c statement_timeout={self.config.statement_timeout_ms}"
            )
            self._conn = psycopg.connect(
                self.config.url,
                connect_timeout=self.config.connect_timeout,
                application_name=APPLICATION_NAME,
                options=options,
                row_factory=dict_row,
            )
            self._conn.read_only = True
            log.debug("connected to %s (read-only)", self.config.redacted())
        return self._conn

    def close(self) -> None:
        if self._conn is not None and not self._conn.closed:
            self._conn.close()
        self._conn = None

    def __enter__(self) -> "Database":
        self.connect()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- reads -------------------------------------------------------------

    def query(self, sql: str, params: Mapping[str, Any] | Sequence[Any] | None = None) -> list[dict[str, Any]]:
        """Run one SELECT with server-side parameters and return dict rows."""
        conn = self.connect()
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return cur.fetchall()

    @contextmanager
    def cursor(self) -> Iterator[psycopg.Cursor]:
        conn = self.connect()
        with conn.transaction():
            with conn.cursor() as cur:
                yield cur

    def status(self) -> dict[str, Any]:
        """Server version and read-only flags; no secrets."""
        row = self.query(
            "SELECT current_setting('server_version') AS server_version, "
            "current_setting('transaction_read_only') AS transaction_read_only, "
            "current_setting('default_transaction_read_only') AS default_transaction_read_only, "
            "current_user AS role, current_database() AS database"
        )[0]
        row["url"] = self.config.redacted()
        return row
