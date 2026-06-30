---
description: Pre-merge gate -- parse, lint, coverage, and a no-write test build before merge.
---

Run the full pre-merge gate and report a GO / NO-GO. Do NOT run a real
`dbt build` against prod and do NOT `--full-refresh`. Validate, then summarize.

1. `dbt parse` — compile the project and validate the DAG. Any parse error =
   immediate NO-GO (broken ref/source, missing model).
2. `sqlfluff lint models/` (or the changed models). Report violations.
3. Coverage: call the `list_uncovered_models` tool. Every changed model must have
   a `description` + at least a `not_null`/`unique` or `relationships` test on its
   key. List any uncovered model — that's a NO-GO.
4. Grain: call `check_grain_declared` on each changed model. A model with no
   declared grain (header comment or YAML) is a NO-GO.
5. Source freshness: if a source YAML changed, run `dbt source freshness` and
   report warn/error.
6. Test the changed subgraph without writing data:
   `dbt build --select state:modified+ --defer --state ./prod-manifest --empty`
   (the `--empty` runs models with a 0-row limit to validate SQL + tests cheaply).
   Report failures.
7. Confirm no mart contains `SELECT *` and no model selects a raw table directly
   (grep the changed files; the hook also enforces this).

Output a single **GO / NO-GO** with the specific blockers if NO-GO. Each blocker
names the model and the failed rule.

Argument (optional): $ARGUMENTS = a dbt selection (default: `state:modified+`).
