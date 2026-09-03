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

## Personas

### 1. Dana — Data Analyst
Writes SQL against the warehouse/Postgres to answer business questions.
Does not own the data she queries and often doesn't know which schema,
table, or S3 dataset actually has what she needs.

**Why the catalog beats "just query the warehouse":**
- She can't `SELECT *` her way to discovery across systems she doesn't have
  credentials for, or doesn't know exist (a Postgres schema she's never
  touched, an S3 prefix a data engineer dumped exports into).
- Querying a table doesn't tell her if it's trustworthy: is it stale? who
  owns it? is there already a similar table she should use instead of
  re-deriving it?
- She wants to search by business keyword ("orders", "churn"), not by
  knowing exact schema.table names up front.

### 2. Eli — Data Engineer
Builds and maintains the pipelines and source systems (Postgres databases,
S3 buckets/exports) that produce the data Dana and others consume. Also
consumes the catalog himself when working across systems he doesn't own.

**Why the catalog beats "just query the warehouse":**
- Before changing a table's schema, he needs to know who/what depends on
  it — direct inspection of one system can't answer that.
- He wants his tables discoverable without manually writing docs that go
  stale; the catalog should stay current by scraping metadata, not by
  someone remembering to update a wiki.
- He needs a single place to audit what's been cataloged from the systems
  he owns, across both Postgres and S3, without logging into each one.

Both personas are MVP-in-scope. Both are internal, technical users (not
end customers) — the catalog UI is a shared internal tool the customer's
own team uses inside their org.

## Core User Stories (MVP)

Scope is strictly Postgres + S3 connectors and basic catalog + search, per
decisions.md. Lineage (dbt/Airflow), tagging/curation workflows, and usage
analytics are explicitly deferred past MVP — see "Cut from MVP" below.

1. **Unified search** — As Dana, I want to search by keyword across all
   cataloged Postgres tables and S3 datasets in one search box, so I don't
   need to know in advance which system holds the data I want.
2. **Schema view** — As Dana, I want to open a search result and see its
   columns, types, and (if available) a description, so I can understand
   the data without running a query against it first.
3. **Source/location detail** — As Dana, I want to see where an asset
   actually lives (Postgres host/schema/table, or S3 bucket/prefix/format)
   so I know how to access it once I've decided it's the right one.
4. **Freshness signal** — As Dana, I want to see when an asset's metadata
   was last scraped, so I can judge whether what I'm looking at is current
   or possibly stale/abandoned.
5. **Ownership** — As Dana, I want to see who owns a table or dataset (at
   minimum, which connector/source it came from; an explicit owner field if
   captured) so I know who to ask when I have a question.
6. **Zero-touch cataloging** — As Eli, I want new and changed tables in my
   Postgres database and new prefixes/objects in my S3 bucket to show up in
   the catalog automatically after the connector runs, with no manual entry
   on my part.
7. **Audit by source** — As Eli, I want to browse/filter the catalog by
   connector/source, so I can confirm everything I expect from my systems
   has actually been cataloged.
8. **Cross-source result parity** — As Eli, I want Postgres tables and S3
   datasets to appear as peers in the same search results and browse views
   (not as two disconnected catalogs), so the MVP actually demonstrates one
   catalog over multiple sources rather than two bolted-together tools.

### Cut from MVP (explicitly out of scope, revisit post-MVP)
- Lineage graphs (dbt models, Airflow DAGs, upstream/downstream edges) —
  decisions.md scopes MVP to Postgres + S3 connectors and basic catalog +
  search only; lineage needs its own connectors (dbt/Airflow) not yet
  built.
- Manual tagging, curation, or editing of catalog metadata by end users.
- Usage/popularity analytics (e.g., "most-queried tables").
- Any notion of multi-tenant UI (multi-tenancy is out of scope for MVP per
  decisions.md; single-tenant control plane is fine).
- Databricks/Snowflake connectors, or any connector beyond Postgres + S3.

## Success Criteria (MVP Demo)

The MVP is demoable, end to end, as follows:

1. **Real connectors, real sources.** A data-plane instance runs the
   Postgres connector against a real Postgres database and the S3
   connector against a real S3 bucket, and pushes extracted metadata to
   the control plane — no metadata is seeded or hand-entered.
2. **Outbound-only, verifiably.** During the demo, the control plane
   never initiates a connection into the data-plane environment; all
   traffic is data-plane-initiated pushes. This is observable (e.g., no
   inbound listener/firewall rule needed on the customer side).
3. **Search works across both sources.** Typing a keyword in the catalog
   UI returns matching results from both the Postgres-sourced tables and
   the S3-sourced datasets in a single result list.
4. **Detail view is complete enough to be useful.** Clicking a result
   shows: columns + types (Postgres) or file format/partitioning (S3),
   source location, last-scraped timestamp, and owner/source-connector
   info — without the viewer needing to log into the source system.
5. **Change propagates without manual work.** Adding a new table to the
   demo Postgres database (or a new object/prefix to the demo S3 bucket),
   re-running the connector, and seeing it appear in search — with no
   manual catalog edits — demonstrates "zero-touch cataloging" (story 6).
6. **Connector framework, not a one-off.** The Postgres and S3 connectors
   share a common extraction/push contract (per Tech Lead's
   architecture.md), so the demo implicitly shows a third connector could
   be added without re-architecting the data plane or the push API —
   this is the real proof point for the hybrid architecture, not just
   "search works."

If all six hold up live, the MVP has proven the hybrid architecture and
the core discovery loop end to end.

## TODO for Business Analyst

> Status: FILLED IN by Business Analyst (2026-09-02), remapped after the
> Product Owner's Personas/Core User Stories/Success Criteria landed
> concurrently. Acceptance criteria below map 1:1 to the 8 numbered "Core
> User Stories (MVP)" above. Two things worth flagging up front:
> - The PO's "Cut from MVP" list explicitly excludes lineage graphs *and*
>   manual tagging/curation/editing from MVP. That resolves a conflict I'd
>   otherwise have flagged (the raw brief mentions "see which dbt
>   model/DAG produced it," which isn't buildable with Postgres+S3-only
>   connectors) — lineage is correctly deferred, not silently dropped.
>   Schema requirements below still define a Job/DAG entity and a Lineage
>   Edge entity so that when lineage connectors (dbt/Airflow) ship
>   post-MVP, it's additive, not a schema rewrite — that's forward
>   modeling, not an MVP acceptance criterion.
> - Because manual editing is cut from MVP, ownership (Story 5) is
>   **read-only, source-asserted only** for MVP — no "user edits the
>   owner in the UI" acceptance criterion. The schema still models
>   `owner_source` as source-vs-manual so a future edit feature doesn't
>   require a migration, but nothing in MVP writes `manual` today.

### Acceptance criteria per user story

**AC-1 (Story 1: Unified search)**
- Given the catalog has ingested metadata from at least one Postgres source
  and one S3 source, when a user enters a search term matching a table
  name, column name, tag, or description substring, then results from both
  source types appear in a single ranked list within 2 seconds (p95).
- Each result shows: entity name, fully-qualified location (e.g.
  `postgres://host/db.schema.table` or `s3://bucket/prefix`), source type
  icon, owner (if set), and last-scraped freshness ("scraped 3h ago").
- Empty/no-match search shows a zero-results state, not an error.
- Search must not return entities belonging to a different tenant (see
  NFR-2) — testable even in single-tenant MVP by asserting the query path
  always applies a tenant filter, not by relying on there being only one
  tenant's data present.

**AC-2 (Story 2: Schema view)**
- Given a cataloged table, when a user opens its detail page, then they see
  the full ordered column list, each with name, data type (as reported by
  the source), nullability, and primary/foreign key flags (Postgres only —
  see AC-2a for S3).
- Description is shown if the source provided one (e.g. Postgres column/
  table comment); if none was captured, the field shows "no description"
  rather than being silently omitted (no manual-entry affordance in MVP —
  see note above).
- AC-2a (S3): if the connector could not infer a schema (e.g. raw/mixed
  file formats), the detail page shows file-level metadata (format, object
  count, total size, sample key prefixes) instead of a column list, and
  states plainly that no schema was inferred — it must not show a fake or
  empty column table indistinguishable from "zero columns."

**AC-3 (Story 3: Source/location detail)**
- Given a cataloged entity, when a user opens its detail page, then the
  exact source location is shown in both human-readable and canonical
  form: Postgres as host/database/schema/table (plus `fully_qualified_name`
  string), S3 as bucket/prefix/file-format (plus `s3://` URI).
- The detail page identifies which registered source connection produced
  the entity (e.g. "prod-postgres-1"), not just the source type, so a user
  with two Postgres connections configured can tell them apart.

**AC-4 (Story 4: Freshness signal)**
- Every entity detail page and every search result row shows a
  human-readable freshness indicator derived from `last_scraped_at`
  ("scraped 3h ago").
- Detail pages additionally flag "may be stale" if the last successful
  scrape is older than 2x the configured scrape interval (see NFR-1).
- If the most recent scrape attempt for a source failed, entities from
  that source show "last successful scrape: <timestamp>, most recent
  attempt failed" rather than silently showing stale data with no warning
  (needs the Scrape Run entity below).

**AC-5 (Story 5: Ownership)**
- Given a cataloged table, when a user opens its detail page, then an
  owner section is visible, showing either a source-asserted owner (e.g.
  Postgres table comment convention, S3 object tag) or "no owner set."
- MVP is read-only here: no UI/API affordance to manually set or change
  an owner (manual curation is explicitly cut from MVP per PO). The
  `owner_source` field still exists in the schema (see below) so this is
  additive later, not a migration.

**AC-6 (Story 6: Zero-touch cataloging)**
- Given a new table is added to the demo Postgres database (or a new
  object/prefix to the demo S3 bucket) and the connector completes its
  next scrape, when the resulting push is acknowledged by the control
  plane, then the new entity is searchable within 1 minute of
  acknowledgment (ingestion latency, distinct from scrape-interval
  freshness — see NFR-1) with no manual catalog entry required.
- Repeated pushes of an unchanged entity are idempotent (upsert keyed on
  stable entity identity, not scrape-run id) — a re-scrape must not create
  duplicate entities.
- An entity no longer observed by a scrape (e.g. table dropped) is
  tombstoned (`is_deleted = true`), not silently left stale-but-visible or
  hard-deleted (hard delete would break AC-7's audit story).

**AC-7 (Story 7: Audit by source)**
- Given the catalog, when Eli filters/browses by connector or source
  connection, then he sees every entity currently attributed to that
  source connection (including tombstoned ones, clearly marked, so he can
  confirm a dropped table was deliberately dropped vs. never scraped).
- The browse view also surfaces the source connection's most recent
  Scrape Run status and timestamp, so "did my last scrape even succeed" is
  answerable without checking connector logs directly.

**AC-8 (Story 8: Cross-source result parity)**
- Given a search or browse view containing both Postgres tables and S3
  datasets, when results are rendered, then both entity types use the same
  result card/row shape (name, location, owner, freshness) and the same
  ranking/relevance logic — S3 datasets must not appear in a visually or
  functionally separate section, list, or lower-priority tier by default.
- This is the acceptance test for "one catalog over multiple sources":
  a reviewer should not be able to tell, from the search results layout
  alone, that two different connector implementations produced them.

**AC-9 (Control-plane/data-plane push contract — supports Story 6, cross-cutting)**
- Given a data-plane connector completes a scrape cycle, when it pushes
  metadata to the control plane, then the control plane acknowledges
  receipt per entity batch.
- A push must be attributable to exactly one registered data-plane
  instance and one tenant; the control plane must reject (not silently
  accept-and-drop) a push that lacks valid data-plane credentials — this
  is also what AC-1's tenant-isolation and NFR-2 depend on structurally.

### Metadata schema requirements

All entities below carry these common fields regardless of type (kept out
of each entity's field list to avoid repetition):

- `id` (UUID, globally unique)
- `tenant_id` (see NFR-2 — present and enforced even though MVP has
  exactly one tenant)
- `data_plane_id` (which customer environment/connector instance produced
  this record — a tenant may run more than one data plane)
- `source_connection_id` (which configured source, e.g. "prod-postgres-1",
  within that data plane — a data plane may run multiple connectors)
- `first_seen_at` (catalog-side, immutable once set)
- `last_scraped_at` (catalog-side, updated every successful scrape that
  observes this entity)
- `is_deleted` (bool; tombstoned, not hard-deleted, when a scrape no
  longer observes an entity the catalog previously saw — needed so
  "table was dropped" is itself discoverable/auditable, not silent data
  loss)

**Table** (covers a Postgres table/view; see Dataset below for S3)
- `source_type` (`postgres`)
- `database_name`, `schema_name`, `table_name`
- `fully_qualified_name` (canonical, e.g. `postgres://<host>/<db>.<schema>.<table>`)
- `object_type` (`table` | `view` | `materialized_view`)
- `description` (nullable; `description_source` = `source_comment` |
  `manual` — manual descriptions must not be overwritten by a re-scrape
  that finds no comment)
- `owner` (nullable; `owner_source` = `source` | `manual`, per AC-3)
- `tags` (list, freeform + optionally a controlled vocabulary later)
- `row_count_estimate` (nullable — from source stats, explicitly labeled
  as an estimate, never presented as exact)
- `size_bytes_estimate` (nullable)
- `source_created_at` (nullable, from source system if available)
- `source_last_modified_at` (nullable, from source system if available)

**Column** (belongs to a Table)
- `table_id` (FK)
- `name`, `ordinal_position`
- `native_data_type` (exact string as reported by source, e.g.
  `character varying(255)`)
- `normalized_data_type` (catalog's canonical type bucket, e.g. `string`,
  `integer`, `timestamp` — needed so search/UI can group/filter across
  Postgres and future sources consistently)
- `is_nullable` (bool)
- `is_primary_key`, `is_foreign_key` (bool)
- `foreign_key_ref` (nullable pointer to referenced table/column — this is
  itself a lightweight lineage/relationship fact and should be
  representable as a lineage edge too, not just a column attribute, per
  KG direction in decisions.md)
- `description` (nullable; same `description_source` pattern as Table)
- `tags`

**Dataset** (covers an S3-sourced object — a bucket+prefix grouped as one
logical unit; distinct from Table because S3 has no guaranteed schema)
- `source_type` (`s3`)
- `bucket`, `prefix`
- `fully_qualified_name` (canonical, e.g. `s3://<bucket>/<prefix>`)
- `file_format` (nullable — `parquet` | `csv` | `json` | `mixed` |
  `unknown`)
- `schema_inferred` (bool — drives AC-2a's "no schema inferred" state)
- `object_count_estimate`, `total_size_bytes_estimate`
- `description`, `owner`, `tags` — same pattern as Table
- Optional: `fields` list reusing the Column shape above when
  `schema_inferred = true` (e.g. Parquet schema or Glue-catalog-style
  inference); absent when `schema_inferred = false`

**Job / DAG** (schema defined now for extensibility; no connector
populates this in MVP — see AC-4 scope conflict)
- `job_type` (`dbt_model` | `airflow_dag` | `airflow_task` | `manual` |
  `unknown`)
- `name`, `source_system`
- `owner`
- `schedule` (nullable cron-like string)
- `description`
- `last_run_at`, `last_run_status` (nullable — `success` | `failed` |
  `running` | `unknown`)

**Lineage Edge**
- `upstream_entity_id`, `upstream_entity_type` (`table` | `column` |
  `dataset` | `job`)
- `downstream_entity_id`, `downstream_entity_type`
- `edge_granularity` (`table_level` | `column_level`) — **MVP minimum
  viable granularity is table-level**; column-level is schema-supported
  but not required for MVP demo (parsing SQL/dbt for column-level lineage
  is materially more work and should be scoped explicitly if wanted for
  MVP — flagging so it isn't assumed free)
- `producer_job_id` (nullable FK to Job/DAG — null when lineage is
  inferred or manually asserted rather than job-derived)
- `confidence` (`inferred` | `manually_asserted` | `job_declared`) —
  distinguishes a `pg_depend`-derived edge from a future dbt-manifest-derived
  edge from a human-entered edge, so the UI can be honest about provenance
  (ties directly into AC-4's "inferred from schema" / "manually asserted"
  labeling)
- `discovered_at`, `last_confirmed_at` (an edge not re-confirmed by N
  consecutive scrapes is a candidate for tombstoning, same as any other
  entity)

**Scrape Run** (needed to support AC-5's freshness/failure states and
NFR-1's staleness display — not itself catalog content, but required
alongside the entities above)
- `source_connection_id`, `data_plane_id`, `tenant_id`
- `started_at`, `completed_at` (nullable if still running/failed)
- `status` (`success` | `partial_failure` | `failed` | `running`)
- `entities_seen_count`, `entities_created_count`,
  `entities_tombstoned_count`
- `error_summary` (nullable)

### Non-functional requirements

**NFR-1 — Metadata freshness: scheduled scrape, not real-time, for MVP.**
- Decision: each source connection scrapes on a configurable interval,
  default **every 6 hours**, plus an on-demand "scrape now" trigger a user
  can invoke from the UI/API for a single source connection.
- Justification: (1) the push model is already outbound-batch by design
  (decisions.md — data plane pushes to control plane, not a live query
  channel), so "real-time" would mean either CDC/trigger-based capture
  inside the customer's Postgres or continuous S3 event-notification
  processing — both are materially more engineering and customer-side
  setup (e.g. enabling `wal_level=logical` or S3 event notifications) than
  an MVP whose goal is proving the hybrid push architecture end-to-end.
  (2) Catalog/discovery consumers (per Amundsen precedent, decisions.md's
  product framing) tolerate metadata being hours old — the value
  proposition is "can I find this table and understand it," not "is this
  the current row count to the second." (3) A fixed interval is trivial to
  make tighter later per-source without a schema change (it's a connector
  config value, not a data-model constraint) — so this is not a
  future-blocking choice.
- Corollary: `last_scraped_at` + Scrape Run status (schema above) must be
  surfaced in the UI (AC-5), because "freshness is honestly displayed" is
  what makes a 6-hour interval acceptable — silently stale data is not.
- Ingestion latency (control plane processing a received push) is a
  separate, tighter bound: target under 1 minute from push acknowledgment
  to searchable (AC-6), since that's a control-plane processing cost, not
  a customer-environment scrape cost, and there's no reason to add lag
  there.

**NFR-2 — Tenant isolation in the data model, single-tenant MVP.**
- Every entity (Table, Column, Dataset, Job/DAG, Lineage Edge, Scrape Run)
  carries a non-nullable `tenant_id` from day one, even though MVP
  provisions exactly one tenant row. This is a hard requirement, not a
  nice-to-have: retrofitting a tenant column onto populated production
  tables later is a migration that touches every table and every query
  path, which is exactly the "rewrite for multi-tenancy" decisions.md
  rules out.
- `tenant_id` must be enforced at the query/API layer as a mandatory
  filter (every read path takes a tenant scope from the authenticated
  caller's context, never from a client-supplied parameter that could be
  omitted or spoofed), not just present as a column. Recommend the control
  plane's datastore(s) use row-level security (e.g. Postgres RLS) or an
  equivalent mandatory-scoping mechanism as a structural guarantee, so a
  future bug in one query path can't leak cross-tenant data — this is
  worth doing even in MVP because it's cheap to add now and expensive to
  retrofit as a security fix later.
- Model the containment hierarchy as `tenant → data_plane →
  source_connection → entities`, not `tenant → entities` directly. A
  single customer (tenant) may run multiple data planes (e.g. staging +
  prod VPCs) even in a single-tenant-SaaS world, so this hierarchy should
  exist now rather than being bolted on when multi-tenancy work starts.
- The metadata push API (data-plane → control-plane contract, owned by
  Tech Lead in architecture.md) must authenticate each push to a specific
  `data_plane_id`/`tenant_id` pair via credentials issued at data-plane
  registration — never a tenant_id passed as a plain request field the
  data plane could set arbitrarily. This is a security requirement as much
  as a data-modeling one; flagging it for Tech Lead's architecture.md since
  it's the push-contract's job to enforce, not the schema's alone.
- Search index and any denormalized/read-optimized stores (e.g. a
  ClickHouse projection per decisions.md's storage-evaluation note) must
  also carry `tenant_id` on every row/document — a fast read path that
  forgets tenant scoping is a common source of cross-tenant leaks, so this
  should be called out explicitly to whoever builds the search index, not
  assumed to be "obviously" carried through from the source-of-truth
  store.
