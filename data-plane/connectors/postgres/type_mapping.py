"""Map Postgres' `format_type()` native type strings to the catalog's
canonical `normalized_data_type` buckets (spec.md: "needed so search/UI can
group/filter across Postgres and future sources consistently")."""
from __future__ import annotations

import re

_INT_TYPES = {"smallint", "integer", "bigint", "int2", "int4", "int8", "serial", "bigserial", "smallserial"}
_FLOAT_TYPES = {"real", "double precision", "numeric", "decimal", "float4", "float8", "money"}
_STRING_TYPES = {"character varying", "varchar", "character", "char", "text", "bpchar", "citext"}
_BOOL_TYPES = {"boolean", "bool"}
_TIMESTAMP_TYPES = {"timestamp", "timestamp without time zone", "timestamp with time zone", "timestamptz"}
_DATE_TYPES = {"date"}
_TIME_TYPES = {"time", "time without time zone", "time with time zone", "timetz"}
_JSON_TYPES = {"json", "jsonb"}
_UUID_TYPES = {"uuid"}
_BINARY_TYPES = {"bytea"}
_ARRAY_SUFFIX = re.compile(r"\[\]$")


def normalize_type(native_type: str) -> str:
    """Best-effort bucket for a Postgres `format_type()` string, which may
    include type modifiers, e.g. `character varying(255)`, `numeric(10,2)`.
    """
    if not native_type:
        return "unknown"
    t = native_type.strip().lower()
    is_array = bool(_ARRAY_SUFFIX.search(t))
    if is_array:
        t = _ARRAY_SUFFIX.sub("", t).strip()
    # strip parenthesized modifiers, e.g. "numeric(10,2)" -> "numeric"
    base = re.sub(r"\(.*\)$", "", t).strip()

    if base in _INT_TYPES:
        bucket = "integer"
    elif base in _FLOAT_TYPES:
        bucket = "float"
    elif base in _STRING_TYPES:
        bucket = "string"
    elif base in _BOOL_TYPES:
        bucket = "boolean"
    elif base in _TIMESTAMP_TYPES:
        bucket = "timestamp"
    elif base in _DATE_TYPES:
        bucket = "date"
    elif base in _TIME_TYPES:
        bucket = "time"
    elif base in _JSON_TYPES:
        bucket = "json"
    elif base in _UUID_TYPES:
        bucket = "uuid"
    elif base in _BINARY_TYPES:
        bucket = "binary"
    else:
        bucket = "other"

    return f"array<{bucket}>" if is_array else bucket
