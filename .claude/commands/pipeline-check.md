---
description: Pre-run gate -- runs DQ tests, freshness, and schema-contract checks; reports go/no-go before a run or merge.
---

Run the full pipeline gate and report a GO / NO-GO. Do NOT run a production
materialization or backfill; stop after validation and summarize.

1. Run `./scripts/check.sh` (lint, types, `dbt build --target dev`, freshness).
   Report any failures verbatim.
2. Call the `run_dq_checks` tool on the changed/target models. Report any
   failing not_null / unique / accepted_values / relationships tests. Confirm
   every NEW or CHANGED model has DQ tests on its grain key — flag any that
   don't (a model without tests is a NO-GO).
3. Call `check_freshness` on the served (gold) tables in scope. Any stale table
   (older than its SLA) is a blocker. Report the lag.
4. Call `check_schema_contract` on each changed model: confirm the output
   columns/types match the declared contract in its `.yml`. Any drift not
   captured by a versioned contract change is a NO-GO.
5. Confirm the change is idempotent: incremental models declare a `unique_key`
   / partition predicate, and no `TRUNCATE` / unfiltered `DELETE` is introduced
   (grep the diff). Confirm no writes target raw/source/prod.
6. Confirm no PII columns are printed/logged in the changed code (grep the diff
   for obvious identifier columns in log/print statements).
7. Output a single GO / NO-GO with the specific blockers if NO-GO.

Argument (optional): $ARGUMENTS = dbt selector for scope (default: state:modified+).
