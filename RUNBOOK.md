# Running the full stack locally

This walks through bringing up every piece — control-plane storage,
ingest API, catalog API, a data-plane agent against real Postgres/S3
sources, and the web UI — as one connected system on your machine. It's
been run start-to-finish exactly as written below (including the two bugs
it caught and fixed — see "What this exercise found" at the bottom).

Every command assumes your shell is at the repo root
(`data-discovery-metadata-engine/`) unless a `cd` is shown.

## 0. Prerequisites

- Docker Desktop running.
- Python 3.9+, Node 18+.
- **Check for port conflicts before starting.** This stack uses `5433`
  (control-plane Postgres), `7474`/`7687` (Neo4j), `9200` (OpenSearch),
  `8123`/`9000` (ClickHouse), `5432` (data-plane source Postgres), `9500`/
  `9501` (MinIO), `8090` (ingest API), `8091` (catalog API), `5173` (web).
  If you already run a local ClickHouse, Postgres, etc. natively (not in
  Docker), one of these will collide — `8123` in particular is
  ClickHouse's default HTTP port and is a common one to already have
  running. `lsof -i :<port>` tells you what's there before you start.

## 1. Control-plane storage (Postgres, Neo4j, OpenSearch, ClickHouse)

```bash
docker compose -f infra/docker-compose.yml up -d
```

Wait for all four to report healthy: `docker ps` (a Docker healthcheck
takes ~20-60s per service on first boot). ClickHouse's healthcheck can
show `unhealthy` even when the server itself is fine — confirm with
`curl -s http://localhost:8123/ping` (expect `Ok.`) rather than trusting
the Docker status alone.

## 2. Python environment for `control-plane/`

```bash
python3 -m venv control-plane/.venv
control-plane/.venv/bin/pip install --upgrade pip
control-plane/.venv/bin/pip install -r control-plane/requirements.txt
```

## 3. Bootstrap the control plane

Creates the Postgres schema, a fixed local tenant + catalog-read API key,
the OpenSearch index, and the ClickHouse tables. Safe to re-run.

```bash
POSTGRES_PORT=5433 PYTHONPATH="$(pwd):$(pwd)/control-plane" \
  control-plane/.venv/bin/python control-plane/scripts/bootstrap_local.py
```

Prints the tenant id and API key it created
(`control-plane/scripts/local_constants.py` — `local-dev-key` by default).
This same key is reused for both the data-plane push path and the
catalog-UI read path in this local setup (see that file's docstring for
why that's a local-only simplification, not how production auth works).

## 4. Start the ingest API (real stores, not fakes)

```bash
POSTGRES_PORT=5433 PYTHONPATH="$(pwd):$(pwd)/control-plane" \
  control-plane/.venv/bin/python control-plane/scripts/run_ingest_local.py
```

Runs on `http://localhost:8090`. Leave this running in its own terminal
(or background it — see "Running everything in the background" below).

**If you edit anything under `shared/schema/` or `control-plane/storage/`
while this is running, restart it** — Python has already imported and
cached the old schema/module state; a running process won't pick up file
changes.

## 5. Start the catalog API (real stores)

In a new terminal:

```bash
POSTGRES_PORT=5433 PYTHONPATH="$(pwd)" \
  control-plane/.venv/bin/uvicorn api.catalog.app:app --app-dir control-plane --port 8091
```

Runs on `http://localhost:8091`. Verify: `curl http://localhost:8091/healthz` → `{"status":"ok"}`.

## 6. Data-plane source containers (Postgres + MinIO, seeded with demo data)

```bash
docker compose -f data-plane/deploy/docker-compose.yml up -d postgres minio minio-init
```

This brings up only the *source* systems being cataloged (a seeded demo
Postgres database and a seeded MinIO/S3 bucket) — not the dockerized agent
or the `mock-ingest` service also defined in that compose file, since
we're pointing the agent at the real ingest API from step 4 instead.

## 7. Python environment for `data-plane/`

```bash
cd data-plane
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -e ".[dev]"
cd ..
```

## 8. Run the agent (one scrape+push cycle)

```bash
cd data-plane
DP_CONTROL_PLANE_URL=http://127.0.0.1:8090 \
DP_API_KEY=local-dev-key \
DP_DATA_PLANE_ID=dp-local-1 \
DP_SOURCES_CONFIG_FILE=deploy/sources.local-host.yaml \
.venv/bin/python -m agent.main --once
cd ..
```

`sources.local-host.yaml` (as opposed to `sources.local.yaml`) points at
`localhost` + the published Docker host ports, since the agent is running
as a host process here rather than inside the compose network. Expect a
log line like:

```
cycle complete: CycleReport(sources_run=2, sources_failed=0, entities_discovered=18, ..., entities_pushed_accepted=18, entities_pushed_rejected=0, ...)
```

`entities_pushed_rejected` should be `0`. If it's not, the ingest API's
response body (logged as a warning) names the exact validation error —
see "What this exercise found" below for the two real bugs this caught.

## 9. Verify data landed, via the real catalog API

```bash
curl -s -H "Authorization: Bearer local-dev-key" "http://127.0.0.1:8091/v1/catalog/search?q=orders"
```

Should return the `orders` table scraped from the demo Postgres database,
with a real `last_scraped_at` timestamp — not seeded/fixture data.

## 10. Run the web UI against the real backend

```bash
cd control-plane/web
npm install
VITE_LOCAL_PROXY_TARGET=http://127.0.0.1:8091 VITE_LOCAL_API_KEY=local-dev-key VITE_USE_MOCKS=false npm run dev -- --port 5173
```

Open **http://localhost:5173**. Note: use the hostname `localhost`, not
`127.0.0.1` — Vite's dev server binds IPv6 `localhost` by default and
`127.0.0.1` (IPv4) won't connect on some setups.

The UI never implements its own login/API-key flow (out of MVP scope —
see `.claude/team/design.md`), so `VITE_LOCAL_PROXY_TARGET`/
`VITE_LOCAL_API_KEY` (wired in `vite.config.ts`) make the dev server proxy
`/v1/*` requests to the real catalog API and inject the
`Authorization: Bearer local-dev-key` header on the way through — a
local-dev-only mechanism, not part of the shipped app. Omit both env vars
(just `npm run dev`) to fall back to the normal mocked-fetch dev mode with
no backend required at all.

## Running everything in the background

Each of steps 4/5/8's-agent/10 can be backgrounded, e.g.:

```bash
POSTGRES_PORT=5433 PYTHONPATH="$(pwd):$(pwd)/control-plane" \
  control-plane/.venv/bin/python control-plane/scripts/run_ingest_local.py > /tmp/ingest.log 2>&1 &
```

## Tearing down

```bash
docker compose -f infra/docker-compose.yml down -v
docker compose -f data-plane/deploy/docker-compose.yml down -v
pkill -f run_ingest_local.py
pkill -f "uvicorn api.catalog.app"
# stop the `npm run dev` process (Ctrl-C in its terminal, or pkill -f vite)
```

`down -v` wipes the Postgres/Neo4j/OpenSearch/ClickHouse/MinIO data
volumes too — drop `-v` to keep data across restarts (you'll only need to
re-run step 3's bootstrap once, ever, on a persisted volume).

## What this exercise found

Running the full stack for real — not just each engineer's own test suite
in isolation — surfaced two genuine integration bugs that unit tests
against each side's own fakes/mocks couldn't have caught, since both sides
were internally self-consistent and only disagreed with each other:

1. **FE1's fan-out worker vs. FE2's real storage clients** disagreed on
   the *type* passed to the four seam methods (`upsert_entity`,
   `index_entity`, `record_event`) despite agreeing on the method
   *names*. Fixed by reconciling FE1's `interfaces.py` to FE2's real
   `storage/types.py` shapes — see `.claude/team/status.md`'s
   2026-09-03 "Engineering phase complete + merged" entry.
2. **The data-plane connector's `Column` payload vs.
   `shared/schema/column.schema.json`** disagreed on a field name:
   the connector correctly sends `table_urn` (a connector can't know the
   catalog's internal id at push time — only FE1's own schema
   description already said as much: *"FK to the owning Table's id or
   urn"*), but the schema required the literal key `table_id`, and
   `foreign_key_ref.column` vs. the schema's `column_name`. Fixed by
   renaming the schema fields to match the connector (and FE2's own
   `ColumnEntity.table_urn` Postgres column, which already agreed with
   the connector) — the connector and storage layer were right, the
   schema was the odd one out.

**One gap found and left open** (not fixed in this pass — noted in
`.claude/team/status.md`): `GET /v1/catalog/sources/status` always
returns an empty list. It reads from Postgres's `ConnectorRun` table via
`RelationalStore.record_connector_run()`, but nothing in the current
ingest→fan-out path calls that method — `scrape_run` entities are routed
only to ClickHouse's analytics event log (matching spec.md's "Scrape Run
is not itself catalog content"), which is a different, disconnected
bookkeeping path than the one the Source Connection Status screen
actually reads from. Search and asset-detail views work fully; the
Source Connection Status screen (design.md §4) will show no sources.
