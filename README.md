# cfb-analytics — Polyglot College-Football Analytics Pipeline

A portfolio project that ingests **Division-I college football** data from the
[CollegeFootballData (CFBD) API](https://collegefootballdata.com), lands it in **DuckDB**,
transforms it with **dbt** (medallion → Kimball star, incl. an SCD2 dimension), implements the
statistical models from *Football Analytics with Python & R* (Eager & Erickson) in **both R and
Python**, and renders a **Quarto dashboard** that evaluates the data and the models' accuracy.

**Stack:** R (`cfbfastR`, `tidyverse`, `tidymodels`, `lme4`, `gt`, `cfbplotR`) ·
Python (`uv`, `dbt-duckdb`, `statsmodels`, `scikit-learn`) · DuckDB · dbt · Quarto.
Orchestrated by a Python CLI that runs the R models as subprocess steps — **the data
(DuckDB tables + a metrics JSON) is the contract between languages**, not in-memory objects.

> **Status:** scaffolding. See [`PROJECT_PLAN.md`](PROJECT_PLAN.md) for the full design,
> phased task list, and verification plan.

## Modeling (grounded in the book)

| # | Method (book ch.) | CFB application |
|---|---|---|
| M1 | EDA + metric stability (Ch 2) | Which efficiency stats are skill vs noise |
| M2/M3 | Simple → multiple linear regression (Ch 3–4) | **Rushing Yards Over Expected (RYOE)** |
| M4 | Logistic GLM + odds ratios (Ch 5) | **Completion % Over Expected (CPOE)** |
| M5 | Poisson regression (Ch 6) | Passing-TD counts → betting-prop framing |
| M6 | PCA + clustering (Ch 8) | Team/player archetypes |
| M7 | Multilevel / mixed-effects (Ch 9) | Shrinkage / regression-to-the-mean |
| M8 | Web scraping (Ch 7, optional) | Recruiting rank vs on-field production |

Each method is implemented in **R and Python**, with an R↔Python parity check surfaced on the
dashboard. A game-level **win-probability / spread** model consumes these features and is
benchmarked against the CFBD betting line.

## Data source & terms (§9 pre-flight)

- **Source:** CollegeFootballData.com API (v2). **Attribution shown** in this README and on the
  dashboard: *Data: [CollegeFootballData.com](https://collegefootballdata.com)*.
- **Auth:** a **free** API key is required (register at
  [collegefootballdata.com/key](https://collegefootballdata.com/key)), sent as an
  `Authorization: Bearer <key>` header. The key is read from the `CFBD_API_KEY` environment
  variable (`.env` / `.Renviron`) and is **never committed**.
- **Rate limits:** free tier = **1,000 API calls/month**; Cloudflare blocks bursty parallel
  requests. Ingestion is therefore **bounded, throttled, and cached** — a season already in
  bronze is never re-pulled.
- **Redistribution:** raw data is **gitignored**; only code, aggregates, and an attributed
  screenshot are committed. The dashboard HTML (which embeds data) is gitignored.
- **Verdict: GO-WITH-CONDITIONS** — non-commercial portfolio use, attributed, bounded
  on-demand collection (no perpetual poller). Confirm the current Terms at key registration.

## Quickstart

> Requires the runtime toolchain (R, `uv`, dbt, Quarto, DuckDB) — see `PROJECT_PLAN.md` Phase 0.

```bash
# 1. Python env
uv sync
# 2. R env
Rscript -e 'renv::restore()'
# 3. set your key (do NOT commit)
cp .env.example .env   # then edit CFBD_API_KEY
# 4. run the pipeline end-to-end
uv run python run.py --season 2024
```
