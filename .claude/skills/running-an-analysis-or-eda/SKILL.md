---
name: running-an-analysis-or-eda
description: >
  Use when running an analysis, EDA, statistical test, or building a finding in
  this data-science project. Triggers: "explore the data", "run an EDA", "is this
  difference significant", "find what drives X", "build a chart/report of the
  result", "fit a model to estimate". Do NOT use for pure data ingestion/plumbing
  (edit src/ wrangling directly) or for read-only one-off lookups (just query
  read-only via the MCP tool).
---

# Running an Analysis or EDA

Process knowledge for producing a finding without breaking the non-negotiables.
Work the steps in order; each gates the next.

## Procedure
1. **State the question and scope first.** Write the question, then the target
   population, the access frame, and the sample. If the sample isn't representative
   of the target population, the conclusion is "limited, possibly misleading, or even
   wrong" -- say so up front. Name the sampling design and its biases (coverage,
   selection/self-selection, non-response, survivorship). (PRINCIPLES sec. 3)
2. **Wrangle from a read-only copy.** Load raw read-only; write cleaned output to
   `data/interim/`. Never edit `data/raw/**`. (PRINCIPLES sec. 1-2)
3. **Run the quality checks** before any analysis: granularity (what is ONE row?),
   scope (in-range / on-topic values), measurement quality (typos/units/sentinels),
   cross-feature consistency, and missingness. Decide fix-or-drop deliberately --
   imputation changes the inference. Call `profile_dataframe` to get
   nulls/dtypes/ranges/cardinality. (PRINCIPLES sec. 2)
4. **Check for sampling bias** with `check_sampling_bias`: compare the sample's
   key distributions to the known/target distribution. (PRINCIPLES sec. 3)
5. **EDA: plot, don't just summarize.** Let feature type drive the plot; read shape,
   spread, outliers, gaps; check relationships across subgroups (watch Simpson's
   paradox). Remember Anscombe -- identical summary stats can hide wildly different
   data. Work the "what next / so what" questions. (PRINCIPLES sec. 4)
6. **Validate any statistical claim.** If you claim an effect, call
   `run_significance_test`: frame the hypothesis BEFORE looking, report a confidence
   interval (not just a point estimate), use the t-distribution for small n, and
   correct for multiple comparisons. `p < 0.05` alone is not a finding. Don't shop the
   data for significance. (PRINCIPLES sec. 5)
7. **If modeling, seal the test set.** Split first and set the test aside; tune/select
   with cross-validation on TRAIN only. Call `check_leakage` -- no target-derived or
   post-outcome features; fit transforms on train; dedupe before split; split
   time-data by time. Assess on the held-out set exactly once. (PRINCIPLES sec. 6)
8. **Keep causal claims honest.** From observational data say "associated with," not
   "causes"; look for the confounder C. (PRINCIPLES sec. 7)
9. **Make the visualization honest.** Call `render_chart_lint` on each figure: bars
   from zero, area not radius, no gratuitous dual axes / 3-D, axes labeled, accessible
   color. (PRINCIPLES sec. 8)
10. **Write the "so what".** Lead with the takeaway and the action; tailor to the
    audience; cite the evidence (figure/test/cell) for every claim. (PRINCIPLES sec. 9)

## Guardrails
- Never write to `data/raw/**`; it is immutable. (CLAUDE.md)
- The test/holdout split is sealed -- never re-split to chase a score, never tune on it.
- No conclusion from un-validated statistics; report uncertainty every time.
- Correlation is not causation -- no causal verbs over observational data.
- No misleading charts. No PII in notebook outputs; strip outputs before commit.
- Seed = 42; notebooks must run top-to-bottom headless from a clean kernel.

## Verification
- `profile_dataframe` ran; granularity and null/range checks are clean or explained.
- `check_sampling_bias` shows the sample matches the target distribution (or the gap
  is stated as a caveat).
- Every claimed effect has a CI and (if multi-test) a correction; no bare `p < 0.05`.
- `check_leakage` is clean; the test set was set aside and untouched by tuning.
- `render_chart_lint` passes on every figure.
- Re-running the notebook from a clean kernel reproduces the same numbers and figures.
