# Status Log

Append-only. Each agent appends an entry when it finishes a unit of work.
Format: date, role, what shipped, what other roles need to know (contracts,
file locations, open questions). Do not delete past entries.

---

## 2026-09-02 — Product Owner
Filled in `.claude/team/spec.md`: Personas, Core User Stories (MVP),
Success Criteria (MVP Demo). Did not touch architecture.md or design.md.

**Personas:** Dana (Data Analyst — searches/consumes) and Eli (Data
Engineer — owns sources, also consumes). Both internal/technical users of
the customer's own catalog UI.

**8 core user stories**, scoped strictly to Postgres + S3 connectors +
basic catalog/search per decisions.md: unified cross-source search, schema
view, source/location detail, freshness signal, ownership, zero-touch
cataloging, audit-by-source, cross-source result parity (Postgres and S3
must appear as peers, not two bolted-together catalogs).

**Explicitly cut from MVP** (flagging so BA doesn't write acceptance
criteria for these and Designer doesn't design screens for them): lineage
graphs (dbt/Airflow — needs connectors not yet built), manual
tagging/curation, usage/popularity analytics, multi-tenant UI,
Databricks/Snowflake connectors.

**6 demoable success criteria** — real connectors against real Postgres +
S3, verifiably outbound-only push, unified search across both sources,
complete detail view (schema/location/freshness/owner) without touching
the source system, add-a-table-see-it-in-search with no manual edits, and
the connector framework being generic enough that a third connector is
plausible without re-architecting.

**For Business Analyst:** the 8 user stories above are what your
acceptance criteria and metadata schema requirements should map to.
Ownership story (5) is intentionally loose ("owner field if captured") —
please pin down in your metadata schema whether owner is scraped from the
source (e.g., Postgres table comment/grants) or is a first-class field the
system must support even if MVP has no UI to set it.

**For Designer:** design against the 8 user stories, not lineage/tagging/
analytics — those are cut from MVP. Search results and detail views need
to visually treat Postgres tables and S3 datasets as peers (story 8/
success criterion 3), not as two separate catalogs bolted together.

**For Tech Lead:** success criterion 6 assumes the Postgres/S3 push
contract is genuinely connector-agnostic (shared extraction/push shape) —
if architecture.md's contract is more source-specific than that, flag it
back, since "provable extensibility" is part of how the MVP demo argues
the hybrid architecture works, not just "search returns results."

## 2026-09-02 — Business Analyst
Filled in the "TODO for Business Analyst" section of `.claude/team/spec.md`:
acceptance criteria mapped 1:1 to the PO's 8 user stories, the full metadata
schema (Table, Column, Dataset, Job/DAG, Lineage Edge, Scrape Run entities —
Job/Lineage Edge modeled now even though unused in MVP, so post-MVP
dbt/Airflow connectors are additive, not a schema rewrite), and NFRs
(default 6h scheduled scrape interval, configurable per source; strict
tenant_id scoping required across every store including denormalized/search
indexes, called out explicitly for whoever builds the search index).

Confirmed the PO's MVP cut list (lineage, manual tagging/curation) resolves
what would otherwise have been a schema conflict — lineage entities are
modeled but empty in MVP, not dropped. Ownership (Story 5) is **read-only,
source-asserted only** for MVP per the cut list — no UI edit affordance,
though `owner_source` (source vs. manual) is modeled so a future edit
feature doesn't require a migration.

**For Tech Lead:** the push API must authenticate every push to a specific
`data_plane_id`/`tenant_id` via credentials issued at data-plane
registration — never a client-supplied `tenant_id` field. Flagged as a
push-contract responsibility, not just a schema concern.

**For whoever builds the search index:** `tenant_id` must be carried on
every row/document in any denormalized/read-optimized store, not assumed to
propagate automatically from the source-of-truth store.

## 2026-09-02 — Designer
Filled in `.claude/team/design.md`: information architecture (Tenant → Data
Plane → Source Connection → Table/Dataset, matching BA's schema exactly),
and three core MVP screens — Search Results, Asset Detail (Table/Dataset,
including the required "schema not inferred" state for S3 datasets),
Source Connection Status (list + detail, since in this hybrid model "is my
connector even reporting in" is a routine question any user needs to
answer, not an admin-only concern). Concrete freshness/staleness badge rule
defined once and reused everywhere (stale threshold = 2x configured scrape
interval, distinct `stale` vs `scrape issue` states). No lineage or usage UI
built — correctly out of MVP per the cut list.

Flagged one apparent conflict: an earlier draft of BA's AC-3 (read before
BA's concurrent realignment landed) seemed to require manual owner-editing,
which would contradict the PO's "editing cut from MVP" list. **Resolved by
the orchestrator on review (2026-09-03): checked the final spec.md — AC-3 is
about source/location detail, not owner editing, and BA's final note
confirms ownership is read-only/source-asserted only for MVP.** No conflict
remains; design.md's read-only-first owner-field design (§3, item 1 in its
open-questions list) is already correct as built, no rework needed.

**To Tech Lead** (still open): confirm `error_summary` on a Scrape Run is
sanitized of secrets/connection details before it's pushed from the data
plane — the Source Connection Detail screen surfaces this string directly
to users. Also confirm scrape interval is readable per-source-connection via
the API, not just a global default, since the UI's staleness math needs the
actual configured interval per connection.

## 2026-09-02 — Tech Lead
Filled in `.claude/team/architecture.md` in full: repo layout (monorepo,
`data-plane/`/`control-plane/` disjoint trees sharing only
`shared/schema/`), the metadata push contract (HTTPS/JSON batch POST, API-
key auth scoped server-side to `tenant_id`/`data_plane_id`, batching by
size-or-interval, idempotent via client-generated `batch_id`), the
`BaseConnector` Python interface (Postgres + S3 implemented for MVP,
Databricks/Snowflake/Airflow/dbt designed to plug in without core changes),
the control-plane storage model (Postgres as entity system of record, Neo4j
5.x for lineage/relationships, OpenSearch for full-text search, ClickHouse
for scrape/usage analytics — one engine per workload, justified against
actual query patterns and against airgapped-self-host constraints), what
outbound-only means concretely (scheduled batch POST, not a persistent
stream — corporate egress proxies were the deciding factor), and
multi-tenancy representation across all four stores. All four required
Mermaid diagrams (system/deployment, data flow, push sequence, connector
component) are embedded in architecture.md §7. Key decisions additionally
logged to `.claude/team/decisions.md` (2026-09-02, "Architecture v1")
per the orchestrator's follow-up, since the original agent run was cut off
by a session limit before it reached that step.

**Task breakdown for engineering phase** (architecture.md §8, file/directory
ownership so parallel work doesn't collide):
- **FE1** — `control-plane/api/ingest/`, `shared/schema/`,
  `control-plane/workers/fanout/` (orchestration only). Push contract
  endpoint per §2; owns and publishes `shared/schema/*.schema.json`.
- **FE2** — `control-plane/storage/{relational,graph,search}/` (base client,
  not `relevance/`), `control-plane/storage/analytics/`,
  `control-plane/api/catalog/`. Postgres/Neo4j/OpenSearch/ClickHouse clients
  + the catalog read API FE3 builds the UI against.
- **FE3** — `control-plane/web/`. Catalog UI per Designer's design.md and
  PO's spec.md, consuming only FE2's catalog read API (no direct storage
  access from the UI layer).
- **Data Engineer** — `data-plane/connectors/{core,postgres,s3}/`,
  `data-plane/agent/`. `BaseConnector` interface + agent runner
  (scheduler/batcher/push client/retry/dead-letter queue) +
  `PostgresConnector`/`S3Connector`.
- **ML Engineer** — `control-plane/storage/search/relevance/` only (a
  subdirectory FE2 never edits). Ranking/boost profile on top of FE2's base
  index; explicitly narrow scope, ships additively so baseline search works
  without it.

Collision avoidance is explicit in architecture.md §8: `data-plane/` and
`control-plane/` are fully disjoint; within `control-plane/storage/search/`,
FE2 and ML own separate subdirectories; only FE1 edits `shared/schema/`, DE
and FE2 treat it as a versioned dependency.

**Ready for engineering dispatch** — this task breakdown is what the
orchestrator will hand to the 3 fullstack engineers, data engineer, and ML
engineer next.

## 2026-09-03 — Engineering phase complete + merged (orchestrator)
All 5 engineers (FE1, FE2, FE3, Data Engineer, ML Engineer) built their
scoped slices in parallel, isolated git worktrees per the Tech Lead's task
breakdown, and all 5 branches have been merged into `main`. Before merging,
the orchestrator also had to pin the control-plane implementation language
(Python/FastAPI + TypeScript/React — see decisions.md, "Control-plane
implementation language"), since architecture.md only fixed the data-plane
language and 5 parallel engineers would otherwise have guessed differently.

**What shipped, by engineer:**
- **FE1** — `shared/schema/` (JSON Schema for the envelope + all 6 entity
  types), `control-plane/api/ingest/` (the push contract endpoint: auth,
  validation, idempotency, per-entity accept/reject), `control-plane/
  workers/fanout/` (orchestration routing entities to the 4 storage
  interfaces). 54 tests, verified live over real HTTP including idempotent
  replay.
- **FE2** — `control-plane/storage/{relational,graph,search,analytics}/`
  (Postgres/Neo4j/OpenSearch/ClickHouse clients) and `control-plane/api/
  catalog/` (the read API). 39 tests (unit + real-service integration,
  auto-skipping if Docker isn't running). Documented 5 deviations from
  architecture.md (data_plane_id as string not UUID, Dataset added to the
  graph/search model, lineage edges keyed by urn, catalog-API auth reusing
  api_keys, entities_* tables not FK'd to tenants for write-path
  simplicity) — all justified, not silent.
- **FE3** — `control-plane/web/` (TypeScript + React/Vite): all 3 MVP
  screens per design.md, one shared freshness-badge component reused
  everywhere, 45 tests, clean `tsc -b && vite build`.
- **Data Engineer** — `data-plane/` in full: `BaseConnector` interface,
  `PostgresConnector`, `S3Connector`, the agent runner (scheduler/batcher/
  push client/retry/dead-letter-queue), plus Docker Compose for local dev.
  126 tests; also stood up the full compose stack (real Postgres + MinIO)
  and verified a live push cycle end-to-end.
- **ML Engineer** — `control-plane/storage/search/relevance/` only (scope
  respected exactly): field-weight boosting, ClickHouse-derived popularity
  scoring, documented assumed hook interface for FE2 to reconcile, 32
  tests.

**Rate-limit note:** all 5 agents were dispatched together; 3 of the 4
docs-phase agents earlier in this project had hit a session limit
mid-run — for this phase all 5 completed cleanly with no interruption.

**Merge:** all 5 worktree branches merged into `main` with no code
conflicts (each engineer's directories were genuinely disjoint, confirming
the Tech Lead's task breakdown held up in practice). 3 shared files
(`.gitignore`, `control-plane/requirements.txt`, `control-plane/README.md`)
had add/add conflicts from FE1 and FE2 independently creating them —
resolved by the orchestrator by combining both sides' content rather than
picking one.

**Real integration gap found and fixed (orchestrator, not delegated to a
new agent — the problem was fully diagnosable from the two files
involved):** FE1's `workers/fanout/interfaces.py` and FE2's actual
`storage/*/store.py` implementations matched on method *names*
(`upsert_entity`, `index_entity`, `record_event`) per architecture.md §8,
but not on *types* — FE1 had defined its own parallel `CatalogEntity`/
`UpsertResult`/`AnalyticsEvent`, while FE2's real stores are built against
`storage/types.py`'s `EntityRecord`/`UpsertResult`/`ScrapeEvent`/
`UsageEvent` (different field sets, different return-value semantics, and
FE2's `EntityType` enum has no `scrape_run` member since that entity type
never reaches Relational/Graph/Search at all). Fixed by rewriting FE1's
`interfaces.py` to import and match FE2's real types exactly, introducing
a `ValidatedEntity` type for what crosses from ingest into the fan-out
worker (replacing `CatalogEntity`), and updating `worker.py`/`service.py`/
the fan-out test suite accordingly. Notably, `ValidatedEntity` does NOT
carry `id`/`first_seen_at`/`last_scraped_at` the way `CatalogEntity` did —
FE2's `RelationalStore` manages entity identity internally rather than
receiving a candidate id from ingest, which is a cleaner design than FE1's
original assumption. The `TestFirstSeenAtPreserved` test (which asserted
behavior belonging to FE2's RelationalStore, not FE1's orchestration) was
removed from `workers/fanout/tests/` for the same reason.

**Verification performed post-reconciliation (not just unit tests):**
- `control-plane/workers/fanout/` + `control-plane/api/ingest/` + `shared/
  schema/`: 53 tests passing (down from 54 — one test removed per above).
- `control-plane/storage/` + `control-plane/api/catalog/`: 32 tests passing.
- `control-plane/storage/search/relevance/`: 32 tests passing.
- `data-plane/` unit tests: 114 passing.
- `control-plane/web/`: 45 tests passing, `tsc -b && vite build` clean.
- **Live end-to-end smoke test**: ran the real ingest FastAPI service
  (`python control-plane/api/ingest/app.py`) and POSTed a real batch over
  HTTP — accepted with no rejections, proving the reconciled fan-out path
  (ingest → EntityRecord → in-memory fakes shaped exactly like FE2's real
  stores) works, not just that the unit tests were updated to match.

**Still not done (explicitly out of scope for this pass, tracked here so
it isn't lost):**
1. FE1's `IngestDependencies` has never actually been wired to FE2's *real*
   Postgres/Neo4j/OpenSearch/ClickHouse store classes in a running process
   — only proven against in-memory fakes on both sides. Someone needs to
   instantiate FE2's real stores and pass them into `create_app(ingest_deps=...)`
   and confirm a push actually lands in real Postgres/Neo4j/OpenSearch/
   ClickHouse (docker-compose is already in `infra/`).
2. Data Engineer's agent pushes to a *mock* ingest server
   (`data-plane/deploy/mock_ingest_server.py`), not FE1's real FastAPI
   service — full end-to-end (real Postgres/S3 source → real data-plane
   agent → real ingest API → real storage → real catalog UI) has not been
   run as one connected system yet.
3. FE3's UI was built and tested against mocked fetch responses, not
   FE2's real catalog API — the documented API shape matches, but no one
   has run FE3 against a live FE2 backend yet.
4. FE2's `RelevanceBoostHook` Protocol (in `storage/search/query_builder.py`)
   and ML's assumed hook interface (`storage/search/relevance/INTERFACE.md`)
   have not been reconciled the way the FE1/FE2 seam was — same class of
   problem, not yet checked.
5. No queue between ingest and fan-out (FE1's documented simplification);
   no Postgres-backed idempotency store or API-key registry yet (both are
   in-memory).

Point 3 (FE3↔FE2) and point 4 (ML↔FE2) are the same category of risk that
turned out to be real for FE1↔FE2 — worth checking before calling the MVP
demo-ready, not assuming they're fine because each side documented an
assumption.

## 2026-09-03 — Full local stack run: real end-to-end proof, one more bug found+fixed (orchestrator)
Addressed status items 1-3 above by actually running the whole system
connected — control-plane storage (Postgres/Neo4j/OpenSearch/ClickHouse via
`infra/docker-compose.yml`), the ingest API wired to FE2's real stores (new:
`control-plane/scripts/{bootstrap_local,run_ingest_local,local_constants}.py`),
the catalog API against the same real stores, a data-plane agent running as
a host process against real seeded Postgres + MinIO sources (new:
`data-plane/deploy/sources.local-host.yaml`), and the web UI against the
real catalog API via a local-dev-only auth-injecting proxy (new: proxy
config in `control-plane/web/vite.config.ts`, gated behind
`VITE_LOCAL_PROXY_TARGET`/`VITE_LOCAL_API_KEY` so it's inert unless
explicitly enabled). Full step-by-step in `RUNBOOK.md` (repo root).

**Found and fixed a second real integration bug** (same category as the
FE1/FE2 type mismatch, this time between the Data Engineer's connector and
FE1's schema): the Postgres connector's `Column` payload sends `table_urn`
(a connector cannot know the catalog's internal id at push time) and
`foreign_key_ref.column`, but `shared/schema/column.schema.json` required
the literal key `table_id` and `foreign_key_ref.column_name`. Notably,
FE1's own schema description text already said `table_id`'s value should
be "the owning Table's id **or urn**", and FE2's real `ColumnEntity` Postgres
model already used a column named `table_urn` — so the connector and the
storage layer already agreed with each other; the JSON Schema was the one
inconsistent piece. Fixed by renaming the schema fields to match (not by
changing the connector), verified by re-running the agent cycle before/after:
13 of 18 entities rejected before the fix, 18/18 accepted after, with the
ingest service restarted in between (a running process caches the schema at
import time — file edits alone don't take effect without a restart, which
cost one confusing repeat-failure cycle during this exercise, noted in
RUNBOOK.md).

**Verified with real data, not fixtures**: search results returned a table
scraped from a live local Postgres, with a real `last_scraped_at`
timestamp, via `GET /v1/catalog/search?q=orders` — confirming the entire
push→validate→fan-out→Postgres+OpenSearch→catalog-read chain is real and
connected, and the web UI rendering it via the same live API (through the
dev-proxy auth workaround, since the UI itself has no auth flow — correctly
out of MVP scope per design.md, but means "point it at a real backend"
needed a bridge that didn't exist before this pass).

**One gap found and deliberately left open** (documented in RUNBOOK.md's
"What this exercise found," not silently ignored): `GET /v1/catalog/
sources/status` always returns empty. `scrape_run` entities are routed only
to ClickHouse (`AnalyticsStore.record_event`) per the fan-out worker's
routing table (correct, per spec.md: "Scrape Run... not itself catalog
content"), but the Source Connection Status screen's backing endpoint reads
from Postgres's `ConnectorRun` table via a *different* method
(`RelationalStore.record_connector_run()`) that nothing in the current
pipeline calls. These were built as two disconnected bookkeeping paths.
Fixing this means either the fan-out worker also calls
`record_connector_run()` for `scrape_run` entities, or the catalog API's
sources/status endpoint reads scrape history from ClickHouse instead of
Postgres — a real design choice, not a one-line fix, so left for a
follow-up rather than guessed at here. Search and asset-detail views are
unaffected and fully working.

## 2026-09-03 — Third integration bug: FE3 vs. FE2 on /sources/status shape (orchestrator)
Confirmed the exact risk flagged in the "still not done" list above (item
4/point 3): FE3's `/sources` page called `data.data_planes` on the response
from `GET /v1/catalog/sources/status`, but FE2's real implementation
returns `{ sources: [...] }` with much lower-level per-connection fields
(no `type`, no configured `scrape_interval_seconds`, no consecutive-failure
history, no scrape-run history beyond the latest run, no tombstoned-entity
list, and the endpoint ignores the `source_connection_id` query param FE3
assumed it would honor). The shape mismatch threw an uncaught TypeError in
render (`data.data_planes.reduce` on undefined), which React surfaced as a
blank page with no error boundary.

Fixed with a client-side adapter (`control-plane/web/src/api/catalog.ts`,
`mapSourcesStatusResponse` + `mapSourceConnection` + `deriveStatus` +
`inferSourceType`) rather than changing FE2's already-tested API contract
or FE3's page components. The adapter is shape-detecting: FE2's real
`{sources: [...]}` gets transformed; the mock-fetch dev layer's existing
`{data_planes: [...]}` fixtures (and the 45 tests built against them) pass
through unchanged, so nothing about the mocked dev experience regressed.

**Approximations the adapter makes, documented inline in catalog.ts and
worth someone's attention later, not silent:**
- `type` (postgres/s3) is guessed from the connection id string, since the
  backend doesn't return connector_type on this endpoint.
- `scrape_interval_seconds` is hardcoded to the spec.md NFR-1 default (6h)
  for every connection, since the backend doesn't return a per-connection
  configured interval.
- `consecutive_failure_count` is approximated as 0 or 1 (whether the
  latest run failed), since the backend returns one snapshot, not history.
- `scrape_runs` shows only the single latest run (real data, not
  fabricated) rather than actual history, and `tombstoned_entities` is
  always empty — neither is available from this endpoint at all.

A more complete fix would add `connector_type`, a configured interval, and
run-history/tombstoned-entity endpoints to the backend rather than
approximating them client-side — noted here for whoever picks this up
next, alongside the still-open `sources/status`-always-empty gap above
(which is why this bug wasn't caught by a normal manual click-through
before now: the page never had real data to render against until this
session's local-stack run).

Verified: `tsc -b` clean, all 45 frontend tests still pass, and
`GET /sources` now renders the correct "No sources connected yet" empty
state against the live backend instead of crashing (still empty because of
the separate bookkeeping gap noted above — not this bug).
