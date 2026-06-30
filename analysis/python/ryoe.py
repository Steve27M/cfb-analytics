"""M2/M3 (Eager & Erickson, Ch.3-4) — Rushing Yards Over Expected, Python parity of ryoe.R.

statsmodels OLS mirrors R's lm() exactly (same design matrix, same closed-form fit), so the
coefficients must agree to numerical tolerance — that agreement is the committed correctness
check. Same feed, features, mean-imputation, and filtering as the R version.

Reads data/gold/plays_model.csv; writes coef__ryoe__py / metrics__ryoe__py / pred__ryoe__py.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

from cfb_analytics.config import REPO_ROOT

GOLD = REPO_ROOT / "data" / "gold"
RESULTS = REPO_ROOT / "data" / "results"
FEATURES_M3 = ["down", "distance", "yards_to_goal",
               "offense_score_diff_start", "defense_def_rating"]

# statsmodels names the intercept "Intercept"; R names it "(Intercept)". Normalise to R's so the
# parity join lines terms up.
_TERM = {"Intercept": "(Intercept)"}


def _rmse(actual: np.ndarray, pred: np.ndarray) -> float:
    return float(np.sqrt(np.mean((actual - pred) ** 2)))


def _coef_frame(res, model_name: str) -> pd.DataFrame:
    return pd.DataFrame({
        "model": model_name,
        "term": [_TERM.get(t, t) for t in res.params.index],
        "estimate": res.params.values,
        "std_error": res.bse.values,
        "statistic": res.tvalues.values,
        "p_value": res.pvalues.values,
        "language": "py",
    })


def main() -> None:
    plays = pd.read_csv(GOLD / "plays_model.csv")
    rush = plays[(plays.is_rush == 1) & plays.rush_yards.notna()
                 & plays.down.notna() & plays.distance.notna()
                 & plays.yards_to_goal.notna()
                 & plays.offense_score_diff_start.notna()].copy()

    def_mean = rush["defense_def_rating"].mean()
    rush["defense_def_rating"] = rush["defense_def_rating"].fillna(def_mean)

    m2 = smf.ols("rush_yards ~ yards_to_goal", data=rush).fit()
    m3 = smf.ols("rush_yards ~ " + " + ".join(FEATURES_M3), data=rush).fit()

    pred3 = m3.predict(rush).to_numpy()
    actual = rush["rush_yards"].to_numpy()
    base_rmse = _rmse(actual, np.full_like(actual, actual.mean(), dtype=float))

    coef = pd.concat([_coef_frame(m2, "ryoe_simple"),
                      _coef_frame(m3, "ryoe_multiple")], ignore_index=True)
    metrics = pd.DataFrame([
        dict(model="ryoe_simple", metric="rmse", value=_rmse(actual, m2.predict(rush))),
        dict(model="ryoe_simple", metric="r_squared", value=m2.rsquared),
        dict(model="ryoe_multiple", metric="rmse", value=_rmse(actual, pred3)),
        dict(model="ryoe_multiple", metric="r_squared", value=m3.rsquared),
        dict(model="ryoe_multiple", metric="n_obs", value=float(len(rush))),
        dict(model="baseline_mean", metric="rmse", value=base_rmse),
    ])
    metrics["language"] = "py"

    pred = pd.DataFrame({
        "play_key": rush["play_key"].values,
        "expected_rush_yards": pred3,
        "ryoe": actual - pred3,
        "language": "py",
    })

    RESULTS.mkdir(parents=True, exist_ok=True)
    coef.to_csv(RESULTS / "coef__ryoe__py.csv", index=False)
    metrics.to_csv(RESULTS / "metrics__ryoe__py.csv", index=False)
    pred.to_csv(RESULTS / "pred__ryoe__py.csv", index=False)
    print(f"[ryoe/py] M3 RMSE={_rmse(actual, pred3):.3f} (baseline {base_rmse:.3f}), "
          f"R2={m3.rsquared:.4f}, {len(rush)} plays")


if __name__ == "__main__":
    main()
