"""Load the R/Python model results (data/results/*.csv) back into DuckDB gold.* — the
results side of the polyglot contract — and run the committed R<->Python parity check.

The book's methods are implemented twice (R and Python) on the same flat-file feed. Because the
fits are mathematically identical (OLS, IRLS GLM, Poisson), their coefficients MUST agree to
tolerance; if they don't, something is wrong with one implementation. parity_check() enforces
that and writes gold.model_parity for the dashboard. The negative-binomial is excluded: R's
MASS::glm.nb estimates theta while statsmodels' GLM uses a fixed alpha, so they legitimately differ.

Creates: gold.model_coefficients, gold.model_metrics, gold.predictions, gold.model_parity.
"""
from __future__ import annotations

import glob

import duckdb
import pandas as pd

from .config import DUCKDB_PATH, REPO_ROOT

RESULTS_DIR = REPO_ROOT / "data" / "results"
PARITY_RTOL = 1e-4          # relative tolerance on coefficient estimates
PARITY_EXCLUDE_MODELS = {"passing_td_negbin"}


def _read_glob(pattern: str) -> pd.DataFrame:
    frames = [pd.read_csv(p) for p in sorted(glob.glob(str(RESULTS_DIR / pattern)))]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def parity_check(coef: pd.DataFrame) -> pd.DataFrame:
    """Join R vs Python coefficients per (model, term); flag any beyond tolerance."""
    r = coef[coef.language == "r"][["model", "term", "estimate"]]
    py = coef[coef.language == "py"][["model", "term", "estimate"]]
    merged = r.merge(py, on=["model", "term"], suffixes=("_r", "_py"))
    merged = merged[~merged.model.isin(PARITY_EXCLUDE_MODELS)].copy()
    merged["abs_diff"] = (merged.estimate_r - merged.estimate_py).abs()
    merged["tol"] = PARITY_RTOL * (1 + merged.estimate_r.abs())
    merged["within_tol"] = merged.abs_diff <= merged.tol
    return merged


def load() -> None:
    coef = _read_glob("coef__*.csv")
    metrics = _read_glob("metrics__*.csv")
    preds = _read_glob("pred__*.csv")          # play-grain RYOE/CPOE residuals
    game_preds = _read_glob("gamepred__*.csv")  # game-grain win-prob predictions
    if coef.empty:
        raise SystemExit("no results found in data/results — run the R/Python models first")

    parity = parity_check(coef)

    con = duckdb.connect(str(DUCKDB_PATH))
    try:
        con.execute("CREATE SCHEMA IF NOT EXISTS gold")
        for name, df in [
            ("model_coefficients", coef),
            ("model_metrics", metrics),
            ("predictions", preds),
            ("game_predictions", game_preds),
            ("model_parity", parity),
        ]:
            if df.empty:
                continue
            con.register("_df", df)
            con.execute(f"CREATE OR REPLACE TABLE gold.{name} AS SELECT * FROM _df")
            con.unregister("_df")
            print(f"  gold.{name:20s} {len(df):>6,} rows")
    finally:
        con.close()

    n_bad = int((~parity.within_tol).sum())
    n_tot = len(parity)
    if n_bad:
        bad = parity[~parity.within_tol][["model", "term", "estimate_r", "estimate_py",
                                          "abs_diff", "tol"]]
        raise SystemExit(
            f"R<->Python PARITY FAILED: {n_bad}/{n_tot} coefficients exceed tolerance\n"
            + bad.to_string(index=False))
    print(f"  R<->Python parity OK: {n_tot}/{n_tot} coefficients agree "
          f"(rtol={PARITY_RTOL})")


if __name__ == "__main__":
    load()
