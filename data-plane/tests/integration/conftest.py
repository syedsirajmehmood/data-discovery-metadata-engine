"""Integration test fixtures: real Postgres + real MinIO, both expected to
be reachable at the docker-compose published ports (see
`deploy/docker-compose.yml`). Every test in this package is skipped (not
failed) if the services aren't reachable, so `pytest` still runs cleanly
without docker-compose up -- see README "Running tests" for how to start
the services first.
"""
from __future__ import annotations

import os
import socket

import pytest

PG_HOST = os.environ.get("IT_PG_HOST", "localhost")
PG_PORT = int(os.environ.get("IT_PG_PORT", "5432"))
PG_DB = os.environ.get("IT_PG_DB", "demo")
PG_USER = os.environ.get("IT_PG_USER", "demo")
PG_PASSWORD = os.environ.get("IT_PG_PASSWORD", "demo")

MINIO_ENDPOINT = os.environ.get("IT_MINIO_ENDPOINT", "http://localhost:9500")
MINIO_HOST = os.environ.get("IT_MINIO_HOST", "localhost")
MINIO_PORT = int(os.environ.get("IT_MINIO_PORT", "9500"))
MINIO_ACCESS_KEY = os.environ.get("IT_MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.environ.get("IT_MINIO_SECRET_KEY", "minioadmin")
MINIO_BUCKET = os.environ.get("IT_MINIO_BUCKET", "demo-bucket")


def _port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def require_postgres():
    if not _port_open(PG_HOST, PG_PORT):
        pytest.skip(
            f"Postgres not reachable at {PG_HOST}:{PG_PORT} -- run "
            "`docker compose -f deploy/docker-compose.yml up -d postgres` first."
        )


def require_minio():
    if not _port_open(MINIO_HOST, MINIO_PORT):
        pytest.skip(
            f"MinIO not reachable at {MINIO_HOST}:{MINIO_PORT} -- run "
            "`docker compose -f deploy/docker-compose.yml up -d minio minio-init` first."
        )


@pytest.fixture()
def pg_config():
    require_postgres()
    return {
        "source_connection_id": "it-postgres",
        "host": PG_HOST,
        "port": PG_PORT,
        "database": PG_DB,
        "user": PG_USER,
        "password": PG_PASSWORD,
        "include_schemas": ["analytics"],
    }


@pytest.fixture()
def s3_config():
    require_minio()
    return {
        "source_connection_id": "it-minio",
        "bucket": MINIO_BUCKET,
        "prefixes": ["events/", "exports/"],
        "endpoint_url": MINIO_ENDPOINT,
        "aws_access_key_id": MINIO_ACCESS_KEY,
        "aws_secret_access_key": MINIO_SECRET_KEY,
        "use_path_style": True,
    }
