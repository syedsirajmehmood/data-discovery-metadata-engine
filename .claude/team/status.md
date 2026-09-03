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
