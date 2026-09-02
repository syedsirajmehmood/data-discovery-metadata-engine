# Architecture

Status: DRAFT — owned by Tech Lead. Fixed constraints from decisions.md:
control-plane/data-plane split, outbound-only push, connector extensibility,
airgapped-later.

## TODO for Tech Lead
- [ ] Repo layout (monorepo with `data-plane/`, `control-plane/`, shared
      `connectors/` and `schema/` packages, or separate repos)
- [ ] The metadata push contract between data plane and control plane (API
      shape, auth, batching, idempotency/retry)
- [ ] Connector interface (what a new source connector must implement —
      applies to Postgres and S3 now, Databricks/Snowflake/Airflow/dbt later)
- [ ] Metadata storage model on the control plane:
      - Lineage/relationships (table→column, job→dataset, dbt model deps,
        Airflow DAG edges) are graph-shaped by nature — evaluate a
        knowledge-graph representation (property graph) for this rather than
        forcing it into pure relational joins. Pick a concrete storage
        choice (e.g. a graph DB, or Postgres with a graph-query layer) and
        justify it against query patterns the UI needs (impact analysis,
        "what feeds this table," multi-hop traversal).
      - Full-text/keyword search index for the catalog UI.
      - Metadata usage analytics / audit trail (scrape history, access
        patterns, freshness tracking) is high-volume, append-mostly,
        time-series-like data — evaluate ClickHouse for this specifically
        (it's already available in the owner's environment). Do not put
        this workload in the same store as the graph/catalog data — pick
        the right engine per workload rather than one store for everything.
- [ ] What "outbound-only" means concretely (polling vs long-lived
      connection vs webhook-style push — pick one and justify)
- [ ] How multi-tenancy is represented in the control-plane data model even
      though MVP only needs one tenant, so it's not a rewrite later
- [ ] **Diagrams (required, Mermaid, embedded directly in this file):**
      - System/deployment diagram: customer environment (data plane +
        sources) vs vendor-hosted control plane, showing the outbound-only
        boundary
      - Data flow diagram: source → connector → push contract → control-
        plane storage (graph store + search index + ClickHouse) → catalog UI
      - Sequence diagram for one metadata push: connector scrape → batch →
        push API call → validation → storage fan-out
      - Component diagram for the connector interface (how Postgres/S3
        connectors implement a common contract)
