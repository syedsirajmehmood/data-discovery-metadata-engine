"""ClickHouse client construction from environment variables.

- ``CLICKHOUSE_HOST`` (default ``localhost``), ``CLICKHOUSE_PORT`` (default ``8123``, HTTP interface)
- ``CLICKHOUSE_USER`` (default ``default``), ``CLICKHOUSE_PASSWORD`` (default ``""``)
- ``CLICKHOUSE_DATABASE`` (default ``catalog``)
"""

from __future__ import annotations

import os

import clickhouse_connect
from clickhouse_connect.driver.client import Client


def build_client() -> Client:
    return clickhouse_connect.get_client(
        host=os.environ.get("CLICKHOUSE_HOST", "localhost"),
        port=int(os.environ.get("CLICKHOUSE_PORT", "8123")),
        username=os.environ.get("CLICKHOUSE_USER", "default"),
        password=os.environ.get("CLICKHOUSE_PASSWORD", ""),
        database=os.environ.get("CLICKHOUSE_DATABASE", "catalog"),
    )
