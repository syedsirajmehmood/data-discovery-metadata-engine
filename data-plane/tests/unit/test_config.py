import json

import pytest

from agent.config import AgentConfig, ConfigError, SourceConfig


REQUIRED_ENV = {
    "DP_CONTROL_PLANE_URL": "https://cp.example.com",
    "DP_API_KEY": "key-123",
    "DP_DATA_PLANE_ID": "dp-1",
}


def test_from_env_requires_control_plane_url_api_key_data_plane_id():
    with pytest.raises(ConfigError):
        AgentConfig.from_env(env={})


def test_from_env_reports_all_missing_vars():
    with pytest.raises(ConfigError) as excinfo:
        AgentConfig.from_env(env={"DP_API_KEY": "x"})
    assert "DP_CONTROL_PLANE_URL" in str(excinfo.value)
    assert "DP_DATA_PLANE_ID" in str(excinfo.value)


def test_from_env_applies_defaults():
    config = AgentConfig.from_env(env=REQUIRED_ENV)
    assert config.control_plane_url == "https://cp.example.com"
    assert config.scrape_interval_seconds == 6 * 60 * 60
    assert config.max_batch_entities == 500
    assert config.max_batch_interval_seconds == 60
    assert config.retry_max_attempts == 6
    assert config.sources == []


def test_from_env_overrides_are_honored():
    env = dict(REQUIRED_ENV)
    env.update({"DP_MAX_BATCH_ENTITIES": "10", "DP_SCRAPE_INTERVAL_SECONDS": "60"})
    config = AgentConfig.from_env(env=env)
    assert config.max_batch_entities == 10
    assert config.scrape_interval_seconds == 60


def test_control_plane_url_never_hardcoded_must_come_from_env_or_explicit_sources():
    # There is no default value baked into AgentConfig.from_env for the URL --
    # asserting the field has no class-level default enforces this at the
    # dataclass level too (a required positional field, not `= "..."`).
    field = AgentConfig.__dataclass_fields__["control_plane_url"]
    import dataclasses

    assert field.default is dataclasses.MISSING
    assert field.default_factory is dataclasses.MISSING  # type: ignore[comparison-overlap]


def test_sources_file_yaml(tmp_path):
    sources_file = tmp_path / "sources.yaml"
    sources_file.write_text(
        """
sources:
  - connector_type: postgres
    source_connection_id: prod-pg-1
    config:
      host: localhost
      database: demo
      user: demo
      password: demo
  - connector_type: s3
    source_connection_id: prod-s3-1
    config:
      bucket: demo-bucket
      prefixes: ["events/"]
"""
    )
    config = AgentConfig.from_env(env=REQUIRED_ENV, sources_file=str(sources_file))
    assert len(config.sources) == 2
    assert config.sources[0].connector_type == "postgres"
    assert config.sources[0].source_connection_id == "prod-pg-1"
    assert config.sources[0].config["host"] == "localhost"
    # source_connection_id is copied into the connector-facing config dict too
    assert config.sources[0].config["source_connection_id"] == "prod-pg-1"


def test_sources_file_json(tmp_path):
    sources_file = tmp_path / "sources.json"
    sources_file.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "connector_type": "s3",
                        "source_connection_id": "s3-1",
                        "config": {"bucket": "b", "prefixes": ["p/"]},
                    }
                ]
            }
        )
    )
    config = AgentConfig.from_env(env=REQUIRED_ENV, sources_file=str(sources_file))
    assert len(config.sources) == 1
    assert config.sources[0].connector_type == "s3"


def test_source_config_from_dict_requires_connector_type_and_id():
    with pytest.raises(Exception):
        SourceConfig.from_dict({"config": {}})
