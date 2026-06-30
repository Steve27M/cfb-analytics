---
name: building-or-changing-a-pipeline-model
description: >
  Use when building or changing a pipeline model, source, or asset in this
  medallion ELT project. Triggers: "add a silver/gold model", "build the marts
  table", "change the transformation", "add a new source", "set up an
  incremental model", "write a backfill". Do NOT use for read-only exploration
  (just query read-only via the MCP tool) or for pure orchestration scheduling
  changes with no model logic (edit dagster/ directly).
---

# Building or Changing a Pipeline Model

Process knowledge for adding/altering a model without breaking the
non-negotiables. Work the steps in order; each gates the next.

## Procedure
1. **Contract first.** Before writing SQL, write/extend the model's `.yml`:
   declare the grain, output columns + types, and tests (not_null + unique on
   the grain key; accepted_values / relationships where they apply). The
   contract is the interface; the SQL conforms to it. (PRINCIPLES §2, §3)
2. **Pick the layer and respect it.** bronze = raw landing only (append, no
   transform); silver = clean/type/dedup to one grain; gold = business mart.
   Don't smuggle transformations into bronze.
3. **Read the analogous model first** and match its patterns (naming,
   incremental config, ref() usage). Minimal diffs.
4. **Make writes idempotent.** If incremental, declare a `unique_key` /
   partition predicate so a re-run merges, not appends. No `TRUNCATE`, no
   unfiltered `DELETE`. Re-running the same window must be a no-op on row counts.
   (PRINCIPLES §1, §2)
5. **Dry-run before executing.** Call `dry_run_model` (compiles + plans, no
   write) and inspect the plan. Only run against `--target dev`. Never against
   prod from the skill.
6. **Run DQ checks.** Call `run_dq_checks` on the model. Fix failures before
   proceeding — a failing check should act as a circuit breaker, not a warning.
   (PRINCIPLES §3)
7. **Verify freshness + volume** for served tables via `check_freshness` and
   `profile_table` (row count in expected band, null rates sane). (PRINCIPLES §3)
8. **Plan the backfill.** If this changes historical output, state the backfill
   window and confirm it's safe to re-run (idempotent). Use the orchestrator's
   backfill, not ad-hoc deletes. (PRINCIPLES §1, §4)
9. **Update lineage/docs.** Ensure refs are explicit so field-level lineage
   stays intact; document the model's purpose + owner + SLA. (PRINCIPLES §3, §6)

## Guardrails
- Never write to source/prod/raw; bronze is immutable. (CLAUDE.md)
- Every new/changed model ships with DQ tests — no exceptions.
- No PII columns in print/log statements; mask or omit.
- A schema change is a versioned contract change, not a silent edit. If the
  output columns/types move, update the `.yml` and call it out.
- Don't bake nondeterminism (`current_timestamp()`, unordered LIMIT) into
  business logic — it breaks reproducibility.

## Verification
- `dry_run_model` compiles clean and the plan matches intent.
- `run_dq_checks` is green; not_null + unique hold on the grain key.
- `check_schema_contract` shows no undeclared drift.
- Re-running the model for the same partition produces identical row counts
  (idempotency holds).
- `check_freshness` is within SLA for any served table touched.
