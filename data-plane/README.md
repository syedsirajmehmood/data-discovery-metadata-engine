# Data Plane

The connector agent that runs inside a customer's environment: source
connectors (`connectors/`) discover and extract metadata, and the agent
runner (`agent/`) batches and pushes it outbound to the control plane's
ingest API over HTTPS. Nothing here ever listens for inbound connections —
see `.claude/team/architecture.md` §5.

Owned by the Data Engineer role, per `architecture.md` §8:
`connectors/core/`, `connectors/postgres/`, `connectors/s3/`, `agent/`.

## Layout

```
data-plane/
├── connectors/
│   ├── core/        BaseConnector ABC, NormalizedEntity/LineageEdge/Cursor types
│   ├── postgres/     PostgresConnector (information_schema/pg_catalog walk)
│   └── s3/            S3Connector (boto3, CSV/Parquet schema inference)
├── agent/            scheduler, batcher, push client, dead-letter queue, config
├── deploy/           Dockerfile, docker-compose for local dev (Postgres + MinIO)
├── tests/
│   ├── unit/          no external services needed
│   └── integration/   needs docker-compose (real Postgres + real MinIO)
└── pyproject.toml
```

## A note on `shared/schema/`

Per `architecture.md` §1, `shared/schema/` (owned by FE1) is meant to be
the canonical, versioned source of truth for the push-contract envelope and
per-entity-type field lists. At the time this was built, `shared/schema/`
had not yet landed in this worktree, so `connectors/core/types.py` and
`agent/validation.py` were built directly against:
- `architecture.md` §2 (the envelope shape: `batch_id`, `data_plane_id`,
  `connector_type`, `schema_version`, `sent_at`, `entities[]` with
  `urn`/`entity_type`/`operation`/`content_hash`/`extracted_at`/`payload`), and
- `spec.md`'s "Metadata schema requirements" section (the per-entity-type
  field lists for Table/Column/Dataset/Job/Lineage Edge).

Every deliberate deviation or assumption made while doing this is called
out in a docstring at the point it's made — start with
`connectors/core/types.py`'s module docstring (which fields are
intentionally *not* sent in the payload, and why) and
`connectors/s3/connector.py`'s module docstring (two additive Dataset
fields beyond spec.md's minimum list). Once `shared/schema/*.schema.json`
lands, `agent/validation.py` is the one place to swap the current
hand-rolled field-presence checks for real JSON Schema validation without
touching any connector.

## Setup

Requires Python 3.9+.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

`pyarrow` (Parquet schema inference) and `moto` are dev/test-only extras —
at runtime, if `pyarrow` isn't installed, `S3Connector` just reports
`schema_inferred=false` for Parquet objects instead of failing (see
`connectors/s3/schema_inference.py::infer_parquet_schema`).

## Running tests

Unit tests (no external services, fast, ~120 tests):

```bash
pytest tests/unit -q
```

Integration tests (real Postgres + real MinIO via docker-compose; skipped
automatically with a clear message if those services aren't reachable):

```bash
docker compose -f deploy/docker-compose.yml up -d postgres minio minio-init mock-ingest
pytest tests -q -m integration      # just the integration suite
pytest tests -q                     # everything
docker compose -f deploy/docker-compose.yml down -v
```

The integration suite covers: real `information_schema`/`pg_catalog`
introspection against seeded Postgres tables/views/FKs/comments, real
`boto3` listing + CSV schema/partition inference against seeded MinIO
objects, schema-drift-as-delete against a live mutation of the Postgres
schema, and one true end-to-end test that runs the real `AgentRunner`
against real Postgres+MinIO and asserts on the exact HTTP request an
in-process mock ingest server received.

## Running the whole stack locally (agent + Postgres + MinIO + mock ingest)

```bash
cd deploy
docker compose up -d --build
docker compose logs -f agent
```

This starts:
- `postgres` — seeded via `deploy/postgres-init/01_seed.sql` (an
  `analytics` schema with `users`, `orders`, a `recent_orders` view, a
  foreign key, and table/column comments).
- `minio` — seeded via the one-shot `minio-init` service (`mc cp` of
  `deploy/minio-init/sample-data/`: a Hive-partitioned `events/` CSV
  dataset and a flat `exports/users.csv`).
- `mock-ingest` — **a throwaway local-dev stand-in for the real
  control-plane ingest API** (`deploy/mock_ingest_server.py`,
  stdlib-only). It is NOT `control-plane/api/ingest/` (that's FE1's, out
  of this engineer's scope and not touched here) — it implements just
  enough of `architecture.md` §2 (Bearer auth, batch_id idempotency
  replay, per-entity accept/reject) to prove the agent's push client works
  end-to-end without the full control plane running. Every accepted batch
  is written to the `mock-ingest-received` volume as
  `<batch_id>-<random>.json` so you can inspect exactly what was pushed.
- `agent` — built from `deploy/Dockerfile`, configured via
  `deploy/sources.local.yaml` (one Postgres source, one S3 source) and a
  60-second scrape interval for a fast local demo loop (production default
  is 6 hours — see `agent/config.py`).

Inspect what the agent pushed:

```bash
docker compose exec mock-ingest sh -c 'ls /data/received && cat /data/received/*.json | head -80'
```

Watch the demo of "zero-touch cataloging" (spec.md story 6 / AC-6): add a
table while the stack is running and watch it show up in the next pushed
batch without touching the agent.

```bash
docker compose exec postgres psql -U demo -d demo -c \
  "CREATE TABLE analytics.new_table (id INT PRIMARY KEY, note TEXT);"
docker compose logs -f agent   # within ~60s, a new batch includes new_table
```

Drop it again and confirm it tombstones (schema drift -> delete, not an
error):

```bash
docker compose exec postgres psql -U demo -d demo -c \
  "DROP TABLE analytics.new_table;"
docker compose logs -f agent   # next cycle emits operation="delete" for it
```

Tear down:

```bash
docker compose down -v
```

### Running against docker-compose services from the host (not in a container)

`deploy/sources.local.yaml` uses the compose-network hostnames
(`postgres`, `minio:9000`), which only resolve inside the compose network.
To run the agent (or `python -m agent.main --once`) directly on your host
against `docker compose up postgres minio minio-init`, use `localhost` and
the published host ports instead (Postgres `5432`, MinIO `9500`, per
`deploy/docker-compose.yml`'s port mappings) in your own copy of the
sources file, and point `DP_CONTROL_PLANE_URL` at wherever you're running
`mock_ingest_server.py` (or a real control plane).

## Configuration (agent)

Everything is env-driven — the control-plane URL and API key are **never**
hardcoded, per `decisions.md`'s airgapped-later requirement:

| Env var | Required | Default | Meaning |
|---|---|---|---|
| `DP_CONTROL_PLANE_URL` | yes | — | e.g. `https://ingest.example.com` |
| `DP_API_KEY` | yes | — | Bearer token, per data-plane installation |
| `DP_DATA_PLANE_ID` | yes | — | this installation's id |
| `DP_SOURCES_CONFIG_FILE` | no | — | path to a YAML/JSON file listing source connections (see `deploy/sources.local.yaml`) |
| `DP_SCRAPE_INTERVAL_SECONDS` | no | `21600` (6h, spec.md NFR-1) | scheduler interval |
| `DP_MAX_BATCH_ENTITIES` | no | `500` | batch size flush trigger (architecture.md §2) |
| `DP_MAX_BATCH_INTERVAL_SECONDS` | no | `60` | batch time flush trigger |
| `DP_RETRY_MAX_ATTEMPTS` | no | `6` | push retry attempts (architecture.md §2: base 5s, cap ~5min) |
| `DP_CURSOR_DIR` | no | `./data/cursors` | local incremental-scrape state |
| `DP_DEAD_LETTER_DIR` | no | `./data/dead_letter` | local dead-letter queue |

Run one cycle and exit (for a k8s CronJob deployment instead of the
in-process scheduler, per architecture.md §5):

```bash
python -m agent.main --once
```

## Adding a new connector

Per architecture.md §3, this requires zero changes to `agent/` itself:

1. New directory under `connectors/`, a class implementing
   `connectors.core.base.BaseConnector` (`connect`, `health_check`,
   `discover`, `extract_metadata`, optionally `extract_lineage`,
   `get_cursor`/`set_cursor`).
2. Register it in `agent/registry.py`'s `CONNECTOR_REGISTRY`.
3. Add a `sources:` entry with the new `connector_type` to your sources
   config file.

## Design notes / known limitations (MVP scope)

- **Postgres**: `extract_lineage()` is not overridden — `BaseConnector`'s
  default (empty) applies, per architecture.md §3 ("Postgres has no native
  lineage source for MVP"). Row/size stats come from `pg_class.reltuples`
  / `pg_total_relation_size` (estimates, not exact counts, per spec.md).
  Owner is populated from the table's Postgres role owner
  (`pg_get_userbyid`) as a real source-asserted signal for spec.md's
  `owner`/`owner_source` fields.
- **S3**: schema inference is best-effort and samples only the first
  object under a prefix (`sniff_bytes`, default 64KB) — good enough to
  read a CSV header or a Parquet footer, not a full data scan. Parquet
  inference is skipped gracefully (not an error) if `pyarrow` isn't
  installed. `partition_keys` and `source_last_modified_at` are additive
  fields beyond spec.md's minimum Dataset field list — see
  `connectors/s3/connector.py`'s module docstring.
- **Cursor/dead-letter state is local disk, not a database** — intentional
  for MVP: it's data-plane-local, never sent to the control plane, and
  keeping it dependency-free (no local DB) matters for the airgapped/
  minimal-footprint story per decisions.md.
- **`Batcher` is one-connector-type-per-instance** — the runner creates a
  fresh `Batcher` per source-connection cycle, so this is never an issue
  in practice; it's enforced defensively in `agent/batcher.py`.
