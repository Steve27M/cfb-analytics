"""Game-level win-probability model — Python parity (sklearn) of game_model_{train,score}.R.

sklearn LogisticRegression(penalty=None) is unregularized MLE, the same objective as R's
glm(binomial), so coefficients must match the R fit to tolerance — the committed parity check.
Same feed, features, 2023-train / 2024-holdout split, and baselines as the R version.

Reads data/gold/game_model.csv; writes coef__game__py / metrics__game__py /
metrics__game_cv__py / gamepred__game__py.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import norm
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

from cfb_analytics.config import REPO_ROOT

GOLD = REPO_ROOT / "data" / "gold"
RESULTS = REPO_ROOT / "data" / "results"
# net_epa_diff = off_epa_diff - def_epa_diff exactly → excluded to avoid perfect collinearity
# (keeps coefficients identifiable and equal to the R glm fit).
FEATURES = ["off_epa_diff", "def_epa_diff",
            "roll3_net_epa_diff", "win_pct_diff", "sos_diff"]
MARGIN_SD = 13.5


def _fit(train: pd.DataFrame) -> LogisticRegression:
    # C=inf → unregularized MLE == R glm; lbfgs with a tight tol for coefficient parity
    m = LogisticRegression(C=np.inf, solver="lbfgs", max_iter=1000, tol=1e-10)
    m.fit(train[FEATURES].to_numpy(), train["home_won"].to_numpy())
    return m


def _brier(y: np.ndarray, p: np.ndarray) -> float:
    return float(np.mean((y - p) ** 2))


def _logloss(y: np.ndarray, p: np.ndarray) -> float:
    p = np.clip(p, 1e-15, 1 - 1e-15)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def main() -> None:
    df = pd.read_csv(GOLD / "game_model.csv")
    train = df[df.season == 2023].sort_values("week").reset_index(drop=True)
    test = df[df.season == 2024].reset_index(drop=True)

    # walk-forward CV on 2023 (train weeks < k, predict week k) — mirrors the R report
    weeks = sorted(train.week.unique())
    cv_y, cv_p = [], []
    for k in [w for w in weeks if w >= weeks[0] + 2]:
        tr, te = train[train.week < k], train[train.week == k]
        if len(tr) < 30 or len(te) == 0:
            continue
        m = _fit(tr)
        cv_y.append(te["home_won"].to_numpy())
        cv_p.append(m.predict_proba(te[FEATURES].to_numpy())[:, 1])
    cv_y, cv_p = np.concatenate(cv_y), np.concatenate(cv_p)
    cv_metrics = pd.DataFrame([
        dict(model="game_winprob", metric="cv_brier", value=_brier(cv_y, cv_p)),
        dict(model="game_winprob", metric="cv_log_loss", value=_logloss(cv_y, cv_p)),
        dict(model="game_winprob", metric="cv_auc", value=float(roc_auc_score(cv_y, cv_p))),
        dict(model="game_winprob", metric="cv_n", value=float(len(cv_y))),
    ])
    cv_metrics["language"] = "py"

    # final fit on all 2023, score the 2024 holdout
    final = _fit(train)
    y = test["home_won"].to_numpy()
    p_model = final.predict_proba(test[FEATURES].to_numpy())[:, 1]
    p_naive = np.full(len(test), train["home_won"].mean())
    p_market = norm.cdf(-test["home_spread_consensus"].to_numpy() / MARGIN_SD)
    model_acc = float(np.mean((p_model >= 0.5) == (y == 1)))

    metrics = pd.DataFrame([
        dict(model="game_winprob", metric="brier", value=_brier(y, p_model)),
        dict(model="game_winprob", metric="log_loss", value=_logloss(y, p_model)),
        dict(model="game_winprob", metric="auc", value=float(roc_auc_score(y, p_model))),
        dict(model="game_winprob", metric="accuracy", value=model_acc),
        dict(model="game_winprob", metric="brier_naive_homefield", value=_brier(y, p_naive)),
        dict(model="game_winprob", metric="brier_market_line", value=_brier(y, p_market)),
        dict(model="game_winprob", metric="accuracy_market_line",
             value=float(np.mean((p_market >= 0.5) == (y == 1)))),
        dict(model="game_winprob", metric="n_test", value=float(len(test))),
    ])
    metrics["language"] = "py"

    # coefficients aligned to R term names for the parity join
    coef = pd.DataFrame({
        "model": "game_winprob",
        "term": ["(Intercept)"] + FEATURES,
        "estimate": np.concatenate([final.intercept_, final.coef_[0]]),
        "odds_ratio": np.exp(np.concatenate([final.intercept_, final.coef_[0]])),
        "language": "py",
    })

    pred = pd.DataFrame({
        "game_id": test["game_id"].values,
        "season": test["season"].values,
        "week": test["week"].values,
        "home_won": y,
        "home_win_prob": p_model,
        "market_win_prob": p_market,
        "language": "py",
    })

    RESULTS.mkdir(parents=True, exist_ok=True)
    coef.to_csv(RESULTS / "coef__game__py.csv", index=False)
    metrics.to_csv(RESULTS / "metrics__game__py.csv", index=False)
    cv_metrics.to_csv(RESULTS / "metrics__game_cv__py.csv", index=False)
    pred.to_csv(RESULTS / "gamepred__game__py.csv", index=False)
    print(f"[game/py] holdout Brier={_brier(y, p_model):.4f} "
          f"(naive {_brier(y, p_naive):.4f}, market {_brier(y, p_market):.4f}), "
          f"AUC={roc_auc_score(y, p_model):.3f}, {len(test)} games")


if __name__ == "__main__":
    main()
