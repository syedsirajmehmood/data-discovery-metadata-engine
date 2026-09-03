# control-plane/web

Catalog UI for the data discovery / metadata catalog. TypeScript + React,
built with Vite (per `.claude/team/decisions.md`, "Control-plane
implementation language"). Owned by FE3; scope is this directory only —
consumes FE2's catalog read API as plain REST/JSON, no direct storage
access.

Implements the 3 MVP screens from `.claude/team/design.md`:

1. **Search Results View** (`src/pages/SearchResultsPage.tsx`, design.md §2)
2. **Asset Detail View** (`src/pages/AssetDetailPage.tsx`, design.md §3)
3. **Source Connection Status View** (`src/pages/SourceConnectionListPage.tsx`
   + `src/pages/SourceConnectionDetailPage.tsx`, design.md §4)

No Lineage or Usage UI — explicitly cut from MVP per design.md §5; not
stubbed with placeholder tabs.

## Running the dev server

```bash
npm install
npm run dev
```

Opens on `http://localhost:5173` (or the next free port). **FE2's real
backend does not exist in this worktree yet**, so by default the app runs
against an in-browser fetch mock (`src/api/mocks/mockFetch.ts` + fixture
data in `src/api/mocks/fixtures.ts`) that implements the exact endpoint
shapes documented in `architecture.md` §8 and this app's own assumed
extensions (see "API assumptions" below). This lets every screen and every
required state be exercised with no backend running.

To point the app at a real backend instead:

```bash
VITE_USE_MOCKS=false VITE_API_BASE_URL=https://your-control-plane-host npm run dev
```

`VITE_API_BASE_URL` is empty (relative paths) by default — never hardcode
a host in source; see `src/api/client.ts`.

### Exercising specific states in the running dev app

The fixture data already covers most required states (fresh/stale/scrape-
issue/never-scraped badges, a schema-inferred and a non-schema-inferred
Dataset, a tombstoned entity, all 4 source-connection statuses). A few
states are query-param triggers on top of that, for convenience:

- Search for the literal query `erroritis` → simulated search-backend 500,
  to see the "Search is temporarily unavailable" banner.
- Visiting `/asset/urn:postgres:does-not-exist` (any urn not in
  `src/api/mocks/fixtures.ts`) → simulated 404, to see the not-found state.
- `mockFetch.ts`'s `handleAssetDetail`/`handleSourcesStatus` also honor
  `?simulate=404`, `?simulate=error`, and `?empty=1` on the underlying
  fetch call itself (not the browser address bar, since neither page
  forwards its own query string to the API) — the more direct way to hit
  every state is the pages' own test files, which drive each state
  explicitly by mocking `src/api/catalog.ts` per test.

## Running tests

```bash
npm run test        # vitest run, once
npm run test:watch  # vitest, watch mode
npm run test:ui     # vitest --ui
```

Vitest + React Testing Library, 45 tests across 7 files: the shared
freshness/format utilities (pure-function unit tests), the
`FreshnessBadge` component, and all 4 pages (mocking `src/api/catalog.ts`
at the module boundary per page, so each test controls loading/success/
error/edge-case responses directly rather than going through the fetch
mock layer).

Note: `vite.config.ts`'s `test.environmentOptions.jsdom.url` is
deliberately set to a real origin — jsdom throws `SecurityError` for
`localStorage` on the default opaque `about:blank` origin, which
`src/lib/recentlyViewed.ts` (backing the Search page's "Recently viewed"
landing state) depends on. `src/test/setup.ts` additionally installs a
tiny in-memory `localStorage` polyfill, because recent Node versions ship
an experimental built-in `localStorage` global that shadows jsdom's real
one and lacks a working `.clear()` — without the polyfill, tests that
touch `localStorage` fail with `window.localStorage.clear is not a
function` regardless of the jsdom origin fix.

## Building

```bash
npm run build   # tsc -b && vite build
npm run lint    # oxlint
```

## Structure

```
src/
  api/
    client.ts        fetch wrapper (base URL, error handling) — the only
                      place that calls fetch() for real traffic
    catalog.ts        typed functions per documented endpoint
    mocks/
      fixtures.ts      fixture data, covers every required UI state
      mockFetch.ts      installs a fetch mock (dev mode default)
  components/
    FreshnessBadge.tsx  THE shared freshness badge (design.md §5) — used
                        by search results, asset detail, and both source
                        connection screens. Do not reimplement badge logic
                        elsewhere; add to src/lib/freshness.ts instead.
    EntityIcon.tsx      shared Table/Dataset icon + type badge
    ErrorBanner.tsx, TopNav.tsx
    asset/              Asset Detail's column table + AC-2a file-metadata block
    search/              Search Results' facets, result row, skeleton, degraded banner
    sources/              Source Connection status dot
  lib/
    freshness.ts        computeFreshness() — the one badge-logic implementation
    format.ts           relative-time / byte / count formatting
    recentlyViewed.ts    localStorage-backed "recently viewed" for the search landing state
  pages/                 one file per route, each with a colocated *.test.tsx
  types/catalog.ts        API types, with inline JUDGMENT CALL comments
                          wherever a response shape wasn't fully specified
  styles/app.css          single global stylesheet
```

## API assumptions

`architecture.md` §8 documents 4 catalog-read endpoints:
`GET /v1/catalog/search`, `GET /v1/catalog/tables/{urn}`,
`GET /v1/catalog/tables/{urn}/lineage` (intentionally unused — no lineage
UI in MVP), and `GET /v1/catalog/sources/status`. It does not fully
specify every response field this UI needs. Rather than invent new routes
outside that documented surface, this UI assumes:

- **Facet counts** on `GET /v1/catalog/search`: a `facets` object
  (`entity_type`, `source_connection`, `tags`, each with per-value counts)
  computed over the current query, standard faceted-search shape.
- **Freshness context denormalized onto every entity/search-result**: each
  entity and search result carries a `freshness` object (stale threshold
  in seconds, latest scrape-run status, last successful scrape time, and
  whether any scrape run exists at all) so the shared badge component can
  render without a second round trip. Assumed denormalized into the search
  index at write time, same as name/description/tags/owner already are
  per `architecture.md` §4.
- **`GET /v1/catalog/sources/status?source_connection_id=<id>`** — the
  same documented endpoint, scoped to one connection, additionally
  populates `scrape_runs` and `tombstoned_entities` (omitted on the
  unscoped list call to keep that payload light). Used for the Source
  Connection Detail screen instead of inventing a separate route.
- **`POST /v1/catalog/sources/{id}/scrape`** ("Scrape now", design.md
  §4.2) — **does not exist on the backend yet.** Not part of
  architecture.md's documented catalog read API at all (it's a write, not
  a read). `src/api/catalog.ts`'s `triggerScrapeNow()` calls it anyway,
  per this task's requirement, and documents the expected contract inline:
  per `architecture.md` §5's forward-compatible command-queue pattern, the
  call should enqueue a "scrape now" command that the data-plane agent
  picks up on its next outbound poll of `GET /v1/commands` — not run a
  scrape synchronously. The UI treats a 404/501 response as "not available
  yet" (a distinct, non-alarming inline message) rather than a hard error.
- **Dataset `sample_key_prefixes`**: design.md §3's "schema not inferred"
  layout shows a sample-key-prefix list that isn't itemized in spec.md's
  Dataset schema. Modeled as optional on `DatasetEntity`; the UI omits
  that section gracefully if the backend doesn't send it.

All of the above are called out inline in `src/types/catalog.ts` and
`src/api/catalog.ts` with `JUDGMENT CALL` comments at the exact field/
function in question.

## Judgment calls (design.md ambiguities)

Beyond the API-shape assumptions above:

- **"Browse" in the top nav.** design.md §1.2 describes Browse as a
  secondary drill-down path (Data Plane → Source Connection →
  Database/Bucket → Schema/Prefix → Asset list) that explicitly "reuses
  the Search Results list component, pre-filtered." That multi-level
  drill-down isn't one of the 3 screens this task scoped, and design.md
  itself frames it as a thin reuse of Search Results rather than new UI.
  `TopNav`'s Browse link routes to `/search` unfiltered; the facet filters
  already on that screen are the pre-filtering mechanism design.md
  describes. A dedicated hierarchical browse UI was not built.
- **Source Connection Detail's "Show tombstoned" toggle** (design.md
  §4.2). The wireframe places the checkbox next to the asset count line
  but doesn't show what it reveals on that screen. Per US-7/AC-7's
  requirement that tombstoned entities be "inspectable here" (on the
  Source Connection Detail screen itself, not only via a search filter),
  the toggle reveals an inline list of tombstoned entities for that
  connection (name + last-seen time, linking to each asset's detail page)
  rather than only changing the `[View assets from this connection →]`
  link's filter.
- **List-view "Errors" column and sort order.** design.md §4.1 shows an
  Errors count per row (e.g. legacy-pg: 3) without defining what's
  counted. Modeled as `consecutive_failure_count` (consecutive failed/
  partial-failure runs ending at the most recent attempt) — the number
  that best answers "how many times in a row has this been broken."
  Default sort is worst-status-first as design.md's prose states
  (failed → stale → never → ok), applied within each Data Plane group;
  the wireframe's own example ordering (OK, STALE, FAIL) isn't actually
  sorted that way, but the prose is treated as the requirement, the ASCII
  wireframe as illustrative only.
- **Owner-field editability** (design.md §6, item 1 — flagged by Designer
  as an open spec conflict between the PO's cut-list and BA's AC-3, not
  resolved as of this writing). Built read-only with provenance display
  throughout, per design.md's own instruction ("build read-only first;
  edit control is additive once resolved, not a blocker"). No edit
  affordance anywhere in this UI.
- **`?` help control in the top nav.** design.md lists it in the nav
  layout without specifying behavior. Implemented as a static tooltip
  (title attribute) explaining what the search box matches on, rather
  than linking to an external/placeholder URL that would imply a real
  help destination that doesn't exist yet.
- **Freshness badge wording for `partial_failure`.** AC-5 gives exact
  hover-detail wording for a `failed` latest attempt ("last successful
  scrape: <timestamp>, most recent attempt failed"). `partial_failure` is
  treated identically for badge kind (`scrape_issue`) but with wording
  adjusted to "most recent attempt partially failed" so the two failure
  modes stay distinguishable in the tooltip.
