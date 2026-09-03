# control-plane/

The vendor-hosted half of the hybrid architecture (see `.claude/team/
architecture.md`). Two independently-built slices live here, documented
separately below: **FE1's** ingest path (`api/ingest/`, `workers/fanout/`,
plus the shared `shared/schema/` at repo root) and **FE2's** storage +
catalog read API (`storage/`, `api/catalog/`). `control-plane/web/` (FE3)
has its own README under that directory.

**Known integration gap (flagged at merge time, not yet fixed):** FE1's
`workers/fanout/interfaces.py` Protocols and FE2's actual
`storage/*/store.py` implementations were built in parallel worktrees and
don't match exactly — different entity type name (`CatalogEntity` vs.
`EntityRecord`) and different return types on `GraphStore.upsert_entity`/
`SearchIndex.index_entity` (FE1 assumed `None`, FE2 returns `UpsertResult`).
This needs a reconciliation pass wiring `FanoutWorker` to FE2's real stores
before the ingest→storage path works end-to-end with anything other than
FE1's in-memory fakes. See status.md for tracking.

---

## FE1's slice: `api/ingest/`, `workers/fanout/`, `shared/schema/`

This section covers what FE1 built: `control-plane/api/ingest/`,
`control-plane/workers/fanout/`, and `shared/schema/`.

### What's here

```
control-plane/
├── api/ingest/           # POST /v1/ingest/batches - the push contract endpoint
│   ├── auth.py            # Bearer API-key auth, resolves tenant_id/data_plane_id server-side
│   ├── models.py           # Pydantic request/response models matching shared/schema
│   ├── validation.py        # envelope + per-entity payload validation against shared/schema
│   ├── idempotency.py        # batch_id idempotency store (Protocol + in-memory impl)
│   ├── service.py             # orchestration: auth -> validate -> idempotency -> fan-out -> respond
│   ├── router.py                # FastAPI route
│   ├── app.py                    # FastAPI app factory + local dev entrypoint
│   └── tests/
└── workers/fanout/        # validated batch -> storage-interface calls (orchestration only)
    ├── interfaces.py       # the 4-method seam FE2 implements: RelationalStore/GraphStore/
    │                        # SearchIndex/AnalyticsStore (see docstring for the full contract —
    │                        # NOTE: see "Known integration gap" above, this doesn't match FE2's
    │                        # actual store signatures yet)
    ├── fakes.py              # in-memory fakes of those 4 interfaces, FE1-tests-only
    ├── worker.py               # FanoutWorker - routes each entity_type to the right store(s)
    └── tests/
```

`shared/schema/` (repo root, not under `control-plane/`) has its own
README - see `shared/schema/README.md`.

### Why there's a repo-root `pytest.ini` and `.venv` lives under `control-plane/`

architecture.md §1 fixes the directory name `control-plane/` (hyphenated).
Python cannot import a hyphenated name as a dotted package
(`import control-plane.api` is a syntax error) - hyphens aren't valid in
Python identifiers. Renaming the directory isn't an option (it's the
frozen contract in architecture.md). The fix used here, consistently:

- Both **`control-plane/`** and the **repo root** get added to
  `sys.path` (not the repo root alone) - `control-plane/` so `api.*` and
  `workers.*` resolve as top-level packages, and the repo root so
  `shared.schema` resolves.
- For **pytest**: `pytest.ini` at the repo root sets
  `pythonpath = . control-plane`, so this "just works" for `pytest` run
  from the repo root - no per-test path hacking.
- For **running the actual service**, the same two directories need to be
  on `sys.path` - see the run command below (`--app-dir control-plane`
  plus `PYTHONPATH` for the repo root).

This applies equally to FE2's `storage`/`api.catalog` packages below.

### Setup

Requires Python 3.9+.

```bash
python3 -m venv control-plane/.venv
control-plane/.venv/bin/pip install -r control-plane/requirements.txt
```

### Run the ingest service locally

From the repo root:

```bash
PYTHONPATH="$(pwd)" control-plane/.venv/bin/uvicorn api.ingest.app:app \
  --app-dir control-plane --reload --port 8000
```

Then open `http://127.0.0.1:8000/docs` for interactive OpenAPI docs, or
push a batch:

```bash
curl -s -X POST http://127.0.0.1:8000/v1/ingest/batches \
  -H "Authorization: Bearer demo-key" -H "Content-Type: application/json" \
  -d '{
    "batch_id": "b7e2b6b0-1111-1111-1111-000000000001",
    "data_plane_id": "dp_demo",
    "connector_type": "postgres",
    "schema_version": "1.0",
    "sent_at": "2026-09-02T10:15:00Z",
    "entities": [{
      "urn": "urn:postgres:prod-db-1:analytics:public.orders",
      "entity_type": "table",
      "operation": "upsert",
      "content_hash": "sha256:deadbeef",
      "extracted_at": "2026-09-02T10:14:50Z",
      "payload": {
        "source_connection_id": "prod-postgres-1",
        "source_type": "postgres",
        "database_name": "analytics",
        "schema_name": "public",
        "table_name": "orders",
        "fully_qualified_name": "postgres://prod-db-1/analytics.public.orders",
        "object_type": "table"
      }
    }]
  }'
```

`create_app()` (see `api/ingest/app.py`) wires in-memory fakes for
everything by default (API-key registry, idempotency store, and all 4
storage interfaces) - **no real Postgres/Neo4j/OpenSearch/ClickHouse
needed** to run this. State only lives for the process's lifetime and
isn't shared across workers - fine for local dev/demo, not for production
(see "Wiring FE2's real storage clients" below). There's no API key
pre-registered by default; run `python control-plane/api/ingest/app.py`
directly (rather than through uvicorn's CLI) to get a `demo-key` API key
auto-registered at startup, or register one yourself:

```python
from api.ingest.app import create_app
app = create_app()
app.state.api_key_registry.register(
    "my-key", tenant_id="<uuid>", data_plane_id="dp_1", api_key_id="ak_1"
)
```

### Run FE1's tests

```bash
control-plane/.venv/bin/pytest
```

54 tests as of this writing: envelope/entity JSON-Schema validation
(`shared/schema/tests/`), fan-out routing logic
(`control-plane/workers/fanout/tests/`), and the ingest API end-to-end -
auth, envelope validation, per-entity accept/reject, idempotency,
multi-tenant isolation, tombstoning
(`control-plane/api/ingest/tests/`) - all running against the in-memory
fakes, no external services required.

### Wiring FE2's real storage clients (pending the reconciliation pass)

`api/ingest/app.py`'s `create_app()` accepts `ingest_deps:
IngestDependencies` - intended to swap the in-memory fakes for FE2's
Postgres/Neo4j/OpenSearch/ClickHouse clients, e.g.:

```python
from api.ingest.service import IngestDependencies
from api.ingest.idempotency import InMemoryIdempotencyStore  # or a real Postgres-backed one

deps = IngestDependencies(
    idempotency_store=InMemoryIdempotencyStore(),  # or FE2's Postgres-backed store
    relational_store=real_postgres_store,   # must implement workers.fanout.interfaces.RelationalStore
    graph_store=real_neo4j_store,           # must implement workers.fanout.interfaces.GraphStore
    search_index=real_opensearch_index,     # must implement workers.fanout.interfaces.SearchIndex
    analytics_store=real_clickhouse_store,  # must implement workers.fanout.interfaces.AnalyticsStore
)
app = create_app(ingest_deps=deps)
```

**This doesn't work yet as-is** — see "Known integration gap" at the top of
this file. FE2's stores implement a different entity type
(`storage.types.EntityRecord`) than FE1's `interfaces.py` Protocols expect
(`CatalogEntity`), and two of the four methods return `UpsertResult` where
FE1's Protocols declare `None`. Fixing this is the next step, not yet done.

### Known simplifications (documented, not silent)

- **Fan-out is synchronous / in-process**, not queue-backed. The push
  contract's `202 Accepted` (architecture.md §2/§7.3) implies the fan-out
  writes could happen after the response is sent; standing up a real task
  queue was out of scope for this task (no queue library was assigned to
  FE1). Swapping in a queue later is a call-site change in
  `service.process_batch()` (where `FanoutWorker.process_batch()` is
  invoked), not a change to the routing logic itself.
- **Idempotency store is in-memory**, not the Postgres-backed table
  architecture.md §2 specifies. The `IdempotencyStore` Protocol
  (`api/ingest/idempotency.py`) is the seam for swapping in a real one.
- **API key registry is in-memory** (`api/ingest/auth.py`'s
  `InMemoryAPIKeyRegistry`) - production needs this backed by FE2's
  `api_keys` Postgres table (architecture.md §4/§8).

---

## FE2's slice: `storage/`, `api/catalog/`

This section covers the parts of `control-plane/` owned by FE2 per
`.claude/team/architecture.md` §8:

- `storage/relational/` — Postgres system of record (SQLAlchemy)
- `storage/graph/` — Neo4j 5.x lineage/relationship graph
- `storage/search/` — OpenSearch full-text catalog index (base client +
  mapping only; `storage/search/relevance/` is the ML engineer's, untouched
  here)
- `storage/analytics/` — ClickHouse scrape/usage event stream
- `api/catalog/` — the read API FE3's UI consumes

It does **not** cover `api/ingest/`, `workers/fanout/` (orchestration —
FE1, documented above), or `web/` (FE3, own README).

### The seam: four storage-client methods

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
every store agrees on. **See "Known integration gap" at the top of this
file** — these signatures are the ones that need reconciling against FE1's
`workers/fanout/interfaces.py`.

### Local setup

Requires Python 3.9+ (developed and tested against 3.9.6) and Docker.

```bash
cd control-plane
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

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

### Auth (catalog read API)

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

### Catalog read API — exact shape (for FE3)

Base path: `/v1/catalog`. Every route requires `Authorization: Bearer
<api-key>`; `tenant_id` is always resolved from that key server-side.

#### `GET /v1/catalog/search`

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

#### `GET /v1/catalog/tables/{urn}`

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

#### `GET /v1/catalog/tables/{urn}/lineage`

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

#### `GET /v1/catalog/sources/status`

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

### Deviations from / additions to architecture.md (and why)

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

### Testing

39 tests total: unit tests for the query builder and catalog router (no
external services), integration tests for all four stores against the real
services in `../infra/docker-compose.yml` (auto-skip if unreachable). Run
`pytest -v` to see the full list. Every store's integration tests include
at least one explicit tenant-isolation assertion (query as tenant B, assert
tenant A's data is invisible) since that's the one property architecture.md
§6 treats as non-negotiable.
