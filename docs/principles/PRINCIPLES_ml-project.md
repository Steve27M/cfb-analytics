# ML Engineering Principles — A Cited Working Checklist

The distilled discipline behind this template's non-negotiables. Each item is a rule
you can act on, with a chapter/section citation so you can go read the source. Grouped
by project phase. Use it as a pre-flight checklist, not a textbook.

Sources:
- **Designing ML Systems** — Chip Huyen (O'Reilly)
- **ML Design Patterns** — Lakshmanan, Robinson & Munn (O'Reilly); patterns numbered 1–30
- **Hands-On ML** — Géron, 2nd ed. (O'Reilly)
- **Building ML Pipelines** — Hapke & Nelson (O'Reilly)
- **Practical MLOps** — Gift & Deza (O'Reilly)
- **Hands-On Unsupervised Learning** — Patel (O'Reilly)

---

## 1. Data

- **Set the test set aside immediately, before any EDA.** Your brain overfits to
  patterns it sees and silently selects a model to match them — data snooping bias —
  yielding over-optimistic generalization estimates. *(Hands-On ML, ch. 2 "Create a Test Set")*
- **Treat data quality as four explicit dimensions:** accuracy (typos, dupes,
  mislabels), completeness (all classes + varied representations present), consistency
  (units/formats/labels standardized), timeliness (event-time vs. ingest-time tracked).
  *(ML Design Patterns, ch. 1 "Data Quality")*
- **Validate data before the expensive steps.** Run a schema + statistics check at the
  pipeline entrance to catch anomalies, schema changes, and drift — "garbage in" should
  fail fast, not after a training run. *(Building ML Pipelines, ch. 4 "Why Data Validation?")*
- **Auto-generate a schema** from summary statistics and validate every new batch
  against it. *(Building ML Pipelines, ch. 4 "Generating a Schema")*
- **Lint datasets before they hit the platform** — flag zero-count columns, `Unnamed`
  columns, embedded carriage returns. A 30-line CLI catches a class of silent failures.
  *(Practical MLOps, ch. 11 "Creating a Dataset Linter")*
- **Check for biased / nonrepresentative data (sampling bias)** by slicing statistics
  across categorical features and comparing to the real-world distribution.
  *(Building ML Pipelines, ch. 4 "Biased Datasets"; Hands-On ML, ch. 1)*
- **Do unsupervised EDA first.** Dimensionality reduction + clustering surface the
  data's structure, show which features actually vary, and group anomalies for
  inspection before you commit to a supervised frame.
  *(Hands-On Unsupervised Learning, ch. 1 & 3)*

## 2. Splitting (the part everyone gets wrong)

- **Split deterministically by a hash of an immutable ID**, not by random shuffle, so a
  row's set assignment is stable across data refreshes and never migrates train↔test.
  *(ML Design Patterns, DP 22 "Repeatable Splitting"; Hands-On ML, ch. 2)*
- **Split the hash on a well-distributed column that captures row correlation but is NOT
  a model input**, with enough unique values (≈3–5× the modulo) and labels well
  distributed across splits. *(ML Design Patterns, DP 22)*
- **Split time-correlated data by time, not at random** — train on earlier periods, hold
  out the latest. Random splitting leaks future information into training.
  *(Designing ML Systems, ch. 5 "Data Leakage — Common Causes")*
- **Use stratified sampling** so split proportions mirror the full dataset, especially
  for rare classes that random sampling can drop entirely.
  *(Hands-On ML, ch. 2; Designing ML Systems, ch. 4 "Stratified Sampling")*
- **Dedupe BEFORE splitting; oversample AFTER.** Otherwise the same (or near-duplicate)
  sample lands in both train and test, inflating your numbers.
  *(Designing ML Systems, ch. 5 "Common Causes — duplication / resampling")*
- **Guard against group leakage:** strongly correlated examples (two scans of one
  patient, multiple rows per entity) must not straddle the split.
  *(Designing ML Systems, ch. 5 "Group leakage")*

## 3. Features

- **No feature may use the target or predict-time-unavailable data.** Post-outcome
  fields, future-dated values, and process artifacts (a label correlated with the
  capture device) are leakage. *(Designing ML Systems, ch. 5 "Data Leakage")*
- **Compute scaling/imputation statistics on the TRAIN split only**, then apply to
  val/test. Scaling before splitting, or imputing test with test-derived stats, leaks.
  *(Designing ML Systems, ch. 5 "Common Causes — scaling/filling before splitting")*
- **Detect leakage empirically:** measure each feature's correlation / predictive power
  with the target and investigate anything unusually high; run ablations — a feature
  whose removal sharply drops performance, or whose addition suddenly boosts it, may
  carry leaked label info. *(Designing ML Systems, ch. 5 "Detecting Data Leakage")*
- **Capture transformations WITH the model** (separate raw inputs from derived features;
  keep scaling constants, vocabularies, embedding tables inside the artifact) so the
  exact same preprocessing runs at serve time. This is the primary defense against
  training-serving skew. *(ML Design Patterns, DP 21 "Transform"; Building ML Pipelines, ch. 5)*
- **Share features through a feature store** so they're computed once, reused across
  projects, and kept consistent between training (batch) and serving (online).
  *(ML Design Patterns, DP 26 "Feature Store"; Designing ML Systems, ch. 10; Practical MLOps, ch. 5)*

## 4. Training

- **Fix and record all randomness** (seed=42 convention: `random_state`, framework
  seeds) plus data and artifacts — ML training is nondeterministic and otherwise
  non-reproducible. *(ML Design Patterns, ch. 1 "Reproducibility")*
- **Choose the performance measure up front**, tied to the business objective, before
  modeling. *(Hands-On ML, ch. 2 "Select a Performance Measure")*
- **Select models and tune hyperparameters with cross-validation on the training set
  only** — never the test set; prefer repeated CV over a single small validation set.
  *(Hands-On ML, ch. 2 "Cross-Validation"; ch. 1 "Hyperparameter Tuning and Model Selection")*
- **For class imbalance, rebalance for training (downsample/upsample/weight) but keep the
  test set at the true class distribution** so metrics reflect reality. Never evaluate on
  resampled data — that overfits to the resampled distribution.
  *(ML Design Patterns, DP 10 "Rebalancing"; Designing ML Systems, ch. 4 "Resampling")*
- **Hold out a train-dev set when training data differs from production data** to
  separate overfitting from data mismatch: poor on train-dev ⇒ overfitting; good on
  train-dev but poor on validation ⇒ data mismatch. *(Hands-On ML, ch. 1 "Data Mismatch")*
- **Useful overfitting is a deliberate exception** (distillation, modeling a known
  function) — not a default. Generalization on held-out data is the goal.
  *(ML Design Patterns, DP 11 "Useful Overfitting")*
- **Log every run** to experiment tracking: loss curves per split, the metrics you care
  about, sample/prediction/label triples, speed, and system metrics; version code AND
  data (data hash, git SHA). *(Designing ML Systems, ch. 6 "Experiment Tracking and Versioning")*

## 5. Evaluation

- **Always compare to baselines, never a metric in isolation:** random (uniform +
  label-distribution), zero-rule/majority-class, a simple heuristic, human, and the
  existing solution. *(Designing ML Systems, ch. 6 "Baselines"; ML Design Patterns, DP 28 "Heuristic Benchmark")*
- **Never use accuracy on imbalanced data** — it's dominated by the majority class. Read
  the confusion matrix; report precision/recall/F1 and pick the decision threshold
  deliberately from the score distribution. *(ML Design Patterns, DP 10; Hands-On ML, ch. 3)*
- **Prefer the PR curve over ROC/AUC when the positive class is rare** — ROC/AUC looks
  deceptively good under heavy imbalance. *(Hands-On ML, ch. 3 "The ROC Curve")*
- **Slice-based evaluation, not just aggregate.** Find critical slices via error analysis
  and slice finders; a model with higher overall accuracy can be worse on key subgroups
  (Simpson's paradox / hidden stratification). Evaluate through a fairness lens across
  subgroups. *(Designing ML Systems, ch. 6 "Slice-based evaluation"; ML Design Patterns, DP 30 "Fairness Lens"; Building ML Pipelines, ch. 7)*
- **Run behavioral tests beyond aggregate metrics:**
  - *Perturbation* — add noise/clip the test set; prefer the model that holds up, since
    prod inputs are noisier than dev inputs.
  - *Invariance* — changing a sensitive/irrelevant input must not change the output
    (better: exclude it).
  - *Directional expectation* — a known monotone input must move the prediction the
    right way. *(Designing ML Systems, ch. 6 "Evaluation Methods")*
- **Check calibration** when downstream consumers need true probabilities — a "70%"
  prediction should be right ~70% of the time; plot predicted-vs-actual frequency and
  calibrate (e.g. Platt scaling). *(Designing ML Systems, ch. 6 "Model calibration")*
- **Evaluate on the test set exactly once**, calling `transform` (not `fit_transform`),
  and report a confidence interval on generalization error. Then resist tuning to it —
  heavily tuned systems score slightly worse on test and further tweaks won't generalize.
  *(Hands-On ML, ch. 2 "Evaluate Your System on the Test Set")*
- **Provide explainable predictions** (which features drove the output) — accuracy says
  nothing about *why*; needed for trust in high-stakes domains.
  *(ML Design Patterns, DP 29 "Explainable Predictions"; Practical MLOps, ch. 5)*
- **Write a model card** for each blessed version: intended use, training-data window +
  hash, aggregate AND per-segment metrics, known failure modes; regenerate it whenever
  the model changes. *(Designing ML Systems, ch. 11 "Create model cards"; Building ML Pipelines, ch. 7)*

## 6. Deployment

- **Build the foundation bottom-up:** DevOps → DataOps/Data Engineering → Platform
  Automation → MLOps. You can't deliver ML value until each lower layer is automated.
  *(Practical MLOps, ch. 1 "MLOps Hierarchy of Needs")*
- **Make CI the floor:** the same `make install / lint / test` (or `./scripts/check.sh`)
  commands run locally and in CI. *(Practical MLOps, ch. 1 "Implementing DevOps")*
- **Export the model as a stateless serving function** (output depends only on inputs;
  weights are constants) so it scales horizontally.
  *(ML Design Patterns, DP 16 "Stateless Serving Function")*
- **Deploy preprocessing + model as ONE artifact** so inference applies identical
  transforms — no skew. *(Building ML Pipelines, ch. 5 "Deploying ... as One Artifact")*
- **Pin exact dependency versions** — an unpinned runtime can pass accuracy/drift checks
  yet ship a broken model. *(Practical MLOps, ch. 4 "Automated checks")*
- **Roll out with canary / blue-green** and shift traffic progressively so you can roll
  back instantly. *(Practical MLOps, ch. 4 "Controlled Rollout of Models")*
- **Test the whole serving path**, not just accuracy — route, port, payload parsing,
  runtime, response shape. A boolean silently becoming a string passes canary with zero
  errors yet breaks the model. *(Practical MLOps, ch. 4 "Testing Techniques for Model Deployment")*
- **Gate the push.** Only bless and deploy a candidate that beats the latest blessed model
  on a defined metric threshold — otherwise a worse model auto-deploys.
  *(Building ML Pipelines, ch. 7 "Validation in the Evaluator Component")*
- **Version every model as a new endpoint** to preserve backward compatibility and enable
  comparison / split testing / rollback. *(ML Design Patterns, DP 27 "Model Versioning")*

## 7. Monitoring

- **Assume the world drifts.** Know the three shift types: covariate shift (P(X) changes,
  P(Y|X) same), label shift (P(Y) changes, P(X|Y) same), concept drift (P(Y|X) changes —
  "same input, different output," often seasonal). *(Designing ML Systems, ch. 8 "Types of Data Distribution Shifts")*
- **Detect shift with statistics, not vibes.** When labels exist, monitor accuracy-related
  metrics; when they don't, monitor input/prediction distributions with two-sample tests
  (e.g. KS for 1-D), reducing dimensionality first since these tests are weak in high-D.
  *(Designing ML Systems, ch. 8 "Detecting Data Distribution Shifts")*
- **Compare new batches to the training distribution** with skew/drift comparators
  (L-infinity over feature stats) against a threshold; alert and trigger retraining
  before accuracy degrades. *(Building ML Pipelines, ch. 4; Practical MLOps, ch. 6)*
- **Monitor four ML artifacts plus operational metrics:** accuracy-related metrics,
  predictions, features, and raw inputs — alongside latency/throughput/uptime/resource
  use. ML systems fail silently. *(Designing ML Systems, ch. 8 "ML-Specific Metrics")*
- **Continuously evaluate the DEPLOYED model** on live data — deployment is not the end of
  the lifecycle; it's the start of decay. *(ML Design Patterns, DP 18 "Continued Model Evaluation")*
- **Use anomaly/novelty detection on inputs** to catch out-of-distribution data and
  outliers; build a distribution over inputs to quantify how far current data is from
  training data and auto-trigger retraining when they diverge.
  *(Hands-On Unsupervised Learning, ch. 1 & 4)*
- **Use Python `logging`, not `print()`** — respect levels (debug<info<warning<error<
  critical) and ship logs to an observability sink feeding dashboards + alerts.
  *(Practical MLOps, ch. 6 "Logging in Python")*
- **Retrain on a schedule and keep an audit trail** (data, training metadata, deploys) —
  a model built once goes stale as data, customers, and code change.
  *(Practical MLOps, ch. 1 "MLOps Feedback Loop")*

---

### The one-paragraph version
Seal the test set on day one and split deterministically by hash. Let nothing from the
future or the target leak into a feature; fit transforms on train and ship them inside
the model. Beat real baselines on a metric that survives class imbalance, and never trust
an aggregate number until you've sliced it. Make every run reproducible (seed, data hash,
git SHA) and every deploy gated, versioned, and rollback-able. Then watch for drift,
because the only certainty in production is that the distribution moves.
