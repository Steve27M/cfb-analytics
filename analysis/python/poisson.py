"""M5 (Eager & Erickson, Ch.6) — Passing-TD Poisson, Python parity of poisson.R.

statsmodels GLM(Poisson) mirrors R's glm(family=poisson). We also fit a negative binomial and
compare AIC + report the dispersion, matching the R script's overdispersion check.

Reads data/gold/team_game_passing.csv; writes coef__poisson__py / metrics__poisson__py.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
import statsmodels.api as sm

from cfb_analytics.config import REPO_ROOT

GOLD = REPO_ROOT / "data" / "gold"
RESULTS = REPO_ROOT / "data" / "results"
_TERM = {"Intercept": "(Intercept)"}
FORMULA = "passing_tds ~ np.log(pass_attempts) + opponent_defense_rating"
# R term for log(pass_attempts) is "log(pass_attempts)"; align statsmodels' patsy name to it.
_TERM_EXTRA = {"np.log(pass_attempts)": "log(pass_attempts)"}


def _term(t: str) -> str:
    return _TERM_EXTRA.get(t, _TERM.get(t, t))


def main() -> None:
    tg = pd.read_csv(GOLD / "team_game_passing.csv")
    tg = tg[tg.passing_tds.notna() & tg.pass_attempts.notna()
            & (tg.pass_attempts > 0) & tg.opponent_defense_rating.notna()].copy()

    pois = smf.glm(FORMULA, data=tg, family=sm.families.Poisson()).fit()
    disp = float(np.sum(pois.resid_pearson ** 2) / pois.df_resid)

    coef = pd.DataFrame({
        "model": "passing_td_poisson",
        "term": [_term(t) for t in pois.params.index],
        "estimate": pois.params.values,
        "std_error": pois.bse.values,
        "statistic": pois.tvalues.values,
        "p_value": pois.pvalues.values,
        "rate_ratio": np.exp(pois.params.values),
        "language": "py",
    })
    metrics = pd.DataFrame([
        dict(model="passing_td_poisson", metric="dispersion", value=disp),
        dict(model="passing_td_poisson", metric="aic_poisson", value=float(pois.aic)),
        dict(model="passing_td_poisson", metric="mean_tds", value=float(tg.passing_tds.mean())),
        dict(model="passing_td_poisson", metric="var_tds", value=float(tg.passing_tds.var())),
        dict(model="passing_td_poisson", metric="n_obs", value=float(len(tg))),
    ])

    # negative binomial (statsmodels NB alpha = 1/theta); compare AIC
    nb_aic = np.nan
    try:
        nb = smf.glm(FORMULA, data=tg,
                     family=sm.families.NegativeBinomial()).fit()
        nb_aic = float(nb.aic)
        nb_coef = pd.DataFrame({
            "model": "passing_td_negbin",
            "term": [_term(t) for t in nb.params.index],
            "estimate": nb.params.values,
            "std_error": nb.bse.values,
            "statistic": nb.tvalues.values,
            "p_value": nb.pvalues.values,
            "rate_ratio": np.exp(nb.params.values),
            "language": "py",
        })
        coef = pd.concat([coef, nb_coef], ignore_index=True)
        metrics = pd.concat([metrics, pd.DataFrame([
            dict(model="passing_td_negbin", metric="aic_negbin", value=nb_aic),
        ])], ignore_index=True)
    except Exception as e:  # noqa: BLE001
        print(f"[poisson/py] NB fit skipped: {e}")

    metrics["language"] = "py"
    RESULTS.mkdir(parents=True, exist_ok=True)
    coef.to_csv(RESULTS / "coef__poisson__py.csv", index=False)
    metrics.to_csv(RESULTS / "metrics__poisson__py.csv", index=False)
    aic_nb = f" / NB={nb_aic:.1f}" if not np.isnan(nb_aic) else ""
    print(f"[poisson/py] dispersion={disp:.3f}, AIC poisson={pois.aic:.1f}{aic_nb}, "
          f"{len(tg)} team-games")


if __name__ == "__main__":
    main()
