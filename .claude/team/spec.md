# Product Spec

Status: DRAFT — owned by Product Owner + Business Analyst. Read
decisions.md first; the deployment-model and MVP-scope decisions there are
fixed constraints, not open questions.

## One-liner
A data discovery and metadata catalog (Amundsen-style) delivered as a hybrid
SaaS: a connector agent customers run in their own environment, feeding a
catalog/search UI hosted by us.

## Inputs from the owner (raw brief, for PO/BA to turn into real spec below)
- Sources to eventually support: Postgres, Databricks, Snowflake, S3, and
  "anything multiple sources" — treat as an extensible connector framework,
  not a fixed list.
- Orchestration/lineage inputs: Airflow, dbt.
- Deployment: hybrid SaaS, control-plane/data-plane split (see decisions.md).
  Airgapped later, not now.
- MVP: Postgres + S3 connectors first.

## TODO for Product Owner
- [ ] User personas (who searches the catalog day to day — data analyst?
      data engineer? both?)
- [ ] Core user stories for MVP (search for a table, view its schema/owner/
      lineage, see which dbt model or Airflow DAG produced it)
- [ ] Success criteria for MVP demo

## TODO for Business Analyst
- [ ] Acceptance criteria per user story
- [ ] Metadata schema requirements (what fields must be captured per table/
      column/job, minimum viable lineage granularity)
- [ ] Non-functional requirements (how fresh must metadata be — real-time vs
      scheduled scrape; multi-tenant data isolation requirements even at
      single-tenant MVP stage)
