"""Market-efficiency evaluation — does the game model carry signal the closing line lacks?

Not a fitted model but a diagnostic on the game win-prob model's own held-out predictions: it
takes the test-set model probabilities alongside the market's implied probabilities and the
realized outcomes, then asks three questions the way a betting analyst would:

  1. Blend      — does any weighted average w*model + (1-w)*market beat the market's Brier alone?
  2. Orthogonal — in a logistic reg of the outcome on BOTH probabilities (as logits), does the
                  model term survive after controlling for the market? (non-zero => new signal)
  3. Disagree   — on the games where model and market diverge most, which one is right?

The honest expectation is that the closing line is near-efficient, so the model's residual edge is
tiny. Reporting that rigorously (a negative result, cleanly measured) is the point.

Reads data/results/gamepred__game__py.csv (written by game_model.py); writes
metrics__market_edge__py.csv and market_blend__py.csv for the dashboard.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.api as sm
from sklearn.metrics import roc_auc_score

from cfb_analytics.config import REPO_ROOT

RESULTS = REPO_ROOT / "data" / "results"
PRED = RESULTS / "gamepred__game__py.csv"


def _brier(y: np.ndarray, p: np.ndarray) -> float:
    return float(np.mean((y - p) ** 2))


def _logloss(y: np.ndarray, p: np.ndarray) -> float:
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def _acc(y: np.ndarray, p: np.ndarray) -> float:
    return float(np.mean((p >= 0.5) == (y == 1)))


def _logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def main() -> None:
    if not PRED.exists():
        raise SystemExit(f"{PRED.name} not found — run the game model (run.py parity) first.")
    df = pd.read_csv(PRED).dropna(subset=["home_win_prob", "market_win_prob", "home_won"])
    y = df["home_won"].to_numpy(dtype=float)
    model = df["home_win_prob"].to_numpy(dtype=float)
    market = df["market_win_prob"].to_numpy(dtype=float)
    n = len(df)

    rows: list[dict] = []

    def rec(metric: str, value: float) -> None:
        rows.append({"model": "market_edge", "metric": metric, "value": value, "language": "py"})

    rec("n_test", n)
    for nm, p in [("model", model), ("market", market)]:
        rec(f"brier_{nm}", _brier(y, p))
        rec(f"logloss_{nm}", _logloss(y, p))
        rec(f"auc_{nm}", float(roc_auc_score(y, p)))
        rec(f"acc_{nm}", _acc(y, p))

    # 1) BLEND — sweep the weight on the model; record the whole curve + the optimum
    ws = np.round(np.linspace(0, 1, 21), 2)
    curve = [{"w": float(w), "brier": _brier(y, w * model + (1 - w) * market)} for w in ws]
    best = min(curve, key=lambda r: r["brier"])
    brier_market = _brier(y, market)
    rec("blend_w_best", best["w"])
    rec("brier_blend_best", best["brier"])
    rec("blend_gain_pct", (1 - best["brier"] / brier_market) * 100)  # vs market alone

    # 2) ORTHOGONALITY — outcome ~ model_logit + market_logit
    x = sm.add_constant(np.column_stack([_logit(model), _logit(market)]))
    res = sm.Logit(y, x).fit(disp=0)
    rec("orth_model_coef", float(res.params[1]))
    rec("orth_model_p", float(res.pvalues[1]))
    rec("orth_market_coef", float(res.params[2]))
    rec("orth_market_p", float(res.pvalues[2]))
    market_only = sm.Logit(y, sm.add_constant(_logit(market))).fit(disp=0)
    rec("prsq_market_only", float(market_only.prsquared))
    rec("prsq_both", float(res.prsquared))

    # 3) DISAGREEMENT — the top quartile by |model - market|, then the opposite-pick subset
    gap = np.abs(model - market)
    thr = float(np.quantile(gap, 0.75))
    mask = gap >= thr
    yd, md, kd = y[mask], model[mask], market[mask]
    rec("disagree_n", int(mask.sum()))
    rec("disagree_gap_thr", thr)
    rec("disagree_model_brier", _brier(yd, md))
    rec("disagree_market_brier", _brier(yd, kd))
    rec("disagree_model_acc", _acc(yd, md))
    rec("disagree_market_acc", _acc(yd, kd))
    opp = (md >= 0.5) != (kd >= 0.5)  # they pick different winners
    if opp.sum():
        yo = yd[opp]
        rec("opp_n", int(opp.sum()))
        rec("opp_model_right", float(np.mean((md[opp] >= 0.5) == (yo == 1))))
        rec("opp_market_right", float(np.mean((kd[opp] >= 0.5) == (yo == 1))))

    RESULTS.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(RESULTS / "metrics__market_edge__py.csv", index=False)
    pd.DataFrame(curve).assign(language="py").to_csv(RESULTS / "market_blend__py.csv", index=False)

    print(f"  market_edge: n={n} · model Brier {_brier(y, model):.4f} vs market {brier_market:.4f} "
          f"· best blend w={best['w']} Brier {best['brier']:.4f} "
          f"· model_logit p={float(res.pvalues[1]):.3f}")


if __name__ == "__main__":
    main()
