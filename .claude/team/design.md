# Design

Status: DRAFT — owned by Designer. Written against `spec.md` after PO
(personas, 8 user stories, success criteria) and BA (acceptance criteria,
metadata schema, NFRs) filled it in on 2026-09-02. All screen/state
decisions below map to a specific user story (US-#), acceptance criterion
(AC-#), or NFR — cited inline so engineers can trace UI requirements back
to spec. One real spec conflict is flagged in §6 rather than silently
resolved.

## MVP scope reminder (from spec.md, do not re-add cut features)
In scope: US-1 through US-8 (unified search, schema view, source/location
detail, freshness signal, ownership, zero-touch cataloging, audit-by-
source, cross-source parity). **Explicitly cut from MVP, per Product
Owner:** lineage graphs, manual tagging/curation, usage/popularity
analytics, multi-tenant UI. This design does **not** include a Lineage tab
or a Usage tab — the metadata schema keeps lineage/job entities
schema-ready (BA's Lineage Edge / Job-DAG tables) for when Airflow/dbt
connectors ship, but no lineage UI is built now.

---

## 1. Information Architecture

### 1.1 Entity model (what the UI navigates between)

Matches BA's metadata schema in spec.md directly — using BA's field/entity
names so engineers can map UI fields to API fields without translation.

```
Tenant (1, MVP) → Data Plane (1+, e.g. "customer-prod-vpc") →
  Source Connection (1+, e.g. "prod-postgres-1", "raw-events-s3") →
    Entities: Table | Dataset
      + Column (children of Table)
      + Scrape Run (history, belongs to Source Connection, not the entity)

Table   — Postgres table/view. fully_qualified_name, database_name,
          schema_name, table_name, object_type, description
          (+description_source), owner (+owner_source), tags,
          row_count_estimate, size_bytes_estimate, source_created_at,
          source_last_modified_at, last_scraped_at, is_deleted.
Column  — belongs to a Table. name, ordinal_position, native_data_type,
          normalized_data_type, is_nullable, is_primary_key,
          is_foreign_key (+foreign_key_ref), description, tags.
Dataset — S3-sourced. fully_qualified_name (s3://bucket/prefix),
          file_format, schema_inferred (bool — drives AC-2a state),
          object_count_estimate, total_size_bytes_estimate, description,
          owner, tags, optional `fields` (Column-shaped) when
          schema_inferred = true.
Scrape Run — per Source Connection. started_at, completed_at, status
          (success | partial_failure | failed | running),
          entities_seen/created/tombstoned_count, error_summary.
```

Generic UI term: **"Asset"** = Table or Dataset, used wherever the UI
needs to refer to either type without distinguishing (search results,
breadcrumbs). Job/DAG and Lineage Edge entities exist in the schema but
have **no MVP screen** — no connector populates them yet (AC-4's scope
conflict, resolved by PO as "descope for MVP" per the cut list).

### 1.2 Navigation hierarchy

```
Global top nav (persistent):  [Logo/Home]  [Search bar]  [Browse]  [Sources]  [?]

Home / empty search  →  Search Results  →  Asset Detail
                                              └─ (source link) → Source Connection Detail

Sources (top nav)  →  Source Connection List  →  Source Connection Detail
                        (grouped by Data Plane)     ├─ Scrape Run history
                                                     └─ [Scrape now]
```

- **Search is the primary entry point** (US-1). Home state shows recently
  viewed assets, not a blank box — empty for new users, not an error.
- **Browse** is the secondary path for a user who doesn't know what to
  search for (US-3's "where does it live" framing generalized): browse by
  Data Plane → Source Connection → Database/Bucket → Schema/Prefix → Asset
  list. Reuses the Search Results list component, pre-filtered.
- **Sources** is a first-class top-nav item (US-6, US-7: zero-touch
  cataloging and audit-by-source both depend on a user being able to
  check "did my stuff actually get scraped," not just search results).
  Any user can view it — it's not an admin-only page in MVP since Eli (a
  regular technical user, not necessarily an admin role) needs it for
  audit-by-source.
- Every Asset Detail page links back to its Source Connection (badge in
  header); every Source Connection row links forward to its assets — the
  loop closes both directions, matching US-7's audit flow ("confirm
  everything I expect from my systems has actually been cataloged" starts
  from the source and checks outward, not just from search inward).

---

## 2. Screen: Search Results View (US-1, US-8, AC-1)

### Layout
```
┌───────────────────────────────────────────────────────────────────┐
│ [Logo]   [======== search input ========]   Browse  Sources   [?] │
├───────────────┬───────────────────────────────────────────────────┤
│ FILTERS        │  "customers" — 42 results          Sort: [Relevance ▾]│
│                │  ┌─────────────────────────────────────────────┐ │
│ Entity type    │  │ 🐘 TABLE · prod-postgres-1                  │ │
│ ☐ Table        │  │ postgres://prod-db/public.customers          │ │
│ ☐ Dataset      │  │ Customer master record...                    │ │
│                │  │ Owner: jane@co (source)                       │ │
│ Source conn.   │  │ scraped 20 min ago              [✓ fresh]    │ │
│ ☐ prod-pg-1    │  ├─────────────────────────────────────────────┤ │
│ ☐ raw-events-s3│  │ 🪣 DATASET · raw-events-s3                   │ │
│                │  │ s3://raw-events/customers_snapshot/           │ │
│ Tags           │  │ No description                                │ │
│ ☐ pii  ☐ core  │  │ Owner: no owner set                           │ │
│                │  │ scraped 9d ago            [⚠ stale, >12h]    │ │
│                │  └─────────────────────────────────────────────┘ │
└───────────────┴───────────────────────────────────────────────────┘
```

### Key components
- **Search input**: persistent in top nav on every screen. Matches on
  entity name, column name, tag, or description substring (AC-1).
  Autocomplete on name prefix is a nice-to-have, not AC-required for MVP.
- **Result row fields, per AC-1 exactly**: entity name, fully-qualified
  location (`postgres://host/db.schema.table` or `s3://bucket/prefix`),
  source-type icon, owner if set (else "no owner set" — never blank),
  freshness indicator ("scraped 3h ago" style). Entity type badge (TABLE
  vs DATASET) is additive to AC-1, needed so Postgres and S3 results are
  visually legible as peers in one list (US-8/cross-source parity) — same
  row shape, same field order, same typography for both; only the icon
  and type badge differ.
- **Facet filters**: entity type (Table/Dataset), source connection
  (US-7's audit-by-source — filtering search by connector is the
  mechanism for that story), tags. No owner facet required by AC-1;
  optional nice-to-have if cheap.
- **Sort**: Relevance (default), Recently scraped, Name A-Z. **No
  "popular"/usage-based sort** — usage analytics is cut from MVP per PO;
  do not build a signal for it.
- **No tenant picker/switcher anywhere in this UI** — NFR-2 requires
  tenant scoping to be enforced server-side from the authenticated
  caller's session, never a client-supplied parameter. The UI must not
  expose a tenant_id field or selector (there's nothing to pick in
  single-tenant MVP, and building the affordance would create exactly the
  client-supplied-tenant-parameter shape NFR-2 warns against).

### States
| State | Behavior |
|---|---|
| Empty query (landing) | Show "Recently viewed" (per-user, empty for new users). No blank canvas. |
| No results | AC-1: "zero-results state, not an error." — "No assets match 'x'." + suggest checking filters + link to Sources ("Not seeing what you expect? Check source status"). |
| Loading | Skeleton rows. AC-1 targets p95 < 2s server-side; skeleton, not spinner, so layout doesn't jump when results land. |
| Search backend error | Inline banner above results, page (nav/filters) stays usable: "Search is temporarily unavailable. [Retry]" |
| Result's source has a failed most-recent scrape (AC-5) | Badge reads `[⚠ scrape issue]` instead of `[✓ fresh]` even if the last *successful* scrape is recent — see §3.3 for the exact rule; don't collapse this into the plain "stale" badge, they mean different things. |
| One or more source connections degraded/down | Persistent dismissible banner above results: "N source connection(s) haven't completed a scrape recently — results from those may be incomplete or stale. [View sources]" |

---

## 3. Screen: Asset Detail View (US-2, US-3, US-4, US-5, AC-2, AC-2a, AC-3, AC-5)

No tabs in MVP — with lineage and usage both cut, there's one real content
section (Schema / file metadata) plus a header carrying location,
ownership, and freshness. Keeping it a single page avoids building tab
scaffolding for content that doesn't exist yet.

### Layout — Table (Postgres)
```
┌───────────────────────────────────────────────────────────────────┐
│ Sources / prod-postgres-1 / public / customers                     │
│                                                                      │
│ 🐘 TABLE  customers                                    [✓ fresh]    │
│ postgres://prod-db/public.customers                                 │
│ Customer master record, one row per registered account.             │
│   (description from: source comment)                                │
│                                                                      │
│ Owner: jane@co  (source)                    Tags: pii, core         │
│ Rows: ~1.2M (estimate)   Size: ~340 MB (estimate)                    │
│ Last scraped: 20 min ago · Source last modified: 2h ago              │
├───────────────────────────────────────────────────────────────────┤
│  Column          Type              Nullable  Key    Description     │
│  id              bigint            no        PK     —               │
│  email           text              no               —               │
│  created_at      timestamp         no               —               │
│  plan_id         bigint            yes       FK→plans.id             │
│  ... (virtualized/paginated for wide tables)                         │
└───────────────────────────────────────────────────────────────────┘
```

### Layout — Dataset (S3), schema inferred
Same header shape, `🪣 DATASET`, location shown as `s3://bucket/prefix`,
file_format shown next to the type badge (e.g. `DATASET · parquet`).
Column table populated from `fields` when `schema_inferred = true`.

### Layout — Dataset (S3), schema NOT inferred (AC-2a — required state)
```
┌───────────────────────────────────────────────────────────────────┐
│ 🪣 DATASET · mixed          raw-events-s3 / customers_snapshot/     │
│ s3://raw-events/customers_snapshot/                    [✓ fresh]    │
│ No description                                                      │
│ Owner: no owner set                          Tags: —                │
├───────────────────────────────────────────────────────────────────┤
│  No schema could be inferred for this dataset.                      │
│  (mixed/unrecognized file format — showing file-level metadata)     │
│                                                                      │
│  Format: mixed        Object count: ~1,204 (estimate)                │
│  Total size: ~18.4 GB (estimate)                                     │
│  Sample key prefixes:                                                │
│    customers_snapshot/2026-08-30/                                    │
│    customers_snapshot/2026-08-31/                                    │
│    customers_snapshot/2026-09-01/                                    │
└───────────────────────────────────────────────────────────────────┘
```
This is a **named, explicit state per AC-2a** — it must render visibly
differently from a Table with zero columns, not just an empty column
table. Never render an empty `<table>` with a header row and nothing
under it for this case; render the file-metadata block instead.

### Header fields
- Breadcrumb: `Sources / <source connection> / <db|bucket> / <schema|
  prefix> / <name>` — source-connection segment links to Source
  Connection Detail (US-3's "where does it live," extended into "and who
  runs the connector that told us about it").
- Entity type badge + icon + name; for Dataset, file_format shown inline.
- Fully-qualified name (`fully_qualified_name`) shown as a copyable string
  directly under the title — this is the literal answer to US-3 ("how do
  I access it once I've decided it's the right one").
- Description: read-only in MVP (manual editing of description is cut
  per PO's list). Shown with its provenance: `(description from: source
  comment)` when `description_source = source_comment`, or "No
  description" (muted) when null. **No edit affordance in MVP.**
- Owner: shown with provenance (`(source)` / `(manually set)`) or "no
  owner set" (AC-3). **Whether this field is editable in the UI is an
  open conflict — see §6, item 1. Build read-only first; edit control is
  additive once resolved, not a blocker for the rest of this screen.**
- Tags: read-only list or "—" if empty. No add/edit control (manual
  tagging cut from MVP per PO) even though the schema field exists.
- Row/size estimates: always labeled "(estimate)" per schema
  (`row_count_estimate`, `size_bytes_estimate`) — never presented as
  exact counts.
- Freshness line: `Last scraped: <relative, from last_scraped_at>` +, if
  the source reports it, `Source last modified: <relative, from
  source_last_modified_at>`. These are two different clocks (pipeline
  freshness vs. actual data freshness) — see §3.3, don't merge them into
  one label.

### 3.3 Freshness / staleness — concrete rule (NFR-1, AC-2, AC-5)
- **Stale threshold = 2x the configured scrape interval** (AC-2),
  default scrape interval is 6h (NFR-1) → default stale threshold is
  **12h** since `last_scraped_at`. Threshold must be read from the
  source connection's configured interval, not hardcoded to 12h, since
  interval is per-source-connection configurable.
- **Badge logic** (same shared component used in §2 and here):
  - `✓ fresh` — last scrape succeeded and `last_scraped_at` is within the
    stale threshold.
  - `⚠ stale` — `last_scraped_at` is past the stale threshold (regardless
    of why).
  - `⚠ scrape issue` — the most recent Scrape Run attempt has
    `status = failed` (or `partial_failure`), even if the last
    *successful* scrape is still within the fresh window. Per AC-5 this
    must say, on hover/detail: "last successful scrape: <timestamp>, most
    recent attempt failed" — do not hide an active failure just because
    old data still looks fresh enough.
  - `✗ never scraped` — no successful Scrape Run yet (shouldn't occur for
    an entity that exists, since entities are created by a scrape, but
    applies to a Source Connection with zero runs — see §4).
- If both stale and scrape-issue conditions hold, show `⚠ scrape issue`
  (it's the more specific, more actionable message — "stale" is really a
  symptom of it in that case).

### States
| State | Behavior |
|---|---|
| Loading | Header + content skeleton. |
| Asset not found | Could mean tombstoned (`is_deleted = true`, source stopped reporting it) or truly invalid id. "This asset is no longer reported by its source connection. It may have been removed, renamed, or the connector may be misconfigured. [View source status]" |
| Fetch error | Banner: "Could not load this asset. [Retry]" — do not fabricate a stale cached view unless one is already loaded in this session. |
| Table, columns present | Standard column table (see layout above), PK/FK flags per AC-2. |
| Dataset, schema not inferred | File-metadata block per AC-2a (layout above) — not an empty column table. |
| No description / no owner / no tags | Explicit muted text ("No description", "no owner set", "—"), never blank space. |
| Stale / scrape-issue | Badge per §3.3 + a full-width banner under the header: "Metadata may be out of date — <detail from §3.3 rule>. [Check source status]" |

---

## 4. Screen: Source Connection Status View (US-6, US-7, NFR-1, AC-6, Scrape Run schema)

Renamed from a generic "connector status" screen to line up with BA's
schema: the entity being listed/monitored is a **Source Connection**
(e.g. `prod-postgres-1`), grouped under its **Data Plane** (a tenant may
run more than one — NFR-2). This is the trust layer for the hybrid
model: users need an honest answer to "is this connection alive, and
what did its last scrape actually do."

### 4.1 List view
```
┌───────────────────────────────────────────────────────────────────┐
│ Sources                                                              │
├───────────────────────────────────────────────────────────────────┤
│ ▾ Data plane: customer-prod-vpc                                     │
│   Status   Connection        Type      Assets  Last scrape   Errors │
│   🟢 OK    prod-postgres-1   postgres  128     20 min ago    0      │
│   🟡 STALE raw-events-s3     s3        54      9 days ago    0      │
│   🔴 FAIL  legacy-pg         postgres  0       attempt 09:11 3      │
│ ▾ Data plane: customer-staging-vpc                                  │
│   ⚪ NEW   staging-pg        postgres  0       never          —     │
└───────────────────────────────────────────────────────────────────┘
```
- Grouped by Data Plane (schema hierarchy is tenant → data_plane →
  source_connection); MVP demo likely has one data plane, but the UI
  should not assume exactly one, per NFR-2's containment-hierarchy
  requirement.
- Status derived from the most recent Scrape Run(s) for that connection:
  🟢 last run `success` and within stale threshold; 🟡 last successful
  run past stale threshold (stale) OR most recent attempt
  `partial_failure`; 🔴 most recent attempt `failed` outright, or
  repeated failures; ⚪ zero Scrape Runs ever (`never` — onboarding
  state, distinct from stale/failed).
- Row click → Source Connection Detail. Default sort: worst-status-first.

### 4.2 Detail view
```
┌───────────────────────────────────────────────────────────────────┐
│ prod-postgres-1                                    🟢 OK  [Scrape now]│
│ Type: postgres · Data plane: customer-prod-vpc                      │
│ Scrape interval: every 6h (configured)                               │
│ Assets: 128 tables (0 tombstoned)          [ ] Show tombstoned      │
├───────────────────────────────────────────────────────────────────┤
│ Scrape run history                                                   │
│  ✓ 09:41  success       128 seen · 2 created · 0 tombstoned          │
│  ✓ 09:26  success       126 seen · 0 created · 0 tombstoned          │
│  ✗ 09:11  failed        connection refused to source DB              │
├───────────────────────────────────────────────────────────────────┤
│ [View assets from this connection →]                                 │
└───────────────────────────────────────────────────────────────────┘
```
- **`[Scrape now]`** — the on-demand trigger NFR-1 explicitly calls for
  ("a user can invoke from the UI/API for a single source connection"),
  in addition to the default 6h scheduled interval.
- **Scrape run history** rows map directly to the Scrape Run schema:
  status, `entities_seen_count`/`created_count`/`tombstoned_count`,
  `error_summary` when failed. This is the diagnostic surface for "why is
  my catalog out of date" (US-6) — error text must be actionable
  ("connection refused," "auth rejected," "schema extraction timeout on
  table X") but never include credentials/connection strings, since the
  data plane sends metadata only, never secrets (decisions.md) — flagging
  to Tech Lead that `error_summary` must already be sanitized before it's
  pushed, this isn't something the UI can filter after the fact.
- **`Show tombstoned` toggle** — supports US-7 (audit-by-source):
  entities the source connection used to report but no longer does
  (`is_deleted = true`) are hidden from normal asset counts/search by
  default but must be inspectable here, since "confirm everything I
  expect has been cataloged" includes noticing something silently
  disappeared.
- No connection strings/credentials/secrets ever shown — config summary
  is name, type, data plane, interval only.
- `[View assets from this connection →]` reuses the Search Results
  component pre-filtered by source connection.

### States
| State | Behavior |
|---|---|
| No source connections registered yet | Onboarding empty state: "No sources connected yet. Install the data-plane connector in your environment to get started. [Setup instructions →]" |
| 🟢 OK | As above. |
| 🟡 Stale or partial failure | Banner: "No successful scrape in over <threshold> — expected every <interval>. The connector may be down, or network egress may be blocked." Explicitly note troubleshooting is customer-side: outbound-only means the control plane cannot reach into the data plane to fix it. |
| 🔴 Failed | Red status + `error_summary` from the latest run surfaced prominently, plus history showing the pattern. |
| ⚪ Never scraped | "This connection hasn't completed a scrape yet." + `[Scrape now]` prominent, not buried. |
| Loading | Skeleton list/detail. |
| Error loading status data itself | Visually distinct generic error banner (not a red connection-status dot) — a control-plane-internal failure must not be mistaken for "your connector is down." |

---

## 5. Cross-cutting notes for engineers

- **One shared freshness-badge component**, states exactly as enumerated
  in §3.3 (`fresh` / `stale` / `scrape issue` / `never scraped`), reused
  in Search Results, Asset Detail, and Source Connection list/detail. Do
  not let each screen invent its own status vocabulary or its own
  threshold math — compute it once against `last_scraped_at` +
  configured interval + latest Scrape Run status, in one place.
- **Source health is context, not a gate.** Search/browse keep working
  when a source connection is stale/failed — only annotate, never block.
- **Table and Dataset render as peers.** Same result-row shape, same
  detail-header shape; only icon/type-badge/location-string-format and
  the Schema-vs-file-metadata content block differ. This is a direct
  requirement of US-8 / cross-source parity, not a nice-to-have.
- **Tombstoned entities** (`is_deleted = true`) are excluded from default
  search and asset counts everywhere except the Source Connection
  detail's explicit "Show tombstoned" toggle (US-7).
- **No lineage or usage UI in MVP.** Do not build placeholder tabs for
  these — the cut list is explicit. Revisit once dbt/Airflow connectors
  and a usage-tracking mechanism exist.

---

## 6. Open questions / conflicts for other roles (not silently resolved)

1. **Real spec conflict, needs PO or BA to resolve — owner editing.**
   PO's cut list (status.md, 2026-09-02) says "manual tagging,
   curation, or editing of catalog metadata by end users" is cut from
   MVP. BA's AC-3 (spec.md) explicitly requires: "A user with edit
   rights can manually set/change the owner from the UI; this manual
   assertion must survive the next scrape." These directly conflict for
   the owner field specifically (tags/description editing being cut is
   unambiguous either way). I did not silently pick one — §3 designs the
   owner field read-only-first with provenance display (satisfies the
   "view ownership" half of AC-3 and US-5 either way), and calls out the
   edit control as additive once this is resolved, so engineers aren't
   blocked on the rest of the detail page while it's settled.
2. **To Tech Lead:** confirm `error_summary` on a Scrape Run is sanitized
   of secrets/connection details *before* it's pushed from the data
   plane (decisions.md: metadata only, never credentials, never raw
   data) — the Source Connection Detail screen (§4.2) surfaces this
   string directly to users, so it can't rely on control-plane-side
   filtering as the only safeguard.
3. **To BA/Tech Lead:** confirm the scrape interval used for the stale
   threshold (§3.3) is readable per-source-connection via the API (not
   just a global default), since NFR-1 allows per-source configuration
   and the UI's staleness math depends on knowing each connection's
   actual configured interval.
4. **To PO:** AC-4's lineage scope conflict is marked "resolved by PO as
   descope for MVP" in this document based on the status.md cut list —
   if that's not actually final, the Lineage-tab work in §5 ("no lineage
   UI in MVP") would need to be revisited before engineers rely on this
   document.
