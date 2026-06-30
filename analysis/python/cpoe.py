"""M4 (Eager & Erickson, Ch.5) — Completion % Over Expected, Python parity of cpoe.R.

statsmodels GLM(Binomial) mirrors R's glm(family=binomial) (both IRLS) → coefficients agree to
tolerance. Same feed, features, and filtering as the R version.

Reads data/gold/plays_model.csv; writes coef__cpoe__py / metrics__cpoe__py / pred__cpoe__py.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
import statsmodels.api as sm

from cfb_analytics.config import REPO_ROOT

GOLD = REPO_ROOT / "data" / "gold"
RESULTS = REPO_ROOT / "data" / "results"
FEATURES = ["down", "distance", "yards_to_goal", "offense_score_diff_start"]
_TERM = {"Intercept": "(Intercept)"}


def main() -> None:
    plays = pd.read_csv(GOLD / "plays_model.csv")
    pas = plays[(plays.is_pass_attempt == 1) & plays.is_completion.notna()
                & plays.down.notna() & plays.distance.notna()
                & plays.yards_to_goal.notna()
                & plays.offense_score_diff_start.notna()].copy()

    res = smf.glm("is_completion ~ " + " + ".join(FEATURES),
                  data=pas, family=sm.families.Binomial()).fit()

    prob = res.predict(pas).to_numpy()
    y = pas["is_completion"].to_numpy()
    cpoe = y - prob

    brier = float(np.mean((y - prob) ** 2))
    base_rate = float(y.mean())
    brier_base = float(np.mean((y - base_rate) ** 2))
    p = np.clip(prob, 1e-15, 1 - 1e-15)
    log_loss = float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))

    coef = pd.DataFrame({
        "model": "cpoe",
        "term": [_TERM.get(t, t) for t in res.params.index],
        "estimate": res.params.values,
        "std_error": res.bse.values,
        "statistic": res.tvalues.values,
        "p_value": res.pvalues.values,
        "odds_ratio": np.exp(res.params.values),
        "language": "py",
    })
    metrics = pd.DataFrame([
        dict(model="cpoe", metric="brier", value=brier),
        dict(model="cpoe", metric="brier_baseline", value=brier_base),
        dict(model="cpoe", metric="log_loss", value=log_loss),
        dict(model="cpoe", metric="completion_rate", value=base_rate),
        dict(model="cpoe", metric="n_obs", value=float(len(pas))),
    ])
    metrics["language"] = "py"
    pred = pd.DataFrame({
        "play_key": pas["play_key"].values,
        "completion_prob": prob,
        "cpoe": cpoe,
        "language": "py",
    })

    RESULTS.mkdir(parents=True, exist_ok=True)
    coef.to_csv(RESULTS / "coef__cpoe__py.csv", index=False)
    metrics.to_csv(RESULTS / "metrics__cpoe__py.csv", index=False)
    pred.to_csv(RESULTS / "pred__cpoe__py.csv", index=False)
    print(f"[cpoe/py] Brier={brier:.4f} (baseline {brier_base:.4f}), "
          f"logloss={log_loss:.4f}, {len(pas)} attempts")


if __name__ == "__main__":
    main()
