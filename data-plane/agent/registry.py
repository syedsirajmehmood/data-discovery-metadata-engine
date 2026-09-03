"""Connector registry: `connector_type` string -> `BaseConnector` subclass.

This is the ONE place a new connector is wired into the agent. Per
architecture.md §3: "a new source = a new class implementing
`BaseConnector`, registered in agent config -- zero changes to
`data-plane/agent/`." Adding e.g. `DbtConnector` later means adding one
import + one dict entry here; `runner.py` never changes.
"""
from __future__ import annotations

from typing import Dict, Type

from connectors.core.base import BaseConnector
from connectors.postgres import PostgresConnector
from connectors.s3 import S3Connector

CONNECTOR_REGISTRY: Dict[str, Type[BaseConnector]] = {
    PostgresConnector.connector_type: PostgresConnector,
    S3Connector.connector_type: S3Connector,
}


def build_connector(connector_type: str) -> BaseConnector:
    cls = CONNECTOR_REGISTRY.get(connector_type)
    if cls is None:
        raise ValueError(
            f"Unknown connector_type={connector_type!r}. Registered: {sorted(CONNECTOR_REGISTRY)}"
        )
    return cls()
