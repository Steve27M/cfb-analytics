---
name: model-training
description: >
  Use when training, evaluating, tuning, or preparing a tabular model for deployment
  in this project. Triggers: "train the model", "build the classifier/regressor",
  "evaluate", "tune hyperparameters", "run an experiment", "is it ready to ship".
  Do NOT use for exploratory data analysis (just query read-only), data ingestion, or
  serving/API changes (edit serve/ directly).
---

# Model Training

Process knowledge for a reproducible, leakage-free training run. The deterministic
guardrails (hook, MCP tools, permissions) enforce; this skill sequences the judgment.
Cited rules live in `PRINCIPLES.md`.

## Procedure
1. **Leakage check FIRST.** Call `check_leakage` on the proposed feature set before any
   training. Stop and fix if it flags anything. *(Designing ML Systems, ch. 5)*
2. **Load the canonical split.** Confirm the split comes from `src/data/splits.py`
   (deterministic hash, seed=42). Never re-split inline. The test split stays sealed
   until step 6. *(ML Design Patterns, DP 22; Hands-On ML, ch. 2)*
3. **Fit transforms on TRAIN only**, then `.transform()` val/test. Bundle the fitted
   transform with the model so serving reuses it (no skew).
   *(ML Design Patterns, DP 21; Building ML Pipelines, ch. 5)*
4. **Establish baselines.** Compute majority/zero-rule + a simple heuristic; you will
   report the model relative to these, on an imbalance-safe metric (PR-AUC / F1, not
   bare accuracy). *(Designing ML Systems, ch. 6; ML Design Patterns, DP 10 & 28)*
5. **Dry-run, then run.** Call `train(dry_run=True)`, inspect the plan, only then
   `dry_run=False`. Tune hyperparameters with cross-validation / the validation split —
   never the test set. *(Hands-On ML, ch. 2)*
6. **Eval on the sealed test set ONCE** via `src/eval.py`. Report aggregate AND
   per-segment metrics (`slice_metrics` tool), plus error analysis and calibration.
   *(Designing ML Systems, ch. 6; ML Design Patterns, DP 30)*
7. **Write/update the model card:** intended use, data window + hash, baseline delta,
   aggregate + segment metrics, known failure modes.
   *(Designing ML Systems, ch. 11; Building ML Pipelines, ch. 7)*

## Guardrails
- Test set touched exactly once. If you need more tuning, use validation/CV only.
- Every run logs params, metrics, **data hash** (`data_hash` tool), and **git SHA** to
  MLflow. *(reproducibility — Designing ML Systems, ch. 6)*
- Dedupe before splitting; resample only after, and never evaluate on resampled data.
  *(Designing ML Systems, ch. 4 & 5)*
- Don't ship on aggregate metrics alone — minority segments hide failures.
- Flag if the training window is stale vs. the current production distribution.
- Only bless/push a candidate that beats the current blessed model on the agreed metric.
  *(Building ML Pipelines, ch. 7)*

## Verification
- Re-running with the same seed + data reproduces metrics within tolerance.
- `check_leakage` is clean; no feature uses target/post-outcome/predict-time-unavailable data.
- Baseline comparison, per-segment breakdown, and calibration are all present.
- The serving path would apply the identical bundled transform (no train/serve skew).
