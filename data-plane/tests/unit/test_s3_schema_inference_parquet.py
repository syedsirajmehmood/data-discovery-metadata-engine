"""Parquet schema inference is a best-effort, optional-dependency path
(pyarrow). These tests are skipped entirely if pyarrow isn't installed --
the connector itself already treats "pyarrow missing" as
schema_inferred=False, not an error (see schema_inference.infer_parquet_schema).
"""
import io

import pytest

pyarrow = pytest.importorskip("pyarrow")
import pyarrow as pa  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402

from connectors.s3.schema_inference import infer_parquet_schema  # noqa: E402


def _sample_parquet_bytes() -> bytes:
    table = pa.table(
        {
            "id": pa.array([1, 2, 3], type=pa.int64()),
            "name": pa.array(["a", "b", "c"], type=pa.string()),
            "amount": pa.array([1.5, 2.5, 3.5], type=pa.float64()),
        }
    )
    buf = io.BytesIO()
    pq.write_table(table, buf)
    return buf.getvalue()


def test_infer_parquet_schema_maps_arrow_types():
    fields = infer_parquet_schema(_sample_parquet_bytes())
    assert fields is not None
    by_name = {f["name"]: f for f in fields}
    assert by_name["id"]["normalized_data_type"] == "integer"
    assert by_name["name"]["normalized_data_type"] == "string"
    assert by_name["amount"]["normalized_data_type"] == "float"
    assert [f["ordinal_position"] for f in fields] == [1, 2, 3]


def test_infer_parquet_schema_garbage_bytes_returns_none():
    assert infer_parquet_schema(b"not a parquet file") is None
