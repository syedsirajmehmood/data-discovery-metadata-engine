import pytest

from connectors.postgres.type_mapping import normalize_type


@pytest.mark.parametrize(
    "native,expected",
    [
        ("integer", "integer"),
        ("bigint", "integer"),
        ("character varying(255)", "string"),
        ("character varying", "string"),
        ("text", "string"),
        ("boolean", "boolean"),
        ("numeric(10,2)", "float"),
        ("double precision", "float"),
        ("timestamp without time zone", "timestamp"),
        ("timestamp with time zone", "timestamp"),
        ("date", "date"),
        ("jsonb", "json"),
        ("uuid", "uuid"),
        ("bytea", "binary"),
        ("some_custom_enum_type", "other"),
    ],
)
def test_normalize_type_scalar(native, expected):
    assert normalize_type(native) == expected


def test_normalize_type_array_suffix():
    assert normalize_type("integer[]") == "array<integer>"
    assert normalize_type("text[]") == "array<string>"


def test_normalize_type_empty_or_none():
    assert normalize_type("") == "unknown"
