"""Pure helpers for the S3 connector: file-format detection, Hive-style
partition inference from key structure, and best-effort schema inference
for CSV/Parquet objects. No boto3 dependency in this module — everything
here operates on plain strings/bytes so it's trivially unit-testable.
"""
from __future__ import annotations

import csv
import io
import re
from collections import Counter
from typing import Any, Dict, List, Optional

_PARTITION_SEGMENT = re.compile(r"^([A-Za-z0-9_.\-]+)=(.*)$")

_EXTENSION_FORMAT = {
    "parquet": "parquet",
    "csv": "csv",
    "tsv": "csv",
    "json": "json",
    "jsonl": "json",
    "ndjson": "json",
}


def detect_format_from_key(key: str) -> str:
    """Best-effort file format from a key's extension. 'unknown' when the
    extension isn't recognized (e.g. extensionless keys, `.gz`-only)."""
    name = key.rsplit("/", 1)[-1]
    if "." not in name:
        return "unknown"
    ext = name.rsplit(".", 1)[-1].lower()
    # tolerate one layer of compression suffix, e.g. "part-0.csv.gz"
    if ext in ("gz", "gzip", "zst", "snappy") and "." in name[: -(len(ext) + 1)]:
        inner = name[: -(len(ext) + 1)].rsplit(".", 1)[-1].lower()
        ext = inner
    return _EXTENSION_FORMAT.get(ext, "unknown")


def aggregate_format(keys: List[str]) -> str:
    """Roll up per-object formats into one Dataset-level `file_format`."""
    if not keys:
        return "unknown"
    formats = Counter(detect_format_from_key(k) for k in keys)
    recognized = {f: c for f, c in formats.items() if f != "unknown"}
    if not recognized:
        return "unknown"
    if len(recognized) == 1:
        return next(iter(recognized))
    return "mixed"


def infer_partitioning(keys: List[str], prefix: str) -> List[str]:
    """Hive-style `key=value` path segments relative to `prefix`, e.g.
    `year=2024/month=01/day=02/part-0.parquet` under prefix `events/` ->
    `["year", "month", "day"]`. Order is first-seen order across the
    sampled keys; empty list when no partition-shaped segments are found.
    """
    seen: List[str] = []
    seen_set = set()
    norm_prefix = prefix if prefix.endswith("/") or prefix == "" else prefix + "/"
    for key in keys:
        rel = key[len(norm_prefix):] if key.startswith(norm_prefix) else key
        segments = rel.split("/")[:-1]  # exclude the object's own filename
        for seg in segments:
            m = _PARTITION_SEGMENT.match(seg)
            if m:
                name = m.group(1)
                if name not in seen_set:
                    seen_set.add(name)
                    seen.append(name)
    return seen


def _sniff_scalar_type(value: str) -> str:
    if value == "":
        return "string"
    try:
        int(value)
        return "integer"
    except ValueError:
        pass
    try:
        float(value)
        return "float"
    except ValueError:
        pass
    if value.lower() in ("true", "false"):
        return "boolean"
    return "string"


def infer_csv_schema(sample_bytes: bytes) -> Optional[List[Dict[str, Any]]]:
    """Parses a header row (and, if present, one data row for lightweight
    type sniffing) from a CSV sample. Returns None if the sample can't be
    decoded/parsed at all (caller should treat as schema_inferred=False)."""
    try:
        text = sample_bytes.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return None
    lines = text.splitlines()
    if not lines:
        return None
    try:
        reader = csv.reader(lines)
        rows = list(reader)
    except csv.Error:
        return None
    if not rows or not rows[0]:
        return None
    header = rows[0]
    first_data_row = rows[1] if len(rows) > 1 else []
    fields = []
    for i, name in enumerate(header):
        native_type = "string"
        if i < len(first_data_row):
            native_type = _sniff_scalar_type(first_data_row[i])
        fields.append(
            {
                "name": name.strip(),
                "ordinal_position": i + 1,
                "native_data_type": native_type,
                "normalized_data_type": native_type,
                "is_nullable": True,
                "is_primary_key": False,
                "is_foreign_key": False,
                "foreign_key_ref": None,
                "description": None,
                "description_source": None,
                "tags": [],
            }
        )
    return fields


_PARQUET_TYPE_TO_NORMALIZED = {
    "int8": "integer", "int16": "integer", "int32": "integer", "int64": "integer",
    "uint8": "integer", "uint16": "integer", "uint32": "integer", "uint64": "integer",
    "float": "float", "double": "float", "decimal128": "float",
    "bool": "boolean",
    "string": "string", "large_string": "string",
    "binary": "binary", "large_binary": "binary",
    "date32": "date", "date64": "date",
    "timestamp": "timestamp",
}


def infer_parquet_schema(sample_bytes: bytes) -> Optional[List[Dict[str, Any]]]:
    """Best-effort Parquet schema read via `pyarrow`, an optional
    dependency. Returns None (not an error) when pyarrow isn't installed or
    the sample can't be parsed as Parquet — callers treat that the same as
    "couldn't infer a schema" (AC-2a), not a connector failure."""
    try:
        import pyarrow.parquet as pq  # type: ignore
    except ImportError:
        return None
    try:
        reader = pq.ParquetFile(io.BytesIO(sample_bytes))
        schema = reader.schema_arrow
    except Exception:  # noqa: BLE001 - any parse failure -> no inference
        return None

    fields = []
    for i, f in enumerate(schema):
        arrow_type = str(f.type).split("(")[0].split("[")[0]
        normalized = _PARQUET_TYPE_TO_NORMALIZED.get(arrow_type, "other")
        fields.append(
            {
                "name": f.name,
                "ordinal_position": i + 1,
                "native_data_type": str(f.type),
                "normalized_data_type": normalized,
                "is_nullable": bool(f.nullable),
                "is_primary_key": False,
                "is_foreign_key": False,
                "foreign_key_ref": None,
                "description": None,
                "description_source": None,
                "tags": [],
            }
        )
    return fields
