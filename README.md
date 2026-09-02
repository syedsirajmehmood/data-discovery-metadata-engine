# data-discovery-metadata-engine

A data discovery and metadata catalog in the spirit of [Amundsen](https://www.amundsen.io/)
(Lyft's open-source data catalog), delivered as a **hybrid SaaS**.

## Deployment model

- **Data plane** — deployed inside a customer's own environment (their VPC /
  Kubernetes cluster). Runs source connectors (Postgres, Databricks,
  Snowflake, S3, Airflow, dbt, and more via an extensible connector
  interface) and extracts *metadata only* — schemas, columns, job/DAG
  definitions, lineage edges, basic stats. Raw customer data and credentials
  never leave the customer's environment.
- **Control plane** — hosted by the vendor (multi-tenant SaaS). Receives
  metadata pushed from each customer's data plane over an **outbound-only**
  connection, serves the catalog/search UI, and handles tenant/license
  management.
- **Airgapped mode** is a future deployment target (not built yet): the
  customer runs both planes themselves with no calls out to the vendor's
  SaaS. The architecture is built so this doesn't require a rewrite later.

See [`.claude/team/decisions.md`](.claude/team/decisions.md) for the full
rationale and [`.claude/team/architecture.md`](.claude/team/architecture.md)
for diagrams and the technical design (in progress).

## MVP scope

First working version: Postgres + S3 connectors end-to-end through both
planes, plus a basic catalog + search UI. Databricks, Snowflake, Airflow,
and dbt integrations follow once the architecture is proven.

## How this project is being built

This repo uses a team of specialized Claude Code subagents, defined in
[`.claude/agents/`](.claude/agents/), coordinating through shared living
documents in [`.claude/team/`](.claude/team/) instead of ad hoc chat context:

| Role | File |
|---|---|
| Product Owner | `.claude/agents/product-owner.md` |
| Business Analyst | `.claude/agents/business-analyst.md` |
| Designer | `.claude/agents/designer.md` |
| Tech Lead | `.claude/agents/tech-lead.md` |
| Manager | `.claude/agents/manager.md` |
| Fullstack Engineer (x3, same definition, different scopes) | `.claude/agents/fullstack-engineer.md` |
| Data Engineer | `.claude/agents/data-engineer.md` |
| ML Engineer | `.claude/agents/ml-engineer.md` |

Shared context lives in `.claude/team/`:

- `decisions.md` — append-only log of fixed decisions and why
- `spec.md` — product spec (Product Owner + Business Analyst)
- `architecture.md` — technical design + diagrams (Tech Lead)
- `design.md` — UX/IA (Designer)
- `status.md` — append-only log of what's shipped and what's next

Every agent reads these before starting and writes back to them when done,
so context persists across sessions without relying on chat history.
