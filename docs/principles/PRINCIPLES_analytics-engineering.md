# Analytics Engineering Principles

A working checklist distilled from three references, each item cited so it's auditable:
- **AE** = *Analytics Engineering with SQL and dbt* (Machado/Russa)
- **MED** = *Building Medallion Architectures* (Strengholt)
- **FDE** = *Fundamentals of Data Engineering* (Reis/Housley)

This is the "why" behind CLAUDE.md's non-negotiables. When a model is in question, walk this list.

---

## 1. Project Structure & Modularity

- [ ] **Three layers, one direction.** Model in staging → intermediate → marts; dependencies flow
  one way. `stg_` 1:1 with sources, `int_` business constructs, `fct_`/`dim_` business entities.
  One model per file. *(AE, ch.2 — Building Modular Data Models; ch.4 — Structure of a dbt Project)*
- [ ] **Staging does rename/recast only.** No joins, no aggregations in `stg_` models — joining or
  aggregating there "limit[s] access to valuable source data." Typically materialized as views.
  *(AE, ch.2 — Building Modular Data Models)*
- [ ] **`ref()` everywhere downstream; `source()` only in staging.** `{{ ref() }}` lets dbt "detect
  and establish dependencies" and build the DAG. Referencing raw tables directly "hinders
  flexibility and modularity." `{{ source() }}` is used "sparingly, typically limited to the
  initial selection of raw data." *(AE, ch.2 — Referencing data models)*
- [ ] **Import CTEs at the top.** Every model opens with import CTEs (`with x as (select * from
  {{ ref('...') }})`) before transform logic. *(AE, ch.2)*
- [ ] **DRY the intermediate layer.** If an `int_` model is referenced by many downstreams, that's "a
  design issue" — promote shared logic to a macro. Marts should avoid excessive joins; if a mart
  needs many joins, "rethink the intermediate layer." *(AE, ch.2 — Intermediate / Mart models)*
- [ ] **Treat transformations like software.** Version control (incl. data version control), CI/CD,
  configuration as code, testing — DataOps automation "has a similar framework... to DevOps."
  *(FDE, ch.2 — DataOps)*

## 2. Modeling — Dimensional + Medallion

- [ ] **Declare the grain first, before facts or dims.** Define "the level of detail in the fact and
  dimension tables" before loading. "Each row of a fact table should represent the grain of the
  data" and "facts should be at the lowest grain possible." Put the declared grain in a header
  comment and the YAML description. *(FDE, ch.8 — Kimball; MED, ch.3 — Star Schema Design)*
- [ ] **4-step dimensional design.** Identify business processes → declare grain → identify dimensions
  → identify facts. The end-to-end use case derives dims + facts in exactly this order. *(AE, ch.6 —
  Analytical Data Modeling; FDE, ch.8)*
- [ ] **Star schema shape.** Central fact (numeric measures + dimension FKs) surrounded by descriptive
  dimensions. Facts "narrow and long," dims "wide and short." Facts reference only dimensions —
  "fact tables don't reference other fact tables." *(FDE, ch.8 — Kimball)*
- [ ] **Build dims before facts; mint surrogate keys in the mart.** "Create the dimension tables
  before the fact tables because fact tables rely on dimension tables for their surrogate keys."
  Surrogate keys are minted here, not earlier — "surrogate keys do not typically belong in the
  Silver layer." Handle early-arriving facts with placeholder dimension rows. *(MED, ch.3 — Star
  Schema; ch.3 — Silver Layer)*
- [ ] **Medallion = single responsibility per layer.** Bronze: raw, immutable, "original structure
  without any transformation," no business logic. Silver: "refines, cleanses, and standardizes" —
  dedup, conform, quality checks; still granular, source-aligned (NOT yet integrated across
  sources). Gold: "aggregating, summarizing, and enriching" — business rules, star schema,
  read-optimized. *(MED, ch.3 — Bronze / Silver / Gold Layer)*
- [ ] **Bronze forbids business logic.** Only sanctioned mutations are metadata tagging and PII
  masking — "data... may either be completely raw or slightly augmented." Bronze is "not intended
  for historization... as a fully processed SCD2 table." *(MED, ch.3 — Bronze Layer)*
- [ ] **Conformed dimensions are shared across facts.** Reuse `dim_date`, `dim_customer` etc. across
  multiple fact tables rather than re-deriving. *(AE, ch.2; MED, ch.3)*
- [ ] **Pick the modeling style per need.** Kimball star for BI-facing marts (bottom-up, accepts
  denormalization). 3NF / Data Vault for an integrated/harmonized silver when source schemas churn
  ("resilience to change"). One-Big-Table when joins hurt or a flat table feeds ML. *(FDE, ch.8 —
  Inmon/Kimball/Data Vault; MED, ch.3 — 3NF and Data Vault / One Big Table)*

## 3. Materializations & Incrementality

- [ ] **Choose materialization deliberately:**
  - **view** — stores only the query, cheap/timely, slower at query time. Default; staging default.
  - **table** — physically stored, slow to build, fast to query. Use in marts / heavy-read models.
  - **ephemeral** — inlined as a CTE downstream; lightweight glue. Can't be queried directly;
    overuse complicates debugging and inflates downstream build time.
  - **incremental** — process only new/changed rows; for large, frequently-updated tables.
  - **materialized view** — precomputed + auto-refreshed by the platform; convenient but "less
    fine-grained control over your incremental logic." *(AE, ch.5 — Model Materializations)*
- [ ] **Incremental = idempotent upsert.** Set `unique_key` + `incremental_strategy: merge` so matched
  rows update and unmatched insert (the dedup/upsert mechanism). Guard new rows with
  `{% if is_incremental() %} where _loaded_at >= (select max(_loaded_at) from {{ this }}) {% endif %}`.
  *(AE, ch.5 — Incremental Models)*
- [ ] **Re-running yields the same result.** "In an idempotent system, the outcome of processing a
  message once is identical to the outcome of processing it multiple times." A `--full-refresh` must
  reproduce the incremental table. Validate by running incremental + full-refresh in parallel for a
  few days. *(FDE, ch.7 — idempotency; AE, ch.5)*
- [ ] **SCD2 via snapshots.** Use dbt snapshots (in `snapshots/`, separate from models) for Type-2
  history over mutable sources: `strategy: timestamp` (preferred) or `check` with `check_cols`. dbt
  manages `dbt_valid_from`/`dbt_valid_to`/`dbt_scd_id`. *(AE, ch.5 — Snapshots; FDE, ch.8 — SCD;
  MED, ch.3 — Slowly changing dimensions)*

## 4. Testing & Contracts

- [ ] **Generic tests on every key.** `unique`, `not_null`, `accepted_values`, `relationships`
  (referential integrity) declared in YAML under each column. At minimum: `not_null` + `unique`
  on the primary/surrogate key, `relationships` on FKs. *(AE, ch.4 — Generic tests)*
- [ ] **Singular tests for the rules built-ins can't express.** `.sql` files in `tests/` returning
  failing rows (e.g. `assert_total_payment_amount_is_positive.sql`). Use `severity: warn` to
  downgrade non-blocking checks. *(AE, ch.4 — Singular tests)*
- [ ] **Validate completeness technically at ingestion.** Row counts, checksums, hash totals, schema
  and format checks — catch integrity errors early to "prevent the propagation of inaccuracies to
  subsequent layers." Quarantine bad rows (intrusive) rather than poison downstream. *(MED, ch.3 —
  Technical Validation Checks)*
- [ ] **Fix quality at the source where possible**, not patched repeatedly downstream. *(MED, ch.3 —
  Cleaning Data Activities)*
- [ ] **Data contracts as versioned YAML under GitOps.** "A formal agreement between a data provider
  and a data consumer" covering format, quality, availability, security. Version-control contracts
  in Git; gate changes via pull-request workflows. *(MED, ch.12 — Data Contracts Using YAML Files
  and GitOps)*
- [ ] **Sources have freshness SLAs.** `loaded_at_field` + `freshness: {warn_after, error_after}`;
  run `dbt source freshness`. SLAs/SLOs function as data contracts ("99% uptime, 95% of data free
  of defects"). *(AE, ch.4 — Source freshness; FDE, ch.9 — Trust)*

## 5. Documentation & Lineage

- [ ] **Describe every model and key column.** `description:` in YAML; richer prose in `.md` doc blocks
  referenced via `{{ doc('...') }}`. *(AE, ch.4 — documentation)*
- [ ] **Generate docs + lineage from refs.** `dbt docs generate` builds the docs site with an
  auto-generated DAG — which only works if `ref()`/`source()` wiring is correct. *(AE, ch.2/ch.4 —
  Documentation)*
- [ ] **Define each metric once (semantic/metrics layer).** "A metrics layer is a tool for maintaining
  and computing business logic," meant "to solve the traditional problem of repetition and
  inconsistency." Define ARR/NPS/etc. once; downstream references reuse it. *(AE, ch.5 — dbt
  Semantic Layer; FDE, ch.9 — Semantic and Metrics Layers)*
- [ ] **Serve trust.** "Trust is the root consideration in serving data"; "a loss of trust is often a
  silent death knell." Consistent data definitions/logic + observability earn it. *(FDE, ch.9 —
  Trust / Data Products)*

## 6. CI/CD & Environments

- [ ] **Target-aware, never hardcoded prod.** Select the warehouse via `--target`; gate dev behavior
  with `target.name` (e.g. a macro limiting the dataset outside the deploy target to cut cost).
  *(AE, ch.5 — Using SQL Macros; ch.4 — Jobs and Deployment)*
- [ ] **Promote via pull request into a dedicated prod schema.** dev → `main` through a PR review/
  integration gate; production job default command is `dbt build`. *(AE, ch.4 — Jobs and Deployment)*
- [ ] **Build only what changed (slim CI).** Use state-based selection — `--select state:modified+`
  with `--defer`/`--state` against a stored prod manifest — so CI rebuilds the modified subgraph,
  not the whole project. *(AE, ch.4 — selection syntax / defer; standard dbt slim-CI pattern)*
- [ ] **`dbt build` runs models + tests in DAG order.** Prefer `build` over separate `run`+`test`;
  a failing upstream test halts dependents. *(AE, ch.4 — dbt Commands)*
- [ ] **Automated, dependency-aware orchestration.** Move off cron to an orchestrator (Airflow/
  Dagster) that understands dependencies; block manual deploys, validate the DAG before deploy.
  *(FDE, ch.2 — DataOps)*

---

### The five strongest, most load-bearing rules (if you remember nothing else)
1. Declare the grain before you write the model. *(FDE ch.8; MED ch.3)*
2. Staging renames/recasts only; `source()` lives only there; everything else uses `ref()`. *(AE ch.2)*
3. Every model documented + tested (key gets `not_null`+`unique`/`relationships`). *(AE ch.4)*
4. Incremental models are idempotent upserts (`unique_key`+`merge`, watermark filter). *(AE ch.5; FDE ch.7)*
5. No `--full-refresh` and no DML against a prod/raw target. *(MED ch.3 Bronze immutability; enforced by the hook)*
