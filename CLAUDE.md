# cfb-analytics — Polyglot College-Football Analytics Pipeline

A portfolio project: CFBD API → DuckDB → dbt (medallion + Kimball star) → the statistical
models from *Football Analytics with Python & R* (Eager & Erickson) in **R and Python** →
Quarto dashboard. See `PROJECT_PLAN.md` for the full design and `docs/principles/` for the
cited best-practice checklists this repo's rules compress (four kits: DE, dbt/AE, DS, ML).

## Stack
- **Python 3.12 + `uv`** (never `pip` directly). Package at `src/cfb_analytics/`.
- **R 4.x + `renv`** — `cfbfastR` ingest; `lm`/`glm`/`lme4` + `tidymodels` modeling;
  `gt`/`gtExtras`/`cfbplotR`/`ggplot2` presentation; `duckdb`/`DBI`/`dbplyr` warehouse access.
- **dbt-duckdb** (project in `transform/`) — the only place SQL transforms live.
- **DuckDB** local warehouse at `data/cfb.duckdb` (gitignored).
- **Quarto** static dashboard → `docs/` (R + Python chunks).
- **Orchestration:** Python `run.py` (typer) sequences ingest → dbt → R/Python models →
  render as **subprocess steps**; non-zero exit aborts the run.
- **Layers (medallion):** `bronze` (raw/immutable, written by ingestion) → `silver` (clean) →
  `gold` (Kimball star + marts, served).

## Commands
- Install (py):   `uv sync`
- Install (R):    `Rscript scripts/install_r_packages.R`  then  `Rscript -e 'renv::snapshot()'`
- Lint/type:      `uv run ruff check . && uv run mypy src`
- Ingest bronze:  `Rscript ingest/ingest_cfbd.R`            (bounded/throttled/cached CFBD pulls)
- dbt build:      `uv run dbt build --project-dir transform --profiles-dir transform`
- dbt freshness:  `uv run dbt source freshness --project-dir transform --profiles-dir transform`
- R models:       `Rscript analysis/R/<model>.R`            (read gold, write residuals/metrics)
- Full pipeline:  `uv run python run.py --season 2024`
- Dashboard:      `quarto render dashboard/dashboard.qmd`
- Full check:     `./scripts/check.sh`                       (lint, dbt build, freshness)

## The polyglot data contract (non-negotiable)
R and Python communicate **only through flat files + the warehouse**, never in-memory:
- **Ingest:** R (`cfbfastR`) writes `data/bronze/*.csv[.gz]` (lineage-tagged, season-partitioned).
- **Land:** Python (`cfb_analytics.load_bronze`) loads those into DuckDB `bronze.*`.
- **Transform:** dbt builds `staging → silver → gold` in DuckDB.
- **Export:** Python (`cfb_analytics.export_gold`) writes the gold tables R needs to `data/gold/*.csv`.
- **Model:** R reads `data/gold/*.csv` (`readr`), fits, writes `data/results/*.csv`.
- **Load results:** Python loads those into `gold.predictions`, `gold.model_metrics`,
  `gold.model_coefficients`.
- No `rpy2`, no in-process bridge. Killing any stage fails the pipeline cleanly.

> **Why CSV on the R edge:** R 4.6.1 (released 2026-06-24) has no Windows binary yet for the
> `duckdb`/`arrow`/`nanoparquet` R packages, and source installs crash. R therefore uses
> `readr` CSV (already installed); **Python** owns all DuckDB/Parquet I/O. Swap the R edge to
> Parquet later once `nanoparquet`/`arrow` binaries exist — the contract is unchanged.

## Non-negotiables (union of the four kits' rules; all traceable to `docs/principles/`)
- **Idempotent + reproducible.** A step run once or thrice yields the same result. Re-ingesting
  a season already in bronze adds **0 rows**. Seed everything (`set.seed(42)` / `random_state=42`).
- **bronze is immutable & ingestion-only.** No `DROP`/`TRUNCATE`/in-place rewrite of bronze;
  silver/gold are rebuilt *from* bronze. Ingestion writes bronze only; never source/prod.
- **dbt layering & grain.** Every model declares its grain (header + YAML). Staging only
  renames/recasts (no joins/aggs). Marts build from `ref()`; only staging may call `source()`.
  No `SELECT *` in marts. Surrogate keys minted in marts, not staging.
- **Every new/changed dbt model has tests.** At minimum `not_null` + `unique` on the grain key,
  plus relevant `relationships`/`accepted_values`. **Freshness + volume** checks on every gold
  table. No model is "done" without tests.
- **SCD2 via dbt snapshot** for `dim_team` (conference/coach/SP+ change over seasons).
- **Modeling discipline (the book's methods).** Seal the holdout; **no leakage** (time-aware
  CV: train weeks 1..k, predict k+1); **beat a baseline** on the right metric (Brier/log-loss
  for win-prob, not accuracy); report **slice** metrics; bundle the transform with the model.
- **R↔Python parity.** Each book method is implemented in both; coefficients/predictions must
  agree within tolerance — this is a committed correctness check, not a nicety.
- **No secrets, no PII in logs.** `CFBD_API_KEY` lives in `.env`/`.Renviron` (gitignored),
  sent as `Authorization: Bearer`. Never print keys or raw identifier rows. Raw data gitignored.
- **Respect the source (§9).** CFBD free tier = **1,000 calls/month** + Cloudflare anti-burst →
  bounded, throttled, cached collection; **no perpetual poller**; attribution shown.

## Layout
- `ingest/`            CFBD → bronze (R `cfbfastR` primary; Python client fallback). Bronze only.
- `transform/`        dbt project: `models/{staging,silver,gold}`, `snapshots/`, `macros/`, `tests/`.
- `analysis/R/`       the book's models in R (`stability`, `ryoe`, `cpoe`, `poisson`, `pca_cluster`,
                      `multilevel`, `game_model_{train,score}`) + `util_db.R`.
- `analysis/python/`  Python parity implementations (`statsmodels`/`sklearn`).
- `src/cfb_analytics/` Python package: orchestration (`run.py` entry), DB helpers, config.
- `dashboard/`        Quarto `dashboard.qmd` (data-eval + model-accuracy views).
- `artifacts/`        trained models (`.rds`/`.pkl`) + `metrics.json` (gitignored).
- `data/`             DuckDB warehouse + raw cache (gitignored).
- `scripts/`          `install_r_packages.R`, `check.sh`.

## Style
- Match existing patterns; read the analogous model/script before writing a new one.
- Minimal diffs; comments explain WHY (the invariant), not WHAT.
- Incremental/append work is partition-aware and safe to re-run.

## Agent guardrails (composed from 4 kits)
`.claude/` merges the DE, dbt/AE, DS, and ML kits: four `PreToolUse` guards
(`guard_{de,dbt,ds,ml}.py`), four review subagents (`pipeline-reviewer`, `dbt-model-reviewer`,
`analysis-reviewer`, `eval-reviewer`), four gates (`/pipeline-check`, `/model-check`,
`/analysis-check`, `/train-gate`), and four MCP servers (`de-tools`, `dbt-tools`, `ds-tools`,
`ml-tools`). Hooks invoke `python` (this machine has no `python3` alias).
