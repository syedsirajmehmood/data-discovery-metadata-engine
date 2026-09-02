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
