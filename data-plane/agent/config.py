"""Agent configuration.

Per decisions.md ("airgapped mode is a future deployment target ... do not
hardcode the owner's SaaS URL into the data plane") and architecture.md §2
("`control-plane-host` is a config value in the data-plane agent, never
hardcoded"): the control-plane URL and API key are ALWAYS read from
environment variables (or an explicit override passed by tests), never
embedded as defaults/constants in code.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional


class ConfigError(ValueError):
    pass


@dataclass
class SourceConfig:
    connector_type: str
    source_connection_id: str
    config: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SourceConfig":
        for key in ("connector_type", "source_connection_id"):
            if not d.get(key):
                raise ConfigError(f"source entry missing required key {key!r}: {d!r}")
        cfg = dict(d.get("config", {}))
        # source_connection_id is required inside each connector's own
        # config dict too (BaseConnector implementations use it to build
        # urns) -- copy it in so callers don't have to repeat themselves.
        cfg.setdefault("source_connection_id", d["source_connection_id"])
        return cls(
            connector_type=d["connector_type"],
            source_connection_id=d["source_connection_id"],
            config=cfg,
        )


def _load_sources_file(path: str) -> List[SourceConfig]:
    text = Path(path).read_text()
    if path.endswith((".yaml", ".yml")):
        import yaml  # local import: only needed if a YAML sources file is used

        data = yaml.safe_load(text) or {}
    else:
        data = json.loads(text) if text.strip() else {}
    entries = data.get("sources", [])
    return [SourceConfig.from_dict(e) for e in entries]


@dataclass
class AgentConfig:
    control_plane_url: str
    api_key: str
    data_plane_id: str
    sources: List[SourceConfig] = field(default_factory=list)

    schema_version: str = "1.0"

    # Scheduler (NFR-1 default: every 6 hours)
    scrape_interval_seconds: int = 6 * 60 * 60

    # Batching (architecture.md §2 defaults)
    max_batch_entities: int = 500
    max_batch_interval_seconds: int = 60

    # Retry/backoff (architecture.md §2: base 5s, cap ~5min, ~6 attempts over ~15min)
    retry_base_seconds: float = 5.0
    retry_cap_seconds: float = 300.0
    retry_max_attempts: int = 6
    request_timeout_seconds: float = 30.0

    # Local, data-plane-only state (never sent to the control plane)
    cursor_dir: str = "./data/cursors"
    dead_letter_dir: str = "./data/dead_letter"

    @classmethod
    def from_env(
        cls,
        env: Optional[Mapping[str, str]] = None,
        sources_file: Optional[str] = None,
        sources: Optional[List[SourceConfig]] = None,
    ) -> "AgentConfig":
        env = env if env is not None else os.environ

        control_plane_url = env.get("DP_CONTROL_PLANE_URL")
        api_key = env.get("DP_API_KEY")
        data_plane_id = env.get("DP_DATA_PLANE_ID")
        missing = [
            name
            for name, val in (
                ("DP_CONTROL_PLANE_URL", control_plane_url),
                ("DP_API_KEY", api_key),
                ("DP_DATA_PLANE_ID", data_plane_id),
            )
            if not val
        ]
        if missing:
            raise ConfigError(
                f"Missing required env var(s): {missing}. Control-plane URL and API "
                "key must be supplied via config/env, never hardcoded (decisions.md)."
            )

        resolved_sources = sources
        if resolved_sources is None:
            path = sources_file or env.get("DP_SOURCES_CONFIG_FILE")
            resolved_sources = _load_sources_file(path) if path else []

        def _int(name: str, default: int) -> int:
            return int(env[name]) if env.get(name) else default

        def _float(name: str, default: float) -> float:
            return float(env[name]) if env.get(name) else default

        return cls(
            control_plane_url=control_plane_url,  # type: ignore[arg-type]
            api_key=api_key,  # type: ignore[arg-type]
            data_plane_id=data_plane_id,  # type: ignore[arg-type]
            sources=resolved_sources,
            schema_version=env.get("DP_SCHEMA_VERSION", "1.0"),
            scrape_interval_seconds=_int("DP_SCRAPE_INTERVAL_SECONDS", 6 * 60 * 60),
            max_batch_entities=_int("DP_MAX_BATCH_ENTITIES", 500),
            max_batch_interval_seconds=_int("DP_MAX_BATCH_INTERVAL_SECONDS", 60),
            retry_base_seconds=_float("DP_RETRY_BASE_SECONDS", 5.0),
            retry_cap_seconds=_float("DP_RETRY_CAP_SECONDS", 300.0),
            retry_max_attempts=_int("DP_RETRY_MAX_ATTEMPTS", 6),
            request_timeout_seconds=_float("DP_REQUEST_TIMEOUT_SECONDS", 30.0),
            cursor_dir=env.get("DP_CURSOR_DIR", "./data/cursors"),
            dead_letter_dir=env.get("DP_DEAD_LETTER_DIR", "./data/dead_letter"),
        )
