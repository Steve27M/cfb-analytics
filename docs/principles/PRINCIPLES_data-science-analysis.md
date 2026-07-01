# Data-Science / Analysis Principles — a working checklist

A digest of practices distilled from the reference library, grouped by phase. This is
the *why* behind the repo's non-negotiables. Treat each `[ ]` as a check to clear,
not prose to admire. Citations are by chapter/section (page numbers where useful) so you
can go read the source.

Sources:
- **LDS** — Lau, Gonzalez & Nolan, *Learning Data Science* (O'Reilly)
- **DSH** — Field Cady, *The Data Science Handbook* (Wiley)
- **EMDS** — Thomas Nield, *Essential Math for Data Science* (O'Reilly)
- **EMAI** — Hala Nelson, *Essential Math for AI* (O'Reilly)
- **VT** — Nathan Yau, *Visualize This* (Wiley)
- **CWD** — Carl Allchin, *Communicating with Data* (O'Reilly)
- **DPT** — John Whalen, *Design for How People Think* (O'Reilly)

The data-science lifecycle is the spine: ask a question → obtain & wrangle data →
understand the data (EDA) → model → communicate. Keep it in mind end to end.
(LDS, ch. 1 "The Stages of the Lifecycle"; DSH, ch. 2 "The Data Science Road Map")

---

## 1. Reproducibility & Project Hygiene

- [ ] **Seed every source of randomness (seed = 42).** Sampling, splits, bootstraps,
  model fits — pseudorandom number generators are deterministic given a seed, so fix it
  and your run replays exactly. (EMDS, ch. 2 "The Uniform Distribution and Pseudorandom
  Numbers" framing; convention)
- [ ] **Pin the environment.** Commit `uv.lock`; an unpinned runtime can silently change
  results. (DSH, ch. 15 "Software Engineering Best Practices")
- [ ] **Notebooks run top-to-bottom from a clean kernel.** Execute headless in CI
  (`jupyter execute`); a notebook that only works with hidden out-of-order state is not
  reproducible. (LDS, ch. 1; DSH, ch. 15.3 "Testing Code")
- [ ] **Version control the analysis** and keep logic in tested `src/` functions, not
  buried in cells. Separate reusable logic from notebook glue. (DSH, ch. 15.2 "Version
  Control and Git for Data Scientists", 15.3–15.4)
- [ ] **Raw data is read-only.** Cleaning writes a *new* artifact; never overwrite the
  source. The raw → clean transformation must be auditable and re-runnable. (LDS, ch. 8–9
  — wrangling pipelines transform copies, preserve the source file)

## 2. Data Wrangling & Quality

Quality is judged against four lenses, and the framing **scope / granularity /
faithfulness** (after Hellerstein) anchors the chapter. (LDS, ch. 9 "Quality Checks";
ch. 2 fn. 1)

- [ ] **Check quality based on scope:** are the values in range, and do they match what
  the data is *supposed* to represent? (LDS, ch. 9 "Quality Based on Scope")
- [ ] **Check quality of measurements and recorded values:** typos, impossible values,
  wrong units, sentinel codes masquerading as numbers. (LDS, ch. 9 "Quality of
  Measurements and Recorded Values"; DSH, ch. 4 "How to Identify Pathologies")
- [ ] **Check quality across related features:** do columns that should agree, agree
  (e.g., totals vs. components, start ≤ end)? (LDS, ch. 9 "Quality Across Related Features")
- [ ] **Establish the table's shape and granularity** — what does ONE row mean? Mixed
  granularity is a silent corruptor of every downstream aggregate. (LDS, ch. 8 "Table
  Shape and Granularity"; ch. 9)
- [ ] **Decide whether to fix or drop, deliberately.** Imputation and deletion both
  change the data-generating story; missingness affects later inference — "confidence
  intervals will" be wrong if you ignore it. (LDS, ch. 9 "Fixing the Data or Not",
  "Missing Values and Records")
- [ ] **Lint the dataset on the way in:** flag zero-count / `Unnamed` columns, embedded
  carriage returns, encoding mismatches before they cause silent failures. (DSH, ch. 4.2
  "How to Identify Pathologies", 4.4 "Formatting Issues")
- [ ] **Keep transforms in a pipeline** so wrangling is one reproducible flow, not a pile
  of ad-hoc edits. (LDS, ch. 9 "Piping for Transformations")

## 3. Questions, Scope & Sampling Bias

- [ ] **Turn an area of interest into an answerable question first.** "The interplay
  between asking a question and understanding the limitations of data to answer it" is
  the real first step. (LDS, ch. 1–2)
- [ ] **State the scope: target population, access frame, sample.** "If the access frame
  is not representative of the target population, then the" conclusions are limited,
  misleading, or wrong. Draw the scope diagram. (LDS, ch. 2 "Target Population, Access
  Frame, and Sample")
- [ ] **Name the sampling design and its biases.** Coverage bias (frame ≠ population),
  selection / self-selection bias, non-response, survivorship. (LDS, ch. 2 "Types of
  Bias", ch. 3 "Sampling Designs"; EMDS, ch. 3 "Populations, Samples, and Bias")
- [ ] **Watch confirmation bias** — gathering only data that supports your belief, even
  unknowingly. (EMDS, ch. 3 "Populations, Samples, and Bias")
- [ ] **Distinguish descriptive from inferential.** Summaries describe the sample;
  inference generalizes to a population you can't fully observe — and only the latter
  needs the representativeness argument. (EMDS, ch. 3 "Descriptive Versus Inferential
  Statistics")

## 4. Exploratory Data Analysis

- [ ] **Let feature type drive the plot.** Quantitative vs. qualitative (nominal/ordinal)
  determines what distribution/relationship view is honest. (LDS, ch. 10 "Feature Types",
  "The Importance of Feature Types")
- [ ] **Read distributions for shape, spread, outliers, and gaps**, not just the mean.
  (LDS, ch. 10 "What to Look For in a Distribution")
- [ ] **Read relationships across feature pairs**, including one-qualitative-one-
  quantitative and two-qualitative cases; then compare across subgroups. (LDS, ch. 10
  "What to Look For in a Relationship", "Comparisons in Multivariate Settings")
- [ ] **Work the guideline questions:** How is X distributed? How do X and Y relate? Is
  X's distribution the same across subgroups of Z? Any unusual observations? — then ask
  "what next" and "so what". (LDS, ch. 10 "Guidelines for Exploration")
- [ ] **Don't trust summary statistics alone — plot the data.** Anscombe's quartet:
  four datasets with identical means, variances, and correlation but wildly different
  shapes. "Relying on summary statistics can be dangerous." (DSH, ch. 5.13 "Anscombe's
  Quartet and the Limits of Numbers")
- [ ] **Beware Simpson's paradox / subgroup reversal.** A relationship in aggregate can
  reverse within subgroups — always check whether a finding survives the relevant slice.
  (LDS, ch. 10 "Comparisons in Multivariate Settings" — subgroup comparison discipline)

## 5. Statistical Inference (done right)

- [ ] **Report uncertainty, not just a point estimate.** A statistic from a sample has a
  sampling distribution; quantify it with a confidence interval or bootstrap, every time.
  (LDS, ch. 17 "Basics of Confidence Intervals", "Bootstrapping for Inference"; EMDS,
  ch. 3 "Confidence Intervals")
- [ ] **Know the standard error.** The standard deviation of the sample mean is σ/√n
  (Central Limit Theorem); precision grows only with the square root of sample size.
  (EMDS, ch. 3 "The Central Limit Theorem")
- [ ] **Frame a hypothesis test correctly:** state null/alternative *before* looking;
  prefer two-tailed unless direction is justified; a p-value is the probability of a
  result this extreme *under the null*, not the probability the null is true. (LDS, ch. 17
  "Basics of Hypothesis Testing"; EMDS, ch. 3 "Understanding P-Values", "Hypothesis Testing")
- [ ] **`p < 0.05` alone is not a finding.** With many variables you will find spurious
  "significance" — p-hacking and the Texas Sharpshooter fallacy (draw the target around
  the bullet hole). Set the objective first; validate on fresh data. (EMDS, ch. 3 "Big
  Data Considerations and the Texas Sharpshooter Fallacy")
- [ ] **Correct for multiple comparisons.** Run k tests and the chance of a false positive
  inflates; adjust (Bonferroni / FDR) or you are guaranteed to find noise. (DSH, ch. 19.4
  "Multiple Hypothesis Testing")
- [ ] **Use the t-distribution for small samples** (n below ~31) rather than assuming
  normal-z. (EMDS, ch. 3 "The Central Limit Theorem", "Confidence Intervals")
- [ ] **Don't data-dredge into a conclusion.** If you "examined all possible models" and
  picked the best, you must assess on data that "did not enter into any decision making."
  (LDS, ch. 18 — the donkey case study; DSH, ch. 19.3)

## 6. Modeling & Validation

- [ ] **Pick a loss function deliberately** (MAE vs. MSE change what "best" means and how
  outliers count). (LDS, ch. 4 "Choosing Loss Functions")
- [ ] **Split train/test and set the test aside.** "We set aside a portion of our" data;
  the test set is for the *final* assessment only. (LDS, ch. 16 "Train-Test Split"; DSH,
  ch. 6.3 "Training Data, Testing Data, and the Great Boogeyman of Overfitting")
- [ ] **Select models / tune with cross-validation on the training data**, never the test
  set; k-fold averages validation error across folds. (LDS, ch. 16 "Cross-Validation")
- [ ] **Name the bias–variance trade-off.** Overfitting "follows the data too closely";
  underfitting misses structure. Use regularization to control coefficient size. (LDS,
  ch. 16 "Overfitting", "Regularization", "Model Bias and Variance"; EMDS, ch. 5
  "Overfitting and Variance")
- [ ] **No leakage.** Fit scaling/imputation on train only; no feature uses the target or
  post-outcome info; dedupe before splitting; split time-correlated data by time so the
  future doesn't leak into the past. (LDS, ch. 16; DSH, ch. 6)
- [ ] **Judge fit with residuals + the right metric.** Inspect residuals for pattern;
  R² is the share of variance explained, not proof of a good model. (DSH, ch. 11.4–11.5
  "Goodness of Fit", "Correlation of Residuals"; EMDS, ch. 5 "Coefficient of Determination")
- [ ] **For classification, read the confusion matrix; trade precision vs. recall** at a
  deliberately chosen threshold — don't lean on accuracy alone. (LDS, ch. 19 "The
  Confusion Matrix", "Precision Versus Recall"; DSH, ch. 8.6–8.7)

## 7. Correlation, Causation & Confounding

- [ ] **Correlation is not causation.** Absent a controlled experiment, you "cannot
  rigorously conclude anything about causality" from observational correlation. (DSH,
  ch. 5.12 "Correlations")
- [ ] **Hunt the confounder C.** "If A and B are correlated, then neither one is causing
  the other. Instead, there is some factor C causing them both" — a good hypothesis
  generator in EDA. (DSH, ch. 5.12 — Cady's Rule of Thumb)
- [ ] **Confounding is the source of "correlation is not causation."** To claim a causal
  effect from observational data you must control for confounders (e.g., back-door
  criterion / adjustment). (EMAI, ch. 11 "Causal Modeling and the Do Calculus" — p447)
- [ ] **Write "associated with," not "causes,"** in any report built on observational
  data, and say so explicitly. (DSH, ch. 5.12; CWD, ch. 7 — be honest about the claim)

## 8. Visualization Integrity

- [ ] **Bars start at zero; encode by length / 2-D position** — the attributes humans
  decode most accurately. (CWD, ch. 3 "Bar Charts" — axis + zero baseline; ch. 1
  "Pre-Attentive Attributes" — length & 2-D position)
- [ ] **Size by area, not radius/diameter.** Doubling the diameter quadruples the area —
  a four-fold misrepresentation. Same rule for treemaps. (VT, ch. 1 "Keep Your Geometry
  in Check")
- [ ] **Choose the chart for the data and encode proportionally;** the reader has to
  *decode* your geometry, so don't distort it. (VT, ch. 1 "Design"; CWD, ch. 1
  "Communication")
- [ ] **Label axes; annotate the point.** "Without labels or an explanation, your axes
  are just there for decoration." Annotations carry the story. (VT, ch. 1 "Label Axes",
  "Telling Stories with Data")
- [ ] **Use color deliberately and accessibly.** Keep palettes minimal to lower cognitive
  load; pick sequential vs. diverging to match the data; don't rely on hue alone — design
  for color blindness. (CWD, ch. 5 "Color", "Sequential/Diverging color palettes")
- [ ] **Avoid distortion:** no 3-D for 2-D data, no gratuitous dual axes (mixed scales
  mislead), and remember size is hard to decode quantitatively. (VT, ch. 1; CWD, ch. 5
  "Multiple Axes", "Size and Shape")
- [ ] **Choose scale to reveal structure honestly** (fill the data region; consider log
  transforms; smoothing needs tuning and shouldn't manufacture a trend). (LDS, ch. 11
  "Choosing Scale to Reveal Structure", "Smoothing and Aggregating Data")

## 9. Communicating Findings

- [ ] **Lead with the "so what".** "Just sharing your findings is not enough" — state the
  single most important takeaway and the action you want. (CWD, ch. 7 "So What?")
- [ ] **Tailor to the audience.** A slide chart is simple and direct; a report studied at
  length can carry detail. Assume readers "are showing up to my graphics blindly." (VT,
  ch. 1 "Consider Your Audience"; ch. 9 "Prepare Your Readers"; CWD, ch. 9 "Tailoring
  Your Work to Specific Departments")
- [ ] **Respect cognitive load and how people read.** Use pre-attentive attributes to
  guide the eye; minimize the effort to interpret; remember the F/Z scan patterns. (CWD,
  ch. 1 "Pre-Attentive Attributes", "cognitive load"; DPT, ch. 2 "Visual Popout",
  "Unconscious Behaviors")
- [ ] **Design dashboards around purpose** — monitoring vs. understanding — with key
  contextual numbers placed where attention lands first, and a deliberate reading order.
  (CWD, ch. 7 "Methods: Dashboards", "Facilitating Understanding")
- [ ] **Document the analysis as you would code:** clear written report, reproducible,
  every figure and number traceable. (DSH, ch. 9 "Technical Communication and
  Documentation", ch. 9.3 "Written Reports")

---

### The five sharpest invariants (memorize these)
1. **Raw data is read-only; the test/holdout split is sealed** and "did not enter into
   any decision making." (LDS, ch. 8–9, 16, 18)
2. **State scope before you conclude** — target population → access frame → sample; an
   unrepresentative sample makes conclusions misleading or wrong. (LDS, ch. 2)
3. **`p < 0.05` alone is not a finding.** Report uncertainty, pre-register the question,
   correct for multiple comparisons, don't p-hack. (EMDS, ch. 3; DSH, ch. 19.4; LDS, ch. 17–18)
4. **Correlation is not causation** — find the confounder C; say "associated," not
   "causes," from observational data. (DSH, ch. 5.12; EMAI, ch. 11)
5. **Plot the data and don't mislead** — Anscombe over summaries; bars from zero, area
   not radius, axes labeled, honest scale. (DSH, ch. 5.13; VT, ch. 1; CWD, ch. 3 & 5)
