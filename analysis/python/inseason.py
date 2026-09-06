"""In-season update model (Python parity of inseason.R).

The preseason priors model predicts a season before it starts; this model UPDATES that forecast
as results arrive, on the same FBS-vs-FBS scope. It is the in-season half of the forecast
scoreboard and is designed to run without the warehouse (only committed model artifacts + the
season's settled scores), so the CI refresh can apply it every game day.

Method — a Bayesian ridge on scoring margins, prior mean = preseason strength:
  1. Preseason strength s_T = the priors model's linear predictor for team T (priors coefficients
     x prior-season SP+, net EPA, win rate), centered within a season. Logit scale.
  2. gamma, home_adv: OLS of home margin on [home_ind, s_home - s_away] (no intercept) over the
     training season(s) — converts logit-scale strength into points and estimates home field.
  3. As-of ratings: before each kickoff, r = gamma*s + delta, where delta solves the ridge
     min sum_g (margin_g - home_adv*home_ind_g - (r_h - r_a))^2 + k * sum_T delta_T^2
     over the games already played. k is "games of trust in the preseason prior": with no games
     r = gamma*s exactly; each game moves a team toward its opponent-adjusted margins.
  4. Win probability: glm(home_won ~ pred_margin), pred_margin = r_h - r_a + home_adv*home_ind.
     k is chosen by training-season deviance over K_GRID; the latest season is the sealed holdout.
Every step is a closed-form solve or an unregularised glm, so R and Python agree to tolerance —
the hyper-parameters (ridge_k, gamma, home_adv) enter the parity gate as coefficient rows.

The preseason-strength and ridge solves live in cfb_analytics.inseason so the CI snapshot applies
exactly the code that was validated here; this script owns the training/holdout protocol.

Reads:  data/gold/team_priors.csv, data/gold/inseason_games.csv, data/results/coef__priors__py.csv
Writes: coef__inseason__py / metrics__inseason__py / metrics__inseason_k__py / gamepred__inseason__py
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

from cfb_analytics.config import REPO_ROOT
from cfb_analytics.inseason import preseason_strength, ridge_ratings  # shared with the CI snapshot

GOLD = REPO_ROOT / "data" / "gold"
RESULTS = REPO_ROOT / "data" / "results"
K_GRID = [1, 2, 3, 4, 6, 8, 12, 16, 24, 32]


def fit_margin_scale(games: pd.DataFrame) -> tuple[float, float]:
    """OLS home_margin ~ 0 + home_ind + ps_diff -> (home_adv, gamma)."""
    X = np.column_stack([games.home_ind.to_numpy(float), games.ps_diff.to_numpy(float)])
    beta, *_ = np.linalg.lstsq(X, games.home_margin.to_numpy(float), rcond=None)
    return float(beta[0]), float(beta[1])


def as_of_pred_margin(games: pd.DataFrame, strength: pd.Series, k: float, gamma: float,
                      home_adv: float) -> np.ndarray:
    """Leakage-safe predicted margin for every game: ratings use only games that kicked off
    strictly earlier (games sorted by start_date; equal kickoffs share the same ratings)."""
    games = games.sort_values(["start_date", "game_id"]).reset_index(drop=True)
    out = np.empty(len(games))
    ratings = ridge_ratings(games.iloc[:0], strength, k, gamma, home_adv)
    seen_until = None
    for i, g in games.iterrows():
        if g.start_date != seen_until:
            ratings = ridge_ratings(games[games.start_date < g.start_date], strength, k, gamma,
                                    home_adv)
            seen_until = g.start_date
        out[i] = ratings[g.home_team] - ratings[g.away_team] + home_adv * g.home_ind
    return out, games


def _fit_glm(x: np.ndarray, y: np.ndarray) -> LogisticRegression:
    m = LogisticRegression(C=np.inf, solver="lbfgs", max_iter=1000, tol=1e-10)
    m.fit(x.reshape(-1, 1), y)
    return m


def _deviance(m: LogisticRegression, x: np.ndarray, y: np.ndarray) -> float:
    p = np.clip(m.predict_proba(x.reshape(-1, 1))[:, 1], 1e-15, 1 - 1e-15)
    return float(-2 * np.sum(y * np.log(p) + (1 - y) * np.log(1 - p)))


def _brier(y: np.ndarray, p: np.ndarray) -> float:
    return float(np.mean((y - p) ** 2))


def _logloss(y: np.ndarray, p: np.ndarray) -> float:
    p = np.clip(p, 1e-15, 1 - 1e-15)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def _games_entering(games: pd.DataFrame) -> pd.Series:
    """min(games already played by home, by away) per game — for phase-of-season reporting."""
    games = games.sort_values(["start_date", "game_id"])
    long = pd.concat([games[["game_id", "start_date", "home_team"]].rename(columns={"home_team": "team"}),
                      games[["game_id", "start_date", "away_team"]].rename(columns={"away_team": "team"})])
    long = long.sort_values(["team", "start_date", "game_id"])
    long["n"] = long.groupby("team").cumcount()
    return long.groupby("game_id").n.min()


def main() -> None:
    tp = pd.read_csv(GOLD / "team_priors.csv")
    games = pd.read_csv(GOLD / "inseason_games.csv")
    pcoef = pd.read_csv(RESULTS / "coef__priors__py.csv")
    b0 = float(pcoef.loc[pcoef.term == "(Intercept)", "estimate"].iloc[0])

    strength = preseason_strength(tp, pcoef)
    games = games.merge(strength.rename(columns={"team": "home_team", "strength": "s_home"}),
                        on=["season", "home_team"])
    games = games.merge(strength.rename(columns={"team": "away_team", "strength": "s_away"}),
                        on=["season", "away_team"])
    games["ps_diff"] = games.s_home - games.s_away
    games["home_ind"] = 1 - games.neutral_site
    games["prior_win_prob"] = 1 / (1 + np.exp(-(b0 + games.ps_diff)))

    holdout_season = int(games.season.max())
    train = games[games.season < holdout_season].copy()
    test = games[games.season == holdout_season].copy()
    home_adv, gamma = fit_margin_scale(train)

    def season_margins(df: pd.DataFrame, k: float) -> pd.DataFrame:
        parts = []
        for s, g in df.groupby("season"):
            st = strength[strength.season == s].set_index("team").strength
            pm, ordered = as_of_pred_margin(g, st, k, gamma, home_adv)
            parts.append(ordered.assign(pred_margin=pm))
        return pd.concat(parts, ignore_index=True)

    # choose k on the training season(s): the win-prob map has 2 parameters and every
    # pred_margin is already computed strictly before its kickoff, so deviance is honest
    grid = []
    for k in K_GRID:
        tr = season_margins(train, k)
        m = _fit_glm(tr.pred_margin.to_numpy(), tr.home_won.to_numpy())
        grid.append(dict(model="inseason_winprob", metric=f"deviance_k{k}", value=_deviance(
            m, tr.pred_margin.to_numpy(), tr.home_won.to_numpy())))
    best_k = K_GRID[int(np.argmin([r["value"] for r in grid]))]

    tr = season_margins(train, best_k)
    final = _fit_glm(tr.pred_margin.to_numpy(), tr.home_won.to_numpy())
    te = season_margins(test, best_k)
    y = te.home_won.to_numpy()
    p_model = final.predict_proba(te.pred_margin.to_numpy().reshape(-1, 1))[:, 1]
    p_prior = te.prior_win_prob.to_numpy()
    p_naive = np.full(len(te), train.home_won.mean())
    entering = te.game_id.map(_games_entering(te))
    late = (entering >= 4).to_numpy()

    coef = pd.DataFrame({
        "model": "inseason_winprob",
        "term": ["(Intercept)", "pred_margin", "ridge_k", "gamma", "home_adv"],
        "estimate": [float(final.intercept_[0]), float(final.coef_[0][0]),
                     float(best_k), gamma, home_adv],
        "language": "py",
    })
    coef["odds_ratio"] = np.where(coef.term.isin(["(Intercept)", "pred_margin"]),
                                  np.exp(coef.estimate), np.nan)
    metrics = pd.DataFrame([
        dict(model="inseason_winprob", metric="brier", value=_brier(y, p_model)),
        dict(model="inseason_winprob", metric="log_loss", value=_logloss(y, p_model)),
        dict(model="inseason_winprob", metric="auc", value=float(roc_auc_score(y, p_model))),
        dict(model="inseason_winprob", metric="accuracy",
             value=float(np.mean((p_model >= 0.5) == (y == 1)))),
        dict(model="inseason_winprob", metric="brier_naive", value=_brier(y, p_naive)),
        dict(model="inseason_winprob", metric="brier_priors", value=_brier(y, p_prior)),
        dict(model="inseason_winprob", metric="accuracy_priors",
             value=float(np.mean((p_prior >= 0.5) == (y == 1)))),
        dict(model="inseason_winprob", metric="brier_from_game4", value=_brier(y[late], p_model[late])),
        dict(model="inseason_winprob", metric="brier_priors_from_game4",
             value=_brier(y[late], p_prior[late])),
        dict(model="inseason_winprob", metric="n_from_game4", value=float(late.sum())),
        dict(model="inseason_winprob", metric="ridge_k", value=float(best_k)),
        dict(model="inseason_winprob", metric="n_test", value=float(len(te))),
        dict(model="inseason_winprob", metric="n_train", value=float(len(tr))),
    ])
    metrics["language"] = "py"
    kgrid = pd.DataFrame(grid)
    kgrid["language"] = "py"
    pred = pd.DataFrame({
        "game_id": te.game_id.values, "season": te.season.values, "week": te.week.values,
        "home_won": y, "pred_margin": te.pred_margin.values, "inseason_win_prob": p_model,
        "prior_win_prob": p_prior, "games_entering_min": entering.values, "language": "py",
    })

    RESULTS.mkdir(parents=True, exist_ok=True)
    coef.to_csv(RESULTS / "coef__inseason__py.csv", index=False)
    metrics.to_csv(RESULTS / "metrics__inseason__py.csv", index=False)
    kgrid.to_csv(RESULTS / "metrics__inseason_k__py.csv", index=False)
    pred.to_csv(RESULTS / "gamepred__inseason__py.csv", index=False)
    print(f"[inseason/py] k={best_k} gamma={gamma:.3f} home_adv={home_adv:.2f} | holdout "
          f"Brier={_brier(y, p_model):.4f} (priors-only {_brier(y, p_prior):.4f}, naive "
          f"{_brier(y, p_naive):.4f}), AUC={roc_auc_score(y, p_model):.3f}, "
          f"from game 4: {_brier(y[late], p_model[late]):.4f} vs priors "
          f"{_brier(y[late], p_prior[late]):.4f}, {len(te)} games")


if __name__ == "__main__":
    main()
