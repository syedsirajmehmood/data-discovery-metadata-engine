"""Engine/session construction for the Postgres system-of-record.

Reads connection settings from environment variables so the same code runs
against docker-compose locally and against a managed Postgres in production
without a code change:

- ``POSTGRES_DSN`` — full SQLAlchemy DSN, e.g.
  ``postgresql+psycopg://user:pass@host:5432/catalog``. Takes precedence if set.
- Otherwise built from ``POSTGRES_HOST`` (default ``localhost``),
  ``POSTGRES_PORT`` (default ``5432``), ``POSTGRES_DB`` (default ``catalog``),
  ``POSTGRES_USER`` (default ``catalog``), ``POSTGRES_PASSWORD`` (default ``catalog``).
"""

from __future__ import annotations

import os
from typing import Optional

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


def build_dsn() -> str:
    dsn = os.environ.get("POSTGRES_DSN")
    if dsn:
        return dsn
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    db = os.environ.get("POSTGRES_DB", "catalog")
    user = os.environ.get("POSTGRES_USER", "catalog")
    password = os.environ.get("POSTGRES_PASSWORD", "catalog")
    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{db}"


def make_engine(dsn: Optional[str] = None, **kwargs) -> Engine:
    return create_engine(dsn or build_dsn(), future=True, **kwargs)


def make_session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
