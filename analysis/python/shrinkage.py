"""M7 (Eager & Erickson, Ch.9) — multilevel shrinkage, Python parity of shrinkage.R.

statsmodels MixedLM fits the same random-intercept model as lme4 (both REML by default), so the
fixed intercept and variance components should agree closely and the per-rusher BLUPs correlate
~1 with R. Mixed-model optimizers differ, so this is reported as agreement metrics, not the
strict coefficient gate.

Reads data/gold/plays_model.csv, data/results/pred__ryoe__py.csv (+ the R output for the parity
report); writes pred__shrinkage__py / coef__shrinkage__py / metrics__shrinkage__py /
metrics__shrinkage_parity__py.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

from cfb_analytics.config import REPO_ROOT

GOLD = REPO_ROOT / "data" / "gold"
RESULTS = REPO_ROOT / "data" / "results"
MIN_CARRIES = 5


def main() -> None:
    plays = pd.read_csv(GOLD / "plays_model.csv")
    plays = plays[(plays.is_rush == 1) & plays.rusher_player_name.notna()][
        ["play_key", "rusher_player_name"]].rename(columns={"rusher_player_name": "rusher"})
    ryoe = pd.read_csv(RESULTS / "pred__ryoe__py.csv")[["play_key", "ryoe"]]

    d = ryoe.merge(plays, on="play_key")
    d = d.groupby("rusher").filter(lambda g: len(g) >= MIN_CARRIES)

    md = smf.mixedlm("ryoe ~ 1", d, groups=d["rusher"]).fit()
    grand = float(md.fe_params["Intercept"])
    tau = float(np.sqrt(md.cov_re.iloc[0, 0]))     # between-rusher SD
    sigma = float(np.sqrt(md.scale))               # residual (play) SD

    re = {g: float(v.iloc[0]) for g, v in md.random_effects.items()}
    raw = d.groupby("rusher")["ryoe"].agg(carries="count", raw_ryoe="mean").reset_index()
    raw["shrunk_ryoe"] = raw["rusher"].map(lambda g: grand + re.get(g, 0.0))
    raw["shrinkage"] = raw["raw_ryoe"] - raw["shrunk_ryoe"]
    raw["language"] = "py"

    coef = pd.DataFrame([dict(model="shrinkage", term="(Intercept)",
                              estimate=grand, language="py")])
    icc = tau**2 / (tau**2 + sigma**2)
    metrics = pd.DataFrame([
        dict(model="shrinkage", metric="grand_mean_ryoe", value=grand),
        dict(model="shrinkage", metric="tau_between_rusher_sd", value=tau),
        dict(model="shrinkage", metric="sigma_residual_sd", value=sigma),
        dict(model="shrinkage", metric="icc", value=icc),
        dict(model="shrinkage", metric="n_rushers", value=float(len(raw))),
        dict(model="shrinkage", metric="n_plays", value=float(len(d))),
    ])
    metrics["language"] = "py"

    RESULTS.mkdir(parents=True, exist_ok=True)
    raw.to_csv(RESULTS / "pred__shrinkage__py.csv", index=False)
    coef.to_csv(RESULTS / "coef__shrinkage__py.csv", index=False)
    metrics.to_csv(RESULTS / "metrics__shrinkage__py.csv", index=False)

    # agreement vs R: fixed intercept, variance components, BLUP correlation
    r_path = RESULTS / "pred__shrinkage__r.csv"
    if r_path.exists():
        r = pd.read_csv(r_path)[["rusher", "shrunk_ryoe"]].rename(
            columns={"shrunk_ryoe": "shrunk_r"})
        merged = raw.merge(r, on="rusher")
        blup_corr = float(np.corrcoef(merged["shrunk_ryoe"], merged["shrunk_r"])[0, 1])
        rm = pd.read_csv(RESULTS / "metrics__shrinkage__r.csv").set_index("metric")["value"]
        parity = pd.DataFrame([
            dict(model="shrinkage", metric="blup_corr_r_vs_py", value=blup_corr),
            dict(model="shrinkage", metric="grand_mean_abs_diff",
                 value=abs(grand - float(rm["grand_mean_ryoe"]))),
            dict(model="shrinkage", metric="tau_abs_diff",
                 value=abs(tau - float(rm["tau_between_rusher_sd"]))),
        ])
        parity["language"] = "parity"
        parity.to_csv(RESULTS / "metrics__shrinkage_parity__py.csv", index=False)
        gm_diff = abs(grand - float(rm["grand_mean_ryoe"]))
        print(f"[shrinkage/py] tau={tau:.3f} sigma={sigma:.3f} ICC={icc:.4f}; "
              f"vs R: BLUP corr={blup_corr:.4f}, grand-mean diff={gm_diff:.2e}")
    else:
        print(f"[shrinkage/py] tau={tau:.3f} sigma={sigma:.3f} ICC={icc:.4f} (R output not found)")


if __name__ == "__main__":
    main()
