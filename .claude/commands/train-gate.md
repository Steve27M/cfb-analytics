---
description: Pre-training go/no-go gate -- runs leakage, split, baseline, lint, and test checks. Validates only; does NOT start a real run.
---

Run the full pre-training gate and report **GO / NO-GO**. Do NOT start a real
training run; stop after validation and summarize. Treat any failed check as a
blocker, not a warning.

1. **Hygiene.** Run `./scripts/check.sh` (lint, types, unit tests). Report failures.
2. **Leakage.** Call the `check_leakage` MCP tool on the feature set from
   `configs/train.yaml` / `src/features/`. Report any offending columns. NO-GO if any.
   *(Designing ML Systems, ch. 5)*
3. **Split integrity.** Confirm `src/data/splits.py` is the only split source, uses a
   deterministic hash with seed=42, and that no test-split reference appears in
   training or feature code (grep `X_test`, `test_split`, `data/test/`). NO-GO if the
   test set is referenced outside `src/eval.py`. *(ML Design Patterns, DP 22; Hands-On ML, ch. 2)*
4. **Baseline declared.** Confirm the config names the baselines to beat (majority/
   zero-rule + simple heuristic) and the primary metric — and that the metric is
   imbalance-safe (not bare accuracy if classes are skewed). NO-GO if missing.
   *(Designing ML Systems, ch. 6; ML Design Patterns, DP 10 & 28)*
5. **Segments declared.** Confirm the config lists the segment columns eval will slice
   on. NO-GO if none. *(Designing ML Systems, ch. 6; ML Design Patterns, DP 30)*
6. **Dry run.** Call `train(dry_run=True)` and show the planned config (model, features,
   split, seed, logging targets). *(reproducibility — Designing ML Systems, ch. 6)*

Output a single **GO** or **NO-GO** with the specific blockers if NO-GO. On GO, remind
the operator that the real run logs params/metrics/data-hash/git-SHA to MLflow and that
the test set stays sealed until `src/eval.py` runs once.

Argument (optional): $ARGUMENTS = config path (default: `configs/train.yaml`)
