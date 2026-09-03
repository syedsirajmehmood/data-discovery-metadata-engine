# shared/schema/

Canonical JSON Schema (2020-12) files for the metadata push contract, per
`architecture.md` §1/§2 and `spec.md`'s metadata schema section. This is
the **only** package `data-plane/` and `control-plane/` are both allowed to
depend on — see `architecture.md` §1.

## Files

| File | Describes |
|---|---|
| `envelope.schema.json` | The `POST /v1/ingest/batches` request envelope (batch_id, data_plane_id, connector_type, schema_version, sent_at, entities[]). |
| `ingest_response.schema.json` | The per-entity accept/reject response body. |
| `common.schema.json` | Fields shared by Table/Column/Dataset/Job/LineageEdge. `$ref`'d by each entity schema below. |
| `table.schema.json` | Table (Postgres table/view). |
| `column.schema.json` | Column (belongs to a Table). Also exposes `#/$defs/column_specific_fields`, reused by `dataset.schema.json`'s optional `fields` (inferred S3 schema). |
| `dataset.schema.json` | Dataset (S3 bucket+prefix). |
| `job.schema.json` | Job / DAG. No MVP connector populates this; modeled now for extensibility (dbt/Airflow, post-MVP). |
| `lineage_edge.schema.json` | Lineage Edge. |
| `scrape_run.schema.json` | Scrape Run. Not a "common fields" entity — no `id`/`first_seen_at`/`last_scraped_at`/`is_deleted`; see its own field list. |

Every file above declares `"$id": "https://schemas.data-discovery.internal/1.0/<name>.schema.json"`
(a namespace URI, not a real network location — never fetched over the
network; `get_validator()` below resolves these back to the local files on
disk). Cross-file `$ref`s (e.g. `table.schema.json` → `common.schema.json`)
resolve through that shared `$id` namespace.

## Versioning

`schema_version` in the envelope is currently **"1.0"** (`shared.schema.CURRENT_SCHEMA_VERSION`).
A backwards-incompatible change to the envelope or any entity schema bumps
this version and must be logged as a new dated entry in
`.claude/team/decisions.md` first — per `architecture.md`'s header, this
directory is treated as frozen/contract, not silently edited. Additive
changes (new optional field, new `entity_type`) don't require a version
bump — that's the extensibility architecture.md §2 calls out ("new types
don't require an envelope change, only a new schema file").

## Ingest-payload vs. stored-entity shape (important)

Each entity schema (`table.schema.json` etc.) describes the **canonical
stored record** — the full field list from `spec.md`, including the common
fields (`id`, `tenant_id`, `data_plane_id`, `source_connection_id`,
`first_seen_at`, `last_scraped_at`, `is_deleted`).

The **inbound push payload** (`envelope.entities[].payload`) is *narrower*.
Per `architecture.md` §2's explicit security rule ("`tenant_id` is never
accepted from the request body"), applied consistently to every
catalog-side field:

- `id`, `tenant_id`, `first_seen_at`, `last_scraped_at`, `is_deleted` —
  **server-assigned**. Never sent by a connector; the ingest API rejects
  (does not silently strip) any payload that includes them.
- `data_plane_id` — supplied **once per batch**, at the envelope's top
  level (`architecture.md`'s envelope example), not repeated per entity.
  Also rejected if present in an entity's `payload`.
- `source_connection_id` — the one common field the connector *does* send,
  per-entity, inside `payload` (the envelope doesn't carry it at the top
  level, and only the connector knows which named source connection
  produced a given record).

These constants live in this package (`SERVER_ASSIGNED_FIELDS`,
`ENVELOPE_LEVEL_FIELDS`, `FORBIDDEN_PAYLOAD_FIELDS`) so `control-plane/api/ingest`
(and, if useful, the data-plane agent's own pre-push validation) share one
definition instead of two independently-maintained lists.

Because JSON Schema's `required` only says what *must* be present (not what
must be *absent*), the schema files themselves mark these fields optional;
the "must not be present in a push payload" rule is enforced in code
(`control-plane/api/ingest/validation.py`), not by the schema alone.

## Usage

```python
from shared.schema import get_validator, get_entity_schema, FORBIDDEN_PAYLOAD_FIELDS

validator = get_validator("table")          # or get_validator("table.schema.json")
errors = list(validator.iter_errors(payload_dict))
```

`get_validator()` returns a `jsonschema.Draft202012Validator` with `$ref`s
across these files already resolved — callers never deal with `referencing.Registry`
directly.

Requires `jsonschema` + `referencing` (declared in `control-plane/requirements.txt`);
importing plain schema metadata (`ENTITY_SCHEMA_FILES`, `load_schema`, etc.)
has no third-party dependency, so a lighter-weight consumer (e.g. a
data-plane connector that only wants the file paths) doesn't need them
installed.

Format assertions (`format: uuid`, `format: date-time`) are declared in the
schemas for documentation but are **not** strictly enforced by
`get_validator()` by default (no `FormatChecker` is attached) — structural/
type/enum/required validation is what's load-bearing here. If stricter
format enforcement is wanted later, pass `format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER`
when constructing a validator directly.
