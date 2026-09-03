"""S3Connector — MVP connector per architecture.md §3, using `boto3`.

`discover()` walks configured bucket/prefixes (each configured prefix is
one logical "Dataset", per spec.md's Dataset entity — S3 has no guaranteed
schema so datasets are grouped by prefix, not walked file-by-file into
separate entities). `extract_metadata()` captures Dataset fields: format,
size/count estimates, and (best-effort) an inferred column-shaped `fields`
list when `schema_inferred` is true. Partitioning is inferred from
Hive-style `key=value` path segments. No lineage (BaseConnector default
applies as-is).

DEVIATION FROM spec.md, flagged for FE1: spec.md's Dataset field list does
not enumerate `partition_keys` or `source_last_modified_at`, but
architecture.md §3 explicitly calls for "partitioning inferred from key
structure" and "last-modified" to be captured. Both are included in the
payload below as additive fields beyond spec.md's minimum list — check
against `shared/schema/` once it lands and drop/rename if it disagrees.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional

from connectors.core.types import (
    Cursor,
    EntityType,
    HealthStatus,
    NormalizedEntity,
    Operation,
    RawEntity,
    diff_deleted_urns,
    utcnow,
)
from connectors.core.base import BaseConnector

from . import s3_ops
from .schema_inference import (
    aggregate_format,
    infer_csv_schema,
    infer_parquet_schema,
    infer_partitioning,
)


@dataclass
class S3Config:
    source_connection_id: str
    bucket: str
    prefixes: List[str]
    endpoint_url: Optional[str] = None
    region_name: str = "us-east-1"
    aws_access_key_id: Optional[str] = None
    aws_secret_access_key: Optional[str] = None
    use_path_style: bool = False
    sample_limit: int = s3_ops.DEFAULT_SAMPLE_LIMIT
    sniff_bytes: int = s3_ops.DEFAULT_SNIFF_BYTES

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "S3Config":
        required = ["source_connection_id", "bucket", "prefixes"]
        missing = [k for k in required if not d.get(k)]
        if missing:
            raise ValueError(f"S3Config missing required fields: {missing}")
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in d.items() if k in known})


class S3Connector(BaseConnector):
    connector_type = "s3"

    def __init__(self) -> None:
        self._config: Optional[S3Config] = None
        self._client: Any = None
        self._cursor_state: Optional[Cursor] = None

    # -- BaseConnector -----------------------------------------------------

    def connect(self, config: dict) -> None:
        self._config = S3Config.from_dict(config)
        import boto3  # local import: not required unless actually connecting
        from botocore.config import Config as BotoConfig

        boto_config = None
        if self._config.use_path_style:
            boto_config = BotoConfig(s3={"addressing_style": "path"})

        self._client = boto3.client(
            "s3",
            endpoint_url=self._config.endpoint_url,
            region_name=self._config.region_name,
            aws_access_key_id=self._config.aws_access_key_id,
            aws_secret_access_key=self._config.aws_secret_access_key,
            config=boto_config,
        )
        if self._cursor_state is None:
            self._cursor_state = Cursor.empty(self._config.source_connection_id)

    def health_check(self) -> HealthStatus:
        if self._client is None or self._config is None:
            return HealthStatus(ok=False, detail="not connected")
        try:
            self._client.head_bucket(Bucket=self._config.bucket)
            return HealthStatus(ok=True, detail=f"head_bucket({self._config.bucket}) succeeded")
        except Exception as exc:  # noqa: BLE001
            return HealthStatus(ok=False, detail=str(exc))

    def discover(self) -> Iterator[RawEntity]:
        if self._client is None or self._config is None:
            raise RuntimeError("S3Connector.discover() called before connect()")
        cursor_state = self._cursor_state or Cursor.empty(self._config.source_connection_id)

        seen_dataset_urns: List[str] = []
        for prefix in self._config.prefixes:
            list_result = s3_ops.list_prefix(
                self._client, self._config.bucket, prefix, sample_limit=self._config.sample_limit
            )
            if list_result.object_count == 0:
                continue  # nothing there (yet) -> not reported; drift handled below if it *was* known
            urn = self._dataset_urn(prefix)
            seen_dataset_urns.append(urn)
            yield RawEntity(
                entity_type=EntityType.DATASET.value,
                key=prefix,
                raw={"prefix": prefix, "list_result": list_result},
            )

        for urn in diff_deleted_urns(cursor_state, seen_dataset_urns, entity_type=EntityType.DATASET.value):
            yield RawEntity(entity_type=EntityType.DATASET.value, key=urn, raw={}, tombstone=True)

    def extract_metadata(self, entity: RawEntity) -> NormalizedEntity:
        if entity.tombstone:
            return self._tombstone_to_normalized(entity)
        if entity.entity_type == EntityType.DATASET.value:
            return self._dataset_to_normalized(entity)
        raise ValueError(f"S3Connector cannot extract unknown entity_type={entity.entity_type!r}")

    # extract_lineage: not overridden -> BaseConnector default (empty).

    def get_cursor(self) -> Cursor:
        if self._cursor_state is None:
            self._cursor_state = Cursor.empty(
                self._config.source_connection_id if self._config else ""
            )
        return self._cursor_state

    def set_cursor(self, cursor: Cursor) -> None:
        self._cursor_state = cursor

    # -- internal --------------------------------------------------------

    def _dataset_urn(self, prefix: str) -> str:
        assert self._config is not None
        return f"urn:s3:{self._config.bucket}/{prefix}"

    def _record_cursor(self, normalized: NormalizedEntity) -> None:
        cursor_state = self.get_cursor()
        if normalized.operation == Operation.DELETE.value:
            cursor_state.forget(normalized.urn)
        else:
            cursor_state.record(
                normalized.urn,
                normalized.entity_type,
                normalized.content_hash,
                when=normalized.extracted_at,
            )

    def _infer_fields(self, prefix: str, file_format: str, sample_keys: List[str]):
        assert self._config is not None
        if not sample_keys:
            return None
        sample_key = sample_keys[0]
        sample_bytes = s3_ops.sniff_object_bytes(
            self._client, self._config.bucket, sample_key, max_bytes=self._config.sniff_bytes
        )
        if sample_bytes is None:
            return None
        if file_format == "csv":
            return infer_csv_schema(sample_bytes)
        if file_format == "parquet":
            return infer_parquet_schema(sample_bytes)
        return None

    def _dataset_to_normalized(self, entity: RawEntity) -> NormalizedEntity:
        assert self._config is not None
        prefix = entity.raw["prefix"]
        list_result: s3_ops.ListResult = entity.raw["list_result"]
        urn = self._dataset_urn(prefix)

        file_format = aggregate_format(list_result.sample_keys)
        partition_keys = infer_partitioning(list_result.sample_keys, prefix)
        fields = self._infer_fields(prefix, file_format, list_result.sample_keys)
        schema_inferred = fields is not None

        payload: Dict[str, Any] = {
            "source_type": "s3",
            "source_connection_id": self._config.source_connection_id,
            "bucket": self._config.bucket,
            "prefix": prefix,
            "fully_qualified_name": f"s3://{self._config.bucket}/{prefix}",
            "file_format": file_format,
            "schema_inferred": schema_inferred,
            "object_count_estimate": list_result.object_count,
            "total_size_bytes_estimate": list_result.total_size_bytes,
            "description": None,
            "owner": None,
            "owner_source": None,
            "tags": [],
            # Additive beyond spec.md's minimum Dataset field list, per
            # architecture.md §3's explicit requirement -- see module
            # docstring.
            "partition_keys": partition_keys,
            "source_last_modified_at": list_result.last_modified_iso,
        }
        if schema_inferred:
            payload["fields"] = fields

        normalized = NormalizedEntity(
            urn=urn,
            entity_type=EntityType.DATASET.value,
            operation=Operation.UPSERT.value,
            payload=payload,
        )
        self._record_cursor(normalized)
        return normalized

    def _tombstone_to_normalized(self, entity: RawEntity) -> NormalizedEntity:
        assert self._config is not None
        payload = {
            "source_type": "s3",
            "source_connection_id": self._config.source_connection_id,
        }
        normalized = NormalizedEntity(
            urn=entity.key,
            entity_type=entity.entity_type,
            operation=Operation.DELETE.value,
            payload=payload,
            extracted_at=utcnow(),
        )
        self._record_cursor(normalized)
        return normalized
