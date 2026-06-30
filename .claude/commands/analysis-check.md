---
description: Pre-share gate -- runs lint + notebook execution + a reproducibility / leakage / stats / viz-integrity checklist; reports go/no-go before sharing a result.
---

Run the full analysis gate and report a GO / NO-GO. Do NOT touch the sealed test
set, re-split data, or commit anything; stop after validation and summarize.

1. Run `./scripts/check.sh` (lint, types, pytest, headless notebook execution).
   Report any failures verbatim. A notebook that won't run top-to-bottom from a
   clean kernel is a NO-GO (not reproducible).
2. **Reproducibility.** Confirm seeds are set (42), `uv.lock` is committed, and the
   notebooks ran headless without hidden state. Flag any cell relying on out-of-order
   execution.
3. **Scope.** Confirm the analysis states target population -> access frame -> sample
   and names the sampling design + its biases. An analysis that concludes about a
   population without this is a NO-GO. (PRINCIPLES sec. 3)
4. **Stats validity.** Call `run_significance_test` for any claimed effect: confirm a
   confidence/uncertainty interval is reported, the hypothesis was framed before the
   look, and multiple comparisons are corrected if k tests were run. `p < 0.05` alone
   is NOT a finding -- flag any conclusion resting on it. (PRINCIPLES sec. 5)
5. **Leakage.** Call `check_leakage(feature_cols, target)`: no feature derives from the
   target or post-outcome info; scaling/imputation fit on train only; dedupe before
   split; time-correlated data split by time. Confirm the test set was set aside and
   not used for any tuning/selection. (PRINCIPLES sec. 6)
6. **Correlation vs causation.** Grep the report/notebook for causal language
   ("causes", "drives", "leads to", "because of") over observational data. Any
   unsupported causal claim must become "associated with" -- flag it. (PRINCIPLES sec. 7)
7. **Viz integrity.** Call `render_chart_lint` on each figure in scope: bars start at
   zero, no truncated/dual axes without justification, size encodes area not radius,
   axes labeled, color accessible. Any misleading chart is a NO-GO. (PRINCIPLES sec. 8)
8. **Evidence + so-what.** Confirm every claim in the report cites a specific figure /
   test / notebook cell, and the "so what" / takeaway is explicit. A number without
   provenance is not a finding. (PRINCIPLES sec. 9)
9. **No PII / secrets.** Confirm notebook outputs are stripped and no raw identifier
   columns or credentials appear in committed artifacts. (CLAUDE.md non-negotiable 10)
10. Output a single GO / NO-GO with the specific blockers if NO-GO.

Argument (optional): $ARGUMENTS = path/glob for the notebook(s) or report in scope
(default: everything changed in the working tree).
