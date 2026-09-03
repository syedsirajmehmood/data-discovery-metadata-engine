# Decisions Log

Append-only. Each entry: date, decision, why, who made it. Do not delete or
rewrite past entries — if a decision changes, add a new entry that supersedes it
and note what it supersedes.

---

## 2026-09-02 — Repo & visibility
Repo: `syedsirajmehmood/data-discovery-metadata-engine`, private.
**Why:** owner's choice.

## 2026-09-02 — Product framing
Building a metadata/data-discovery catalog in the spirit of Amundsen (Lyft's
open-source data catalog): search and discovery over tables, columns,
dashboards, and pipelines, with lineage and ownership.
**Why:** stated by owner as the reference point for what this product should feel like.

## 2026-09-02 — Deployment model: hybrid, control-plane / data-plane split
This is a **hybrid SaaS** product, not a single deployable app. Two units:
- **Data plane** — deployed inside the customer's own environment (their VPC /
  Kubernetes cluster). Runs the source connectors (Postgres, Databricks,
  Snowflake, S3, Airflow, dbt, more later) and extracts *metadata only*
  (schemas, columns, table/dashboard/job definitions, lineage edges, basic
  stats) — never raw customer data or credentials.
- **Control plane** — hosted by the owner (multi-tenant SaaS). Receives
  metadata pushed from each customer's data plane, serves the catalog/search
  UI, handles tenant and license management.
- **Connection direction: outbound-only from data plane to control plane.**
  The data plane initiates the connection and pushes metadata out; the
  control plane never needs inbound network access into the customer's
  environment. This avoids asking customers to open firewall holes and is the
  standard pattern for this kind of hybrid agent (cf. CI self-hosted runners,
  monitoring agents).
- **Airgapped mode is a future deployment target, not built now.** The
  control plane must be self-hostable later without changing the
  control-plane/data-plane split or the connector code — airgapped just means
  the customer runs both halves themselves with no calls out to the owner's
  SaaS. Do not build multi-tenant-only shortcuts that would block this later
  (e.g., do not hardcode the owner's SaaS URL into the data plane — make it
  configurable).
**Why:** stated by owner. Retrofitting this split after building a monolith
would be expensive, so it's fixed at the architecture level from the start.
**How to apply:** every engineering task must specify which plane it belongs
to. The tech lead's architecture.md must define the data-plane/control-plane
contract (the metadata push API) before engineering starts.

## 2026-09-02 — Diagrams required
Architecture documentation must include Mermaid diagrams (system/deployment,
data flow, push sequence, connector component diagram), embedded directly in
`.claude/team/architecture.md` so they render on GitHub without extra
tooling.
**Why:** owner requested. **How to apply:** Tech Lead produces these as part
of architecture.md, kept up to date as the design evolves — not a one-time
artifact.

## 2026-09-02 — Storage: right engine per workload, evaluate KG tech + ClickHouse
Do not default to "one relational database for everything." Specifically
evaluate: (1) a knowledge-graph / property-graph representation for
lineage and entity relationships, since that data is graph-shaped
(multi-hop traversal, impact analysis are core catalog features); (2)
ClickHouse for high-volume append-mostly analytics data (scrape history,
usage patterns, audit/freshness trail) — the owner already has ClickHouse
available locally. Full-text search index is a separate concern from both.
**Why:** owner requested "latest KG tech" and ClickHouse where it fits, and
graph-shaped lineage queries are a poor fit for pure relational joins at
scale. **How to apply:** Tech Lead picks concrete current technologies for
each workload in architecture.md and justifies the split; engineers follow
that split rather than collapsing everything into one datastore.

## 2026-09-02 — MVP scope
First working version targets **two source connectors (Postgres and S3)**
end-to-end through both planes, plus a basic catalog + search UI on the
control plane, rather than attempting all sources (Databricks, Snowflake,
Airflow, dbt) at once.
**Why:** owner chose "MVP first" over "full scope upfront" — prove the
hybrid architecture and the push contract work end-to-end before scaling out
connector breadth. Multi-tenancy, billing, and airgapped packaging are
explicitly out of scope for the MVP; single-tenant control plane is fine for
now as long as the API shape doesn't preclude multi-tenancy later.

## 2026-09-02 — Architecture v1 (Tech Lead)
Full detail in `architecture.md`. Key technical choices, logged here per
this doc's own instruction to record decisions rather than only edit
architecture.md in place:

- **Repo layout**: single monorepo, `data-plane/` and `control-plane/`
  fully disjoint trees, dependency direction enforced (both depend on
  `shared/schema/`, never on each other). Chosen over separate repos
  because at current team size a contract change should be one atomic
  commit; `data-plane/` is structured so it could still be `git subtree
  split` into its own repo later without a redesign, once customers need
  to pin agent versions independently.
- **Push transport**: plain HTTPS/JSON batch POST (`POST /v1/ingest/
  batches`), not gRPC/websocket/long-lived stream. Rejected streaming
  because corporate egress proxies commonly throttle/kill long-idle
  connections or block websocket upgrades — a plain POST needs zero
  customer-side network allowlisting beyond "outbound HTTPS is allowed."
  Catalog metadata has no sub-second freshness requirement, so the
  stateless request/response model's simpler idempotency/retry story wins.
  Future control-plane-initiated actions (e.g. "scrape now" from the UI)
  stay outbound-only too — the agent polls a commands endpoint on its own
  schedule rather than the control plane dialing in.
- **Auth**: long-lived revocable API key per `(tenant_id, data_plane_id)`,
  `tenant_id` always resolved server-side from the key, never accepted
  from the request body — closes cross-tenant spoofing even at
  single-tenant MVP scale.
- **Connector interface**: data plane is Python (every near-term source —
  Postgres, S3, and post-MVP dbt/Airflow — has first-class Python
  tooling). `BaseConnector` ABC (`connect`, `health_check`, `discover`,
  `extract_metadata`, `extract_lineage`, cursor get/set) — a new source is
  a new class registered in agent config, zero changes to the agent
  runner. Postgres and S3 connectors are the MVP implementations;
  Databricks/Snowflake/Airflow/dbt are designed to plug into the same
  interface without touching `data-plane/agent/`.
- **Control-plane storage: one engine per workload, not one database for
  everything** — resolves the "evaluate KG tech + ClickHouse" decision
  above with concrete choices:
  - **Postgres** — system of record for entities (tenants, API keys,
    connector registry, entities themselves). Transactional source of
    truth; Neo4j and OpenSearch are derived, rebuildable projections of it.
  - **Neo4j 5.x** — lineage and entity relationships (the knowledge-graph
    piece). Chosen over AWS Neptune specifically because Neptune is
    cloud-vendor-locked and would break airgapped/self-host later; Neo4j
    runs the same image self-hosted or managed. Justified against actual
    query shape: multi-hop impact analysis (`downstream of table X`) is a
    native variable-length Cypher traversal, versus a recursive CTE in SQL
    that degrades badly past 3-4 hops with fan-out.
  - **OpenSearch** — full-text/keyword catalog search. Chosen over
    Elasticsearch specifically for its Apache-2.0 license (no
    license-server dependency, matters for airgapped self-host).
  - **ClickHouse** — scrape history, usage events, audit/freshness trail.
    Already available in the owner's environment. Used only for this
    append-only, high-cardinality-over-time workload — explicitly not used
    for entity storage or lineage, since events aren't graph-shaped and
    would degrade Postgres's OLTP performance under high write volume.
- **Multi-tenancy**: `tenant_id` present on every row/node/document across
  all four stores from day one, always server-resolved from the API key,
  never client-supplied — MVP provisions exactly one tenant row, but going
  to N tenants is a provisioning/query-scoping exercise, not a schema
  rewrite.

**Why recorded here separately from architecture.md:** this file is the
append-only decision history; architecture.md is the living document that
will keep changing as implementation surfaces new constraints — decisions
made now should survive even if the document's wording around them evolves.
**How to apply:** engineers build against architecture.md's current text for
detail, but any future change to the choices above must be logged as a new
dated entry here, not a silent edit.

## 2026-09-03 — Control-plane implementation language (orchestrator)
Architecture v1 fixed the data-plane language (Python) but left the
control-plane's language/framework unspecified. Fixing it now, before
engineering starts, so 5 parallel engineers don't each guess differently:
- **Control-plane backend: Python + FastAPI.** Consistent with the
  data-plane language (one language across the whole system reduces
  context-switching for a small team), and every storage engine chosen in
  architecture.md §4 has a mature Python client: SQLAlchemy/psycopg
  (Postgres), the official `neo4j` driver, `opensearch-py`, and
  `clickhouse-connect`.
- **Control-plane frontend (`control-plane/web/`): TypeScript + React,
  built with Vite.** Standard, current choice for a search/catalog web UI;
  consumes the FastAPI backend as a plain REST/JSON API — no server-side
  coupling between FE2's API and FE3's UI beyond the HTTP contract FE2
  publishes.
**Why:** without a pinned stack, FE1/FE2/FE3/DE/ML would each choose
independently and produce incompatible services. **How to apply:** every
engineering task in this phase targets this stack; a change requires a new
dated entry here, not a silent per-engineer choice.
