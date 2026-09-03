"""boto3-driven S3 listing/sampling, decoupled behind a duck-typed `client`
parameter (anything exposing `get_paginator`/`list_objects_v2` and
`get_object`/`head_object` the way a real `boto3` S3 client does) so unit
tests can pass a lightweight fake client instead of talking to real S3/
MinIO.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional

DEFAULT_SAMPLE_LIMIT = 1000
DEFAULT_SNIFF_BYTES = 65536


@dataclass
class ListResult:
    object_count: int = 0
    total_size_bytes: int = 0
    sample_keys: List[str] = field(default_factory=list)
    last_modified_iso: Optional[str] = None


def list_prefix(
    client: Any,
    bucket: str,
    prefix: str,
    sample_limit: int = DEFAULT_SAMPLE_LIMIT,
) -> ListResult:
    result = ListResult()
    latest = None
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []) or []:
            key = obj["Key"]
            # Skip "directory marker" objects (zero-byte keys ending in "/")
            if key.endswith("/") and obj.get("Size", 0) == 0:
                continue
            result.object_count += 1
            result.total_size_bytes += int(obj.get("Size", 0))
            if len(result.sample_keys) < sample_limit:
                result.sample_keys.append(key)
            lm = obj.get("LastModified")
            if lm is not None and (latest is None or lm > latest):
                latest = lm
    if latest is not None:
        result.last_modified_iso = latest.isoformat() if hasattr(latest, "isoformat") else str(latest)
    return result


def sniff_object_bytes(client: Any, bucket: str, key: str, max_bytes: int = DEFAULT_SNIFF_BYTES) -> Optional[bytes]:
    """Read up to `max_bytes` from the start of an object. Returns None on
    any failure (missing object, permission error, etc.) rather than
    raising — the caller treats that the same as "no schema inferrable"."""
    try:
        try:
            resp = client.get_object(Bucket=bucket, Key=key, Range=f"bytes=0-{max_bytes - 1}")
        except TypeError:
            # fake/test clients may not support the Range kwarg
            resp = client.get_object(Bucket=bucket, Key=key)
        body = resp["Body"]
        data = body.read(max_bytes) if hasattr(body, "read") else bytes(body)
        return data
    except Exception:  # noqa: BLE001 - sampling failures are not fatal
        return None
