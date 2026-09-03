# Post-MVP roadmap: `relevance/`

Status: not built, not scheduled — a deliberate deferral, recorded here per
architecture.md §8 ("write up the post-MVP roadmap note... explicitly not
built now"). Nothing in this note should be read as work in progress.

## What MVP ships instead

MVP's relevance layer is entirely lexical: BM25 keyword matching (FE2's
base OpenSearch index) plus this directory's field-weight boosting
(`name` > `description` > `tags`, `boost_profile.py`) and a usage-derived
popularity blend (`popularity.py`). No embeddings, no vector index, no
notion of semantic similarity between entities. See `INTERFACE.md` for how
that plugs into FE2's query builder.

## Why semantic search / similar-table recommendations are deferred

architecture.md §8 states the reason directly: **MVP's metadata schema may
not yet have populated `description` fields to embed.** This isn't a
hypothetical risk — it follows from spec.md's own acceptance criteria:

- AC-2 (schema view) explicitly allows `description` to be absent
  ("if none was captured, the field shows 'no description'") — Postgres
  table/column comments and S3 object tags are optional, source-asserted,
  and manual editing is cut from MVP entirely (spec.md's "Cut from MVP"
  list, and AC-5's "MVP is read-only" note for the analogous `owner`
  field).
- The MVP demo sources (spec.md's Success Criteria) are a demo Postgres
  database and a demo S3 bucket, neither guaranteed to have rich, curated
  table/column descriptions written by anyone.

Embedding a field that is frequently empty or absent produces two bad
outcomes, not just a weak one: (1) many entities embed to a
near-meaningless vector derived from ~nothing, actively hurting
similarity ranking rather than merely not helping it, and (2) it's easy to
mistake "search seems to work on the demo data we happened to type
descriptions into" for a validated feature, when it's actually validated
against hand-populated fixtures that don't represent real customer data at
onboarding time. Building this before descriptions are reliably populated
would be optimizing (and demoing) against the wrong distribution of input
data.

## What "later" looks like, concretely

Once description fields are reliably populated — plausibly once dbt/
Airflow lineage connectors (already deferred past MVP per spec.md) or a
future manual-curation feature (also deferred) exist and give tables a
real reason to accumulate descriptions — the natural next steps are:

1. **Embedding pipeline.** Batch-embed `name` + `description` (+ maybe
   `tags`) per entity using a sentence-embedding model, triggered off the
   same fan-out path that already denormalizes entities into OpenSearch
   (FE1's `control-plane/workers/fanout/`) so embeddings stay current
   without a separate sync mechanism. Model choice is an open question
   deliberately not prejudged here (self-hostable model vs. hosted
   embeddings API is itself a build-vs-buy call that interacts with the
   airgapped-later requirement in decisions.md — a hosted-API-only
   embedding step would be a regression for that future target, so a
   self-hostable model is the likely direction, but this is exactly the
   kind of call that should be made when the feature is actually
   scheduled, not speculatively now).
2. **Vector index.** OpenSearch's k-NN plugin (keeps everything in one
   search engine rather than adding a dedicated vector database — same
   Apache-2.0/self-host reasoning that chose OpenSearch over Elasticsearch
   in architecture.md §4 applies here) storing the embedding alongside the
   existing lexical fields on the same document, so a query can blend
   lexical (BM25 + this directory's boost profile) and semantic (k-NN)
   scores rather than replacing one with the other — semantic search
   augments keyword search for this product, it doesn't replace it (per
   spec.md's Dana/Eli personas, both of whom search by "business keyword,"
   not natural-language question).
3. **"Similar tables" recommendation.** A nearest-neighbors query against
   the same vector index, surfaced on the table detail page (spec.md's
   Story 2/AC-2 scope) as "similar tables" — directly useful for Dana's
   "is there already a similar table I should use instead of re-deriving
   it" scenario called out in spec.md's persona rationale, which MVP does
   not address today.
4. **Query-time hook, same shape as today's.** The integration point would
   plug into the same call-out hook this directory already defines
   (`apply_relevance_boost` in `hook.py`) — extended with a
   `query_embedding` (or similar) parameter — rather than a parallel
   mechanism, keeping FE2's query builder integration surface singular.

## Explicitly not proposing here

- A specific embedding model/provider — premature before description-field
  population is validated as good enough to embed meaningfully.
- A timeline — this is a roadmap note, not a scheduled task; scheduling it
  is a product/tech-lead call once MVP's real description-field fill rate
  is known from actual customer data, not demo fixtures.
