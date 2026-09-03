from connectors.s3.schema_inference import (
    aggregate_format,
    detect_format_from_key,
    infer_csv_schema,
    infer_partitioning,
)


def test_detect_format_from_key_common_extensions():
    assert detect_format_from_key("events/2024/part-0.parquet") == "parquet"
    assert detect_format_from_key("exports/users.csv") == "csv"
    assert detect_format_from_key("exports/users.tsv") == "csv"
    assert detect_format_from_key("logs/events.jsonl") == "json"
    assert detect_format_from_key("logs/events.ndjson") == "json"
    assert detect_format_from_key("weird/nofile") == "unknown"


def test_detect_format_from_key_compressed_suffix():
    assert detect_format_from_key("part-0.csv.gz") == "csv"


def test_aggregate_format_single_format():
    keys = ["a/1.parquet", "a/2.parquet"]
    assert aggregate_format(keys) == "parquet"


def test_aggregate_format_mixed():
    keys = ["a/1.parquet", "a/2.csv"]
    assert aggregate_format(keys) == "mixed"


def test_aggregate_format_all_unknown():
    assert aggregate_format(["a/README", "a/.gitkeep"]) == "unknown"


def test_aggregate_format_empty():
    assert aggregate_format([]) == "unknown"


def test_infer_partitioning_hive_style():
    keys = [
        "events/year=2024/month=01/day=01/part-0.parquet",
        "events/year=2024/month=01/day=02/part-0.parquet",
        "events/year=2024/month=02/day=01/part-0.parquet",
    ]
    partitions = infer_partitioning(keys, prefix="events/")
    assert partitions == ["year", "month", "day"]


def test_infer_partitioning_no_partitions():
    keys = ["flat/a.csv", "flat/b.csv"]
    assert infer_partitioning(keys, prefix="flat/") == []


def test_infer_csv_schema_header_and_type_sniff():
    sample = b"id,name,is_active\n1,alice,true\n2,bob,false\n"
    fields = infer_csv_schema(sample)
    assert [f["name"] for f in fields] == ["id", "name", "is_active"]
    assert fields[0]["normalized_data_type"] == "integer"
    assert fields[1]["normalized_data_type"] == "string"
    assert fields[2]["normalized_data_type"] == "boolean"
    assert all(f["ordinal_position"] == i + 1 for i, f in enumerate(fields))


def test_infer_csv_schema_header_only_no_data_rows():
    sample = b"a,b,c\n"
    fields = infer_csv_schema(sample)
    assert [f["name"] for f in fields] == ["a", "b", "c"]
    assert all(f["native_data_type"] == "string" for f in fields)


def test_infer_csv_schema_empty_bytes_returns_none():
    assert infer_csv_schema(b"") is None


def test_infer_csv_schema_undecodable_bytes_returns_none():
    assert infer_csv_schema(b"\xff\xfe\x00\x01") is None
