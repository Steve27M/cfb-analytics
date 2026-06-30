# Build Plan — `cfb-analytics`: Polyglot College-Football Analytics Pipeline

## Context

**Goal.** A portfolio project that ingests Division-I college-football data from the
CollegeFootballData (CFBD) API into DuckDB, transforms it with dbt into a medallion +
Kimball star, **implements the statistical models and methods taught in the reference book**
(*Football Analytics with Python & R*, Eager & Erickson — applied to CFB), and renders a live
dashboard that evaluates both **the data** and **the models' accuracy**. It demonstrates
**data-engineering** and **data-science** craft, and—per an added requirement—showcases **R**
heavily alongside Python and SQL so the portfolio proves "more than just Python + SQL." The
book itself teaches every method in **both R and Python**, which the project mirrors directly.

**This plan is itself a deliverable:** it is written to `PROJECT_PLAN.md` at the root of the
new desktop repo (see Phase 0) so the design rationale ships with the code.

**Why this project (fit to `DE-Portfolio-Roadmap.md`).** It advances several *open* roadmap
items while doubling as a second strong ML repo (the role `mit-applied-data-science` plays):

| Roadmap item | This project |
|---|---|
| §4 End-to-end ELT · API ingestion · Modeling · DQ | Core of the build (CFBD → DuckDB → dbt → marts) |
| §2/§8 **SCD2** (listed as a remaining ❌ gap) | `dim_team` as SCD2 — conference / coach / SP+ rating change season-over-season |
| §8 "Write SQL? window functions, CTE chains" | Native to play-by-play EPA / success-rate / rolling-form marts |
| ML/AI half of positioning | Win-prob / spread model **with a model-accuracy dashboard** (calibration, backtest) |
| **NEW: R + Python + SQL proof** | All existing repos are Python/SQL; this adds the R claim |
| Phase 1 CI/automation, §5 BigQuery, Phase 3 case-study | **Deferred** (local-only for now) but the repo is structured to bolt them on |

**Not covered:** sports is not one of the roadmap's target *sectors* (defense/aero,
manufacturing, finance, health, energy). Treat this as a **craft + ML + polyglot showcase**,
not a sector play. Closest sector stretch = finance (model-vs-betting-line framing).

**Scope decisions already made with the user:**
- **Model:** grounded in the **book's method suite** (see "Book-grounded methods" below) — the
  **"Over Expected" residual framework** (RYOE, CPOE), **GLM/logistic**, **Poisson** (betting
  props), **PCA + clustering**, and **multilevel/mixed-effects** (shrinkage / regression-to-
  mean) — each built in **both R and Python** as the book does. Phased: book metrics + a
  game-level win-prob/spread application **first**; play-level EPA + multilevel extensions
  **second**. Multiple models, as the user requested.
- **Cloud:** **local-only for now** (GitHub Actions CI + BigQuery deferred, not designed out).
- **Languages:** **R-heavy** — cfbfastR ingest; **`lm`/`glm`/`lme4` + `tidymodels`** modeling;
  ggplot2/cfbplotR/gt viz; `renv` — wrapped in **Python orchestration**; **dbt/SQL** transforms.
- **R-in-Python:** R models run as **subprocess steps**; the **data is the contract**
  (DuckDB tables + a metrics JSON), not in-memory objects. Chosen over `rpy2` (fragile in CI)
  and `plumber` (overkill for batch).
- **Dashboard:** **Quarto static** (R + Python chunks → `docs/`, free Pages-ready) as the
  primary; **optional local Shiny** app later for the interactive demo/Loom.

---

## Data source pre-flight (§9) — GATING FIRST STEP

CFBD facts already verified (June 2026):
- **API key required** (free); register at collegefootballdata.com/key. Used via an
  `Authorization: Bearer <key>` header. Store in `.Renviron` (`CFBD_API_KEY`) and `.env` /
  GitHub Secrets — **never commit**.
- **Free tier = 1,000 API calls / month.** **Cloudflare** blocks bursty parallel requests
  (~10-min ban). → ingestion must be **bounded, throttled, and cached** (never re-pull a
  season already in bronze). This is a real design constraint, not a footnote.
- v2 API live since May 2025; `cfbfastR` (R) and `cfbd` Python client both wrap it.
- Terms page is a JS app (not server-rendered) — the user confirms the ToS checkbox language
  at key registration; the README "Data source & terms" section records the verdict.

**Verdict: GO-WITH-CONDITIONS.** Posture (mirrors the roadmap's OpenSky precedent): **gitignore
raw data**, throttle + cache calls to stay <1,000/mo, show the **attribution line**
(*"Data: CollegeFootballData.com"*) in README and on the dashboard, **bounded on-demand
collection** (no perpetual poller), key in env/secrets only.

---

## Target architecture (polyglot by layer)

```
[CFBD API]
   │  R: cfbfastR  (cfbd_* / load_cfb_pbp)   ← canonical CFB ingestion; Python `cfbd` = fallback
   ▼
DuckDB  bronze.*   (raw, immutable, append-only + lineage: pull_id / fetched_at / season)
   │  dbt (SQL)
   ▼
        silver.*   (typed, deduped, conformed team names; one grain per model)
   │  dbt (SQL) + dbt snapshot (SCD2)
   ▼
        gold.*     (Kimball star + marts)         ← served, tested, fresh
   │
   ├── R: lm/glm/lme4 + tidymodels (Rscript *.R)  ← reads gold, writes gold.predictions,
   │        Python statsmodels/sklearn (parity)      gold.model_metrics, models/*.rds
   ▼
[Quarto static dashboard → docs/]  (+ optional local Shiny)   ← reads predictions/metrics
        ▲ all orchestrated by Python (run.py / Dagster-lite): each step a subprocess;
          non-zero exit fails the run.
```

### DuckDB schema (football specifics)
- **bronze:** `bronze_games`, `bronze_plays`, `bronze_drives`, `bronze_teams`,
  `bronze_lines` (betting), `bronze_ratings_sp`, `bronze_roster`, `bronze_coaches`,
  `bronze_calendar`. Each append-only with `pull_id`, `fetched_at`, `season`, `week`.
- **silver:** cleaned/typed staging + conformance (canonical team keys; dedup; valid ranges).
- **gold (star):**
  - `dim_team` — **SCD2** (dbt snapshot): conference, head coach, SP+ rating valid-from/to.
  - `dim_game`, `dim_calendar` (season/week), `dim_play_type`.
  - `fct_team_game` — one row per team-per-game: points, off/def EPA aggregates, success
    rate, finishing-drives, result, vs-line cover.
  - `fct_play` — one row per play: EPA, WP, down, distance, yardline, garbage-time flag, plus
    per-play **expected** values and residuals (rush_yards, expected_rush_yards, **ryoe**;
    completion, completion_prob, **cpoe**) written back by the R models.
  - `fct_drive` — one row per drive.
  - marts: `mart_team_efficiency` (opponent-adjusted, rolling form via window fns),
    `mart_player_over_expected` (RYOE/CPOE leaderboards + **stability** splits),
    `mart_game_predictions`, `mart_model_metrics`.
- **SQL showcase:** cumulative/rolling season EPA, opponent adjustment, rest/travel, and the
  split-half / season-over-season **stability** correlations (Ch. 2) — all window-function +
  CTE-chain heavy.

### Book-grounded methods (Eager & Erickson) — the modeling suite

The book's spine is the **"Over Expected" residual idea** (model the *expected* outcome from
game situation; the *residual* is skill) plus a ladder of classical models. We implement that
ladder against CFB data, each method in **both R and Python** (the book's exact idioms), and
surface every one in the dashboard. Implemented in order of dependency:

| # | Book ch. | Method | CFB application (this repo) | R / Python tools |
|---|---|---|---|---|
| M1 | Ch. 2 | EDA + **metric stability** (split-half & year-over-year reliability) | Which team/QB efficiency stats are skill vs noise → governs which features we trust | `dplyr`/`ggplot2` · `pandas`/`matplotlib` |
| M2 | Ch. 3 | **Simple linear regression** | **RYOE** v1 — expected rush yards from yardline/down-distance; residual = rusher/team RYOE | `lm()` · `statsmodels.ols` |
| M3 | Ch. 4 | **Multiple regression** | **RYOE** v2 — add controls (box count proxy, score diff, defense quality) | `lm()` · `statsmodels` |
| M4 | Ch. 5 | **GLM / logistic regression** (+ odds ratios) | **CPOE** — completion probability from air-yards/down/distance; residual = QB CPOE | `glm(binomial)` · `statsmodels GLM/Logit` |
| M5 | Ch. 6 | **Poisson regression** (overdispersion → neg-binomial) | **Passing-TD** counts → **betting-prop** framing; benchmark vs CFBD lines | `glm(poisson)`/`MASS::glm.nb` · `statsmodels` |
| M6 | Ch. 8 | **PCA + k-means clustering** | **Team/player archetypes** from multi-stat efficiency profiles | `prcomp`+`kmeans` · `sklearn` PCA/KMeans |
| M7 | Ch. 9 | **Multilevel / mixed-effects** (partial pooling, **shrinkage / regression-to-mean**) | Stabilize small-sample RYOE/CPOE by shrinking toward team/positional means | **`lme4::lmer/glmer`** · `statsmodels MixedLM` |
| M8 | Ch. 7 | **Web scraping** *(optional)* | Recruiting-rank (composite) vs on-field production — "do teams beat their recruiting" | `rvest` · `requests`+`bs4` |

**Predictive application (ties the above together).** A **game-level win-prob / spread model**
consumes the book-derived features (team RYOE, CPOE, efficiency, archetypes): `tidymodels`
(`recipes`→`parsnip` logistic + xgboost→**time-aware `rsample` CV**, train weeks 1..k predict
k+1, **no leakage**→`tune`→**`yardstick`** Brier/log-loss/AUC/**calibration**); **benchmark =
the CFBD betting line**. Python `scikit-learn` = the documented **parity baseline**.

**Phasing.** *First pass:* M1–M5 + the game model (the book's core ladder + the headline
predictor). *Second pass:* M6–M7 (archetypes + multilevel shrinkage), play-level **EPA**
(expected-points from play-by-play, the book's "next steps"), and optional M8 scraping.

**Why both languages per method:** the book demonstrates each in R *and* Python; doing the
same here is the cleanest possible "polyglot" proof and lets the dashboard show R-vs-Python
coefficient/prediction parity as a built-in correctness check.

### Polyglot contract (the "R backend, Python scaffolding" answer)
- `run.py` (typer CLI; Dagster optional later) sequences: `ingest → dbt build →
  Rscript train.R → Rscript score.R → quarto render`. Each is `subprocess.run(...)`;
  non-zero exit aborts the pipeline (clean failure handling).
- R reads gold from the **same DuckDB file** (`duckdb` + `dbplyr`), writes back
  `gold.predictions` + `gold.model_metrics` and `models/model.rds` + `metrics.json`.
- Envs isolated and lockfile'd: **`uv`** (Python) + **`renv`** (R). Reproducibility signal.

### Dashboard (two stories the user asked for)
1. **Data / EDA evaluation:** team-efficiency & **RYOE/CPOE leaderboards** (`gt`/`gtExtras` +
   `cfbplotR` logos), distributions, the **stability** plots (M1), and a **data-quality panel**
   (dbt test pass/fail, freshness, row counts) — the "evaluating the data" view.
2. **Model accuracy:** per book model — regression diagnostics & **odds ratios** (M2–M5),
   Poisson fit vs actual TDs (M5), PCA/cluster maps (M6), shrinkage before/after (M7); and for
   the game predictor: calibration curve, Brier/log-loss by week, predicted-vs-actual,
   accuracy-vs-betting-line, confusion matrix, feature importance — plus the **R-vs-Python
   parity** check — the "evaluating the model" view.
- Built in **Quarto** (R + Python chunks) → `docs/`; CFBD attribution shown. Data embedded →
  HTML **gitignored**, a committed attributed PNG used as the public artifact (OpenSky pattern).

---

## Template-kit composition (`project-templates`) — concrete merge strategy

Compose **four** of the seven kits: `data-engineering-pipeline/` (ingestion + medallion
spine), `analytics-engineering/` (dbt + SCD2 snapshots), `data-science-analysis/` (EDA +
communicating findings — matches the book), `ml-project/` (model + honest eval). Each kit is
designed to *be* a repo root (its own `CLAUDE.md`, `settings.json`, `guard.py`), so merging
into one repo needs the following — verified against the kit contents:

- **Hooks (the one real blocker):** all four ship `.claude/hooks/guard.py` at the *same path*
  on the *same* `Bash|Edit|Write` matcher. Rename to `guard_de.py`, `guard_dbt.py`,
  `guard_ds.py`, `guard_ml.py` and register **all four** under one `hooks.PreToolUse`. Their
  regexes are complementary (union, not conflict); audit the AE `SELECT *`-in-mart check vs
  the DE bronze-DDL check so they don't cross-fire on each other's files.
- **`settings.json` (single merged file):** union `permissions.allow/ask/deny` with
  **deny-wins** — preserve ml's `Read/Edit(data/test/**)` deny (sealed test set) and AE's
  `profiles.yml` / `**/raw/**` denies. Register all four MCP servers (`de-tools`, `dbt-tools`,
  `ds-tools`, `ml-tools` — names distinct, no collision) and the four renamed hooks.
- **Skills / commands / agents — copy as-is, no collisions:** skills
  `building-or-changing-a-pipeline-model`, `adding-or-changing-a-dbt-model`,
  `running-an-analysis-or-eda`, `model-training`; commands `/pipeline-check`, `/model-check`,
  `/analysis-check`, `/train-gate`; review agents `pipeline-reviewer`, `dbt-model-reviewer`,
  `analysis-reviewer`, `eval-reviewer`. Keep the four MCP servers **separate** (fully-qualified
  tool names don't collide even though `query_readonly` repeats in 3 and `check_leakage` has
  two different signatures). Wire each server's placeholder DB connection to our DuckDB file
  (read-only).
- **One top-level `CLAUDE.md`:** the kits' `src/`/`models/` layouts mean different things, so
  write a single `CLAUDE.md` for *this* repo's real polyglot stack + the **union of
  Non-negotiables** (idempotent loads, immutable bronze, freshness/volume checks, DQ tests on
  every model, sealed holdout, no leakage, seed=42 reproducibility, no PII/secrets in logs).
  Keep the four `PRINCIPLES.md` as cited references under `docs/principles/`.
- **R adaptation (no kit covers R):** extend `CLAUDE.md` with an R section — `renv` lockfile,
  the `Rscript` subprocess data-contract, `.Renviron` secrets never committed — and apply the
  DS/ML rigor rules (sealed holdout, no leakage, reproducibility) to the **R tidymodels** path,
  enforced by convention + the `analysis-reviewer` / `eval-reviewer` agents (the ml guard's
  Python-specific forbidden-feature/sealed-test regexes get an R-aware analogue).
- **Make the spine real:** the kit README flags the executable spine as dangling — we build a
  working `scripts/check.sh` (lint + dbt build + freshness), `pyproject.toml` / `uv`, `renv`,
  and a runnable eval pass.

---

## Phased task list

**Phase 0 — Pre-flight & scaffold**
1. Run the **§9 CFBD terms review**; write the README "Data source & terms" verdict.
2. Create the repo dir (`…/Desktop/Send to Github/cfb-analytics`; **gitignore data, `.venv`,
   `renv/library`** — caution re: OneDrive sync of large/locked files) and **copy this plan in
   as `PROJECT_PLAN.md`** (the user's explicit deliverable). `git init`.
3. Scaffold: compose the 4 kits' `.claude/`, `pyproject.toml`+`uv`, `renv` init, dbt project,
   DuckDB, `.env`/`.Renviron` templates, `.gitignore`, Mermaid architecture diagram.

**Phase 1 — Ingestion → bronze**
4. R `ingest/` via cfbfastR: bounded, **throttled, cached** pulls (≤1,000 calls/mo) →
   append-only bronze with lineage + an `ingest_log`. Verify with 1–2 seasons of FBS data.

**Phase 2 — dbt medallion + star + DQ**
5. silver staging/conformance; **gold star** + `dim_team` **SCD2 snapshot**; efficiency marts
   (window functions). dbt tests (not_null/unique on grain, relationships, accepted_values),
   **freshness + volume** checks, quarantine. Target: `dbt build` PASS, 0 errors.

**Phase 3 — Book models, first pass (M1–M5) + game predictor + orchestration**
6. Implement **M1 stability** (EDA), **M2/M3 RYOE** (`lm`), **M4 CPOE** (`glm` binomial),
   **M5 passing-TD Poisson** — each in **R and Python**, writing residuals/coeffs back to
   `gold` (`ryoe`, `cpoe`) + a `model_coefficients` table; assert R↔Python parity.
7. R `train.R`/`score.R` game model (`tidymodels`, time-aware CV) → `gold.predictions`,
   `gold.model_metrics`, `models/*.rds`, `metrics.json`. Python `sklearn` parity baseline.
8. `run.py` Python orchestrator wiring ingest → dbt → R/Python models → render as subprocess
   steps with failure propagation.

**Phase 4 — Dashboard**
9. Quarto dashboard: data/EDA-eval view (incl. RYOE/CPOE + stability) + per-model accuracy
   view + game-predictor accuracy; attribution; gitignore HTML, commit an attributed PNG.

**Phase 5 — Book models, second pass (M6–M7), EPA, optional M8**
10. **M6 PCA + clustering** (archetypes), **M7 multilevel/mixed-effects** (`lme4`) shrinking
    RYOE/CPOE, play-level **EPA** (expected-points from play-by-play, the book's "next steps"),
    feed EPA back into the game model; optional **M8** recruiting-vs-production scraping. Add
    the corresponding dashboard views.

**Phase 6 — Polish (and deferred hooks)**
11. Case-study README section (design decisions / trade-offs / what I learned), renv/uv
    lockfiles committed, optional local **Shiny** app. **Deferred but pre-structured:**
    GitHub Actions CI + weekly cron, BigQuery-sandbox push of gold (roadmap §5/Phase 1).

---

## Verification (end-to-end)

- **One-command run:** `uv run python run.py --season 2024` → builds DuckDB, `dbt build`
  passes with tests green + freshness OK, R trains + scores, Quarto dashboard renders.
- **Data quality:** dbt test summary all-pass; row-count reconciliation (no silent drops);
  bronze immutability check (re-running ingest for a cached season adds 0 rows).
- **Book models:** each of M1–M7 produces sane, interpretable output (RYOE/CPOE leaderboards
  pass face validity; logistic odds ratios + Poisson rate ratios reported; multilevel shrinkage
  visibly pulls small-sample players toward the mean). **R↔Python parity:** coefficients /
  predictions agree within tolerance — surfaced on the dashboard as a correctness check.
- **Game predictor:** `gold.model_metrics` shows Brier < naive baseline, a sensible calibration
  curve, AUC reported, and accuracy tracked **vs the betting line** by week.
- **Polyglot contract:** confirm R writes `gold.predictions` and the Quarto dashboard reads
  it with **no Python↔R in-memory coupling** (kill R step → pipeline fails cleanly).
- **Reproducibility:** fresh clone + `uv sync` + `renv::restore()` + API key → identical
  outputs; secrets absent from git history; raw data gitignored.
- **Deliverable check:** `PROJECT_PLAN.md` is present at the repo root.

## Open decisions to confirm at execution time
- Final repo name/path (default above).
- Seasons to ingest (default: 2 recent FBS regular seasons — keeps calls < 1,000/mo and data
  in MBs).
- Orchestrator depth: start with a typer `run.py`; add **Dagster** only if you want the
  orchestration-tool signal (matches the manufacturing flagship).
