---
name: adding-or-changing-a-dbt-model
description: >
  Use when adding or modifying a dbt model, fact, dimension, staging model, or
  snapshot in this project. Triggers: "add a model", "build a fact/dim table",
  "stage this source", "make it incremental", "add a mart", "model this data".
  Do NOT use for exploratory querying (just call query_readonly read-only), for
  raw ingestion (out of dbt's scope here), or for BI/dashboard changes.
---

# Adding or Changing a dbt Model

## Procedure
1. **Declare the grain first.** State, in one line, what a single row of this model
   represents (e.g. "one row per order per day"). Put it in a header comment AND
   the model's YAML `description`. If you can't state the grain, stop — you're not
   ready to write the model. (FDE ch.8; MED ch.3)
2. **Place it in the right layer.**
   - New source field/entity → `stg_<source>__<entity>.sql`: rename + recast only,
     1:1 with the source, `{{ source(...) }}`, materialized view. No joins/aggs.
   - Business construct / joins / dedup → `int_<entity>_<verb>.sql`, built from
     `{{ ref('stg_...') }}`. Ephemeral or view.
   - Business-facing fact/dim → `fct_<process>.sql` / `dim_<entity>.sql`, built from
     `{{ ref(...) }}`, materialized table, columns enumerated (no `SELECT *`).
3. **Reference, don't reach.** Use `{{ ref() }}` for every upstream model; `{{ source() }}`
   only inside staging. Open the model with import CTEs, then transform CTEs, final SELECT.
4. **For a fact/dim:** build dims before the fact; mint surrogate keys in the mart;
   `LEFT JOIN` fact→dim with a `COALESCE` default for unmatched keys; add a placeholder
   row strategy for early-arriving facts. (MED ch.3)
5. **Choose the materialization on purpose** (see PRINCIPLES.md §3): view (default/staging),
   table (marts/heavy read), ephemeral (lightweight glue), incremental (large + frequently
   updated). Write down why.
6. **If incremental:** set `unique_key` + `incremental_strategy: merge`; wrap the new-rows
   filter in `{% if is_incremental() %} where _loaded_at >= (select max(_loaded_at) from
   {{ this }}) {% endif %}`. It must be a true upsert. (AE ch.5)
7. **Add tests + docs in the layer YAML:** `description` on the model and key columns;
   `not_null` + `unique` on the key, `relationships` on FKs; a singular test in `tests/`
   for any rule the built-ins can't express. (AE ch.4)
8. **SCD2 → use a snapshot** in `snapshots/` (strategy `timestamp` preferred), not a
   hand-rolled mart. (AE ch.5)
9. **Lint + validate:** `sqlfluff fix`, then `dbt parse`, then `/model-check`.

## Guardrails
- Grain is declared or you don't ship. One fact row = the declared grain.
- Staging renames/recasts only — no joins, no aggregations, no business logic.
- `source()` lives only in staging; marts are built from `ref()`, never raw tables.
- No `SELECT *` in marts (allowed only in import CTEs). The hook will block both raw
  selects in models and `*` in marts.
- Never run `--full-refresh` against prod; never write to raw/source/bronze schemas.
- Incremental models reproduce under `--full-refresh` (idempotent). Validate before trusting.

## Verification
- `dbt parse` is clean; lineage shows the model wired via `ref()`/`source()`.
- `list_uncovered_models` does NOT list this model (has docs + tests).
- `check_grain_declared` passes for this model.
- For incremental: a `--full-refresh` build and an incremental build agree on row counts
  and key values for a controlled window.
- `sqlfluff lint` clean; `/model-check` returns GO.
