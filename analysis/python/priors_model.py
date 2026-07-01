"""Preseason priors model (Python parity of priors_model.R).

sklearn LogisticRegression(C=inf) == R glm, so coefficients enter the strict parity gate. Same
feed, features, and latest-season holdout. Predicts games from PRIOR-season carryover only, so it
works before any current-season form exists.

Reads game_priors.csv; writes coef__priors__py / metrics__priors__py / gamepred__priors__py.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

from cfb_analytics.config import REPO_ROOT

GOLD = REPO_ROOT / "data" / "gold"
RESULTS = REPO_ROOT / "data" / "results"
FEATURES = ["prior_sp_diff", "prior_net_epa_diff", "prior_win_pct_diff"]
_TERM = {"Intercept": "(Intercept)"}


def main() -> None:
    df = pd.read_csv(GOLD / "game_priors.csv")
    holdout_season = int(df.season.max())
    train = df[df.season < holdout_season]
    test = df[df.season == holdout_season]

    m = LogisticRegression(C=np.inf, solver="lbfgs", max_iter=1000, tol=1e-10)
    m.fit(train[FEATURES].to_numpy(), train["home_won"].to_numpy())

    y = test["home_won"].to_numpy()
    p_model = m.predict_proba(test[FEATURES].to_numpy())[:, 1]
    p_naive = np.full(len(test), train["home_won"].mean())

    def brier(p: np.ndarray) -> float:
        return float(np.mean((y - p) ** 2))

    def logloss(p: np.ndarray) -> float:
        p = np.clip(p, 1e-15, 1 - 1e-15)
        return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))

    coef = pd.DataFrame({
        "model": "priors_winprob",
        "term": ["(Intercept)"] + FEATURES,
        "estimate": np.concatenate([m.intercept_, m.coef_[0]]),
        "odds_ratio": np.exp(np.concatenate([m.intercept_, m.coef_[0]])),
        "language": "py",
    })
    metrics = pd.DataFrame([
        dict(model="priors_winprob", metric="brier", value=brier(p_model)),
        dict(model="priors_winprob", metric="log_loss", value=logloss(p_model)),
        dict(model="priors_winprob", metric="auc", value=float(roc_auc_score(y, p_model))),
        dict(model="priors_winprob", metric="accuracy",
             value=float(np.mean((p_model >= 0.5) == (y == 1)))),
        dict(model="priors_winprob", metric="brier_naive", value=brier(p_naive)),
        dict(model="priors_winprob", metric="n_test", value=float(len(test))),
        dict(model="priors_winprob", metric="n_train", value=float(len(train))),
    ])
    metrics["language"] = "py"
    pred = pd.DataFrame({
        "game_id": test["game_id"].values, "season": test["season"].values,
        "home_won": y, "prior_win_prob": p_model, "language": "py",
    })

    RESULTS.mkdir(parents=True, exist_ok=True)
    coef.to_csv(RESULTS / "coef__priors__py.csv", index=False)
    metrics.to_csv(RESULTS / "metrics__priors__py.csv", index=False)
    pred.to_csv(RESULTS / "gamepred__priors__py.csv", index=False)
    print(f"[priors/py] preseason holdout Brier={brier(p_model):.4f} "
          f"(naive {brier(p_naive):.4f}), AUC={roc_auc_score(y, p_model):.3f}, {len(test)} games")


if __name__ == "__main__":
    main()
