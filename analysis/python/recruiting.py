"""M8 (Eager & Erickson, Ch.7) — recruiting vs production, Python parity of recruiting.R.

statsmodels OLS mirrors R's lm() exactly, so the coefficients enter the strict R<->Python parity
gate. Same feed, model, and residual definition.

Reads data/gold/recruiting_production.csv; writes coef__recruiting__py / metrics__recruiting__py /
pred__recruiting__py.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

from cfb_analytics.config import REPO_ROOT

GOLD = REPO_ROOT / "data" / "gold"
RESULTS = REPO_ROOT / "data" / "results"
_TERM = {"Intercept": "(Intercept)"}


def main() -> None:
    df = pd.read_csv(GOLD / "recruiting_production.csv")
    df = df[df.sp_rating.notna() & df.recruiting_rank_247.notna()].copy()

    m = smf.ols("sp_rating ~ recruiting_rank_247", data=df).fit()
    pred = m.predict(df).to_numpy()

    coef = pd.DataFrame({
        "model": "recruiting",
        "term": [_TERM.get(t, t) for t in m.params.index],
        "estimate": m.params.values,
        "std_error": m.bse.values,
        "statistic": m.tvalues.values,
        "p_value": m.pvalues.values,
        "language": "py",
    })
    metrics = pd.DataFrame([
        dict(model="recruiting", metric="r_squared", value=float(m.rsquared)),
        dict(model="recruiting", metric="corr_rank_sp",
             value=float(np.corrcoef(df.recruiting_rank_247, df.sp_rating)[0, 1])),
        dict(model="recruiting", metric="n_obs", value=float(len(df))),
    ])
    metrics["language"] = "py"

    out = df.copy()
    out["predicted_sp"] = pred
    out["performance_vs_recruiting"] = out["sp_rating"] - pred
    out["language"] = "py"
    out = out[["team", "season", "recruiting_rank_247", "sp_rating", "win_pct",
               "predicted_sp", "performance_vs_recruiting", "language"]]

    RESULTS.mkdir(parents=True, exist_ok=True)
    coef.to_csv(RESULTS / "coef__recruiting__py.csv", index=False)
    metrics.to_csv(RESULTS / "metrics__recruiting__py.csv", index=False)
    out.to_csv(RESULTS / "pred__recruiting__py.csv", index=False)
    print(f"[recruiting/py] SP+ ~ recruiting rank: R2={m.rsquared:.3f}, "
          f"corr={np.corrcoef(df.recruiting_rank_247, df.sp_rating)[0, 1]:.3f}, "
          f"{len(df)} team-seasons")


if __name__ == "__main__":
    main()
