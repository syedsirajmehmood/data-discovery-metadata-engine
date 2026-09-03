# control-plane/ (FE1's scope)

This README covers what FE1 built: `control-plane/api/ingest/`,
`control-plane/workers/fanout/`, and `shared/schema/`. It does not cover
`control-plane/storage/` (FE2), `control-plane/api/catalog/` (FE2), or
`control-plane/web/` (FE3) - those don't exist yet in this repo.

## What's here

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
├── workers/fanout/        # validated batch -> storage-interface calls (orchestration only)
│   ├── interfaces.py       # the 4-method seam FE2 implements: RelationalStore/GraphStore/
│   │                        # SearchIndex/AnalyticsStore (see docstring for the full contract)
│   ├── fakes.py              # in-memory fakes of those 4 interfaces, FE1-tests-only
│   ├── worker.py               # FanoutWorker - routes each entity_type to the right store(s)
│   └── tests/
└── requirements.txt
```

`shared/schema/` (repo root, not under `control-plane/`) has its own
README - see `shared/schema/README.md`.

## Why there's a repo-root `pytest.ini` and `.venv` lives under `control-plane/`

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

## Setup

Requires Python 3.9+. A virtualenv is already set up at
`control-plane/.venv` in this checkout; to rebuild it from scratch:

```bash
python3 -m venv control-plane/.venv
control-plane/.venv/bin/pip install -r control-plane/requirements.txt
```

## Run the service locally

From the repo root:

```bash
PYTHONPATH="$(pwd)" control-plane/.venv/bin/uvicorn api.ingest.app:app \
  --app-dir control-plane --reload --port 8000
```

- `--app-dir control-plane` adds `control-plane/` to `sys.path` so
  `api.ingest.app:app` resolves.
- `PYTHONPATH="$(pwd)"` adds the repo root so that module can, in turn,
  `import shared.schema`.

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

## Run the tests

```bash
control-plane/.venv/bin/pytest
```

(equivalently `control-plane/.venv/bin/python -m pytest` from the repo
root - `pytest.ini`'s `testpaths` picks up
`control-plane/api/ingest/tests/`, `control-plane/workers/fanout/tests/`,
and `shared/schema/tests/`.)

54 tests as of this writing: envelope/entity JSON-Schema validation
(`shared/schema/tests/`), fan-out routing logic
(`control-plane/workers/fanout/tests/`), and the ingest API end-to-end -
auth, envelope validation, per-entity accept/reject, idempotency,
multi-tenant isolation, tombstoning
(`control-plane/api/ingest/tests/`) - all running against the in-memory
fakes, no external services required.

## Wiring FE2's real storage clients (once they exist)

`api/ingest/app.py`'s `create_app()` accepts `ingest_deps:
IngestDependencies` - pass a real one to swap the in-memory fakes for
FE2's Postgres/Neo4j/OpenSearch/ClickHouse clients, e.g.:

```python
from api.ingest.service import IngestDependencies
from api.ingest.idempotency import InMemoryIdempotencyStore  # or a real Postgres-backed one

deps = IngestDependencies(
    idempotency_store=InMemoryIdempotencyStore(),  # or FE2's Postgres-backed store
    relational_store=real_postgres_store,   # implements workers.fanout.interfaces.RelationalStore
    graph_store=real_neo4j_store,           # implements workers.fanout.interfaces.GraphStore
    search_index=real_opensearch_index,     # implements workers.fanout.interfaces.SearchIndex
    analytics_store=real_clickhouse_store,  # implements workers.fanout.interfaces.AnalyticsStore
)
app = create_app(ingest_deps=deps)
```

No changes needed in `router.py`, `service.py`, or `worker.py` - that's
the point of the Protocol-based seam in
`control-plane/workers/fanout/interfaces.py`.

## Known simplifications (documented, not silent)

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
