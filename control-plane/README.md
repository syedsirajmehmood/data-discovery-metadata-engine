# control-plane — FE2 slice (storage + catalog read API)

This README covers the parts of `control-plane/` owned by FE2 per
`.claude/team/architecture.md` §8:

- `storage/relational/` — Postgres system of record (SQLAlchemy)
- `storage/graph/` — Neo4j 5.x lineage/relationship graph
- `storage/search/` — OpenSearch full-text catalog index (base client +
  mapping only; `storage/search/relevance/` is the ML engineer's, untouched
  here)
- `storage/analytics/` — ClickHouse scrape/usage event stream
- `api/catalog/` — the read API FE3's UI consumes

It does **not** cover `api/ingest/`, `workers/fanout/` (orchestration —
FE1), or `web/` (FE3) — those are built and documented separately.

## The seam: four storage-client methods

Per architecture.md §8, FE1's fan-out worker calls exactly these methods
after validating an ingest batch. This is the contract; everything else in
each store exists to serve `api/catalog/`.

| Store | Method | Module |
|---|---|---|
| `RelationalStore` | `upsert_entity(record: EntityRecord) -> UpsertResult` | `storage/relational/store.py` |
| `GraphStore` | `upsert_entity(record: EntityRecord) -> UpsertResult` | `storage/graph/store.py` |
| `SearchIndex` | `index_entity(record: EntityRecord) -> UpsertResult` | `storage/search/store.py` |
| `AnalyticsStore` | `record_event(event: Union[ScrapeEvent, UsageEvent]) -> None` | `storage/analytics/store.py` |

`EntityRecord`, `UpsertResult`, `ScrapeEvent`, `UsageEvent` are defined in
`storage/types.py` — read that module's docstring first, it's the shape
every store agrees on.

## Local setup

Requires Python 3.9+ (developed and tested against 3.9.6) and Docker.

```bash
cd control-plane
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

# Start Postgres, Neo4j, OpenSearch, ClickHouse
docker compose -f ../infra/docker-compose.yml up -d

# Postgres is mapped to host port 5433 (not 5432) to avoid clashing with any
# other local Postgres — export this before running anything below:
export POSTGRES_PORT=5433

# Apply the baseline schema (either path works, they're kept in sync):
python -m storage.relational.migrate
#   — or —
psql "postgresql://catalog:catalog@localhost:5433/catalog" -f storage/relational/migrations/001_init.sql

# Run the full test suite (integration tests hit the containers above;
# they `pytest.skip` individually if a service isn't reachable, so this is
# also safe to run without Docker — you'll just see those tests skipped)
pytest

# Run just the catalog API locally
uvicorn api.catalog.app:app --reload --port 8001
# -> GET http://localhost:8001/healthz
# -> GET http://localhost:8001/v1/catalog/search?q=orders  (needs a valid
#    API key — see "Auth" below; there's no seed data yet until FE1's
#    ingest path or a manual insert populates the stores)
```

Tear down: `docker compose -f ../infra/docker-compose.yml down -v`.

## Auth (catalog read API)

architecture.md §2 defines API-key auth for the *push* path
(data-plane → ingest). It doesn't separately define a UI-user auth scheme,
so FE2 reused the same `api_keys` table for the *read* path: a row with
`data_plane_id IS NULL` is a tenant-scoped read key rather than a
data-plane push key. `api/catalog/deps.py::get_tenant_id` resolves
`tenant_id` server-side from `Authorization: Bearer <key>` by looking up
`sha256(key)` in `api_keys.key_hash` — **never** from a path/query
parameter, per architecture.md §6. To create a test key:

```python
import hashlib, uuid
from storage.relational.store import RelationalStore
from storage.relational.models import ApiKey, Tenant

store = RelationalStore()
raw_key = "dev-only-key"
with store._session_factory() as session:
    tenant = Tenant(name="dev-tenant")
    session.add(tenant)
    session.flush()
    session.add(ApiKey(tenant_id=tenant.id, key_hash=hashlib.sha256(raw_key.encode()).hexdigest(), label="dev"))
    session.commit()
```

## Catalog read API — exact shape (for FE3)

Base path: `/v1/catalog`. Every route requires `Authorization: Bearer
<api-key>`; `tenant_id` is always resolved from that key server-side.

### `GET /v1/catalog/search`

Query params: `q` (string, default `""`), `entity_type` (repeatable, subset
of `table|column|dataset|dashboard`), `source_type` (repeatable, e.g.
`postgres|s3`), `limit` (1–100, default 20), `offset` (default 0).

```json
{
  "total": 1,
  "results": [
    {
      "urn": "urn:postgres:prod-db-1:analytics:public.orders",
      "entity_type": "table",
      "source_type": "postgres",
      "name": "orders",
      "description": "Customer orders",
      "tags": ["core"],
      "owner": "eli",
      "fully_qualified_name": "postgres://prod-db-1/analytics.public.orders",
      "last_scraped_at": "2026-09-02T10:15:00+00:00",
      "score": 4.32
    }
  ]
}
```

### `GET /v1/catalog/tables/{urn}`

`404` if no such table exists for the caller's tenant (including if the URN
exists for a *different* tenant — never leaks existence).

```json
{
  "table": {
    "urn": "...", "fully_qualified_name": "...", "source_type": "postgres",
    "database_name": "...", "schema_name": "...", "table_name": "...",
    "object_type": "table", "description": "...", "description_source": "source_comment",
    "owner": "...", "owner_source": "source", "tags": ["..."],
    "row_count_estimate": 1234, "size_bytes_estimate": null,
    "source_connection_id": "prod-postgres-1", "data_plane_id": "dp_9f3...",
    "first_seen_at": "...", "last_scraped_at": "...", "is_deleted": false
  },
  "columns": [
    {
      "urn": "...", "table_urn": "...", "name": "id", "ordinal_position": 0,
      "native_data_type": "integer", "normalized_data_type": "integer",
      "is_nullable": false, "is_primary_key": true, "is_foreign_key": false,
      "foreign_key_ref": null, "description": null, "description_source": null,
      "tags": [], "is_deleted": false, "last_scraped_at": "..."
    }
  ]
}
```

### `GET /v1/catalog/tables/{urn}/lineage`

Query params: `direction` (`upstream|downstream|both`, default `both`),
`max_hops` (1–10, default 5). `404` if the anchor table isn't in the
tenant's catalog.

```json
{
  "urn": "urn:postgres:prod-db-1:mart:public.orders_mart",
  "upstream": [{"urn": "urn:postgres:prod-db-1:staging:public.stg_orders", "entity_type": "table", "hops": 1}],
  "downstream": []
}
```

### `GET /v1/catalog/sources/status`

No query params (tenant-scoped only).

```json
{
  "sources": [
    {
      "data_plane_id": "dp_9f3...",
      "data_plane_name": "prod-dp-1",
      "last_seen_at": "2026-09-02T10:00:00+00:00",
      "source_connections": [
        {
          "source_connection_id": "prod-postgres-1",
          "last_run_status": "success",
          "last_run_started_at": "...", "last_run_completed_at": "...",
          "entities_seen_count": 120, "entities_created_count": 4,
          "entities_tombstoned_count": 0, "error_summary": null
        }
      ]
    }
  ]
}
```

Full Pydantic response models: `api/catalog/schemas.py`.

## Deviations from / additions to architecture.md (and why)

1. **`data_plane_id` is a string, not a UUID column.** architecture.md §2's
   push envelope example is `"data_plane_id": "dp_9f3..."` — an opaque
   identifier, not guaranteed canonical UUID text. Every `entities_*` row,
   `connector_runs.data_plane_id`, and `data_plane_registrations.id` are
   `VARCHAR(64)` accordingly (caught by an integration test failure against
   real Postgres — worth flagging since it's an easy trap to fall into if
   FE1/DE assume UUID formatting on this field).
2. **Graph model gains a `(:Dataset)` label** beyond architecture.md §4's
   literal `Table/Column/Job/Dashboard` list, and **OpenSearch indexes
   `dataset` alongside `table/column/dashboard`** beyond §4's literal
   sentence. Both are needed for spec.md AC-1/AC-8 (S3 datasets must be
   first-class search/lineage citizens, not second-class to Postgres
   tables) — documented in `storage/graph/store.py` and
   `storage/search/mapping.py` docstrings.
3. **Lineage Edge's `upstream_entity_id`/`downstream_entity_id`
   (spec.md) are populated with the entity's URN**, not an internal
   Postgres UUID — the only identity stable and known before control-plane
   ingest assigns internal IDs. See `storage/graph/store.py`'s module
   docstring.
4. **Catalog-API auth reuses the `api_keys` table** (a UI/service key with
   `data_plane_id IS NULL`) rather than a separate user-auth system, since
   architecture.md only specifies data-plane→ingest auth. See "Auth" above.
5. **`entities_*` tables don't FK `tenant_id` to `tenants.id`** (unlike
   `api_keys`/`data_plane_registrations`, which do) — kept loose
   deliberately so entity ingestion never blocks on tenant-row provisioning
   order; tenant scoping is still enforced at every query path (§6), just
   not as a hard FK on the hot write path.

## Testing

39 tests total: unit tests for the query builder and catalog router (no
external services), integration tests for all four stores against the real
services in `../infra/docker-compose.yml` (auto-skip if unreachable). Run
`pytest -v` to see the full list. Every store's integration tests include
at least one explicit tenant-isolation assertion (query as tenant B, assert
tenant A's data is invisible) since that's the one property architecture.md
§6 treats as non-negotiable.
