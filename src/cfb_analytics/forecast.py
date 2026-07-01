"""Forecast an upcoming (unplayed) season with the preseason priors model.

The core pipeline models completed seasons; this applies the trained priors model to a FUTURE
schedule. It pulls the target season's schedule from CFBD (the sanctioned API — no scraping), pairs
each game with both teams' PRIOR-season priors already in the warehouse (SP+ rating, net EPA, win
rate), and scores it with the committed priors_winprob coefficients (R and Python agree on them, so
applying them is language-agnostic). Writes gold.forecast_<season> + a CSV under data/gold/.

    uv run python -m cfb_analytics.forecast 2026
"""
from __future__ import annotations

import os
import sys

import duckdb
import numpy as np
import pandas as pd
import requests

from .config import DUCKDB_PATH, REPO_ROOT
from .db import read_only_conn

CFBD_GAMES_URL = "https://api.collegefootballdata.com/games"
GOLD_DIR = REPO_ROOT / "data" / "gold"


def _schedule(season: int) -> pd.DataFrame:
    key = os.getenv("CFBD_API_KEY")
    if not key:
        raise SystemExit("CFBD_API_KEY not set (.env) — needed to pull the schedule")
    resp = requests.get(CFBD_GAMES_URL, params={"year": str(season), "seasonType": "regular"},
                        headers={"Authorization": f"Bearer {key}"}, timeout=60)
    resp.raise_for_status()
    games = resp.json()
    return pd.DataFrame([{
        "game_id": g["id"], "week": g.get("week"), "start_date": g.get("startDate"),
        "neutral_site": g.get("neutralSite"),
        "home_team": g.get("homeTeam"), "away_team": g.get("awayTeam"),
    } for g in games])


def forecast(season: int) -> pd.DataFrame:
    prior = season - 1
    con = read_only_conn()
    try:
        priors = con.execute(f"""
            with eff as (
                select team, avg(net_epa_per_play) as net_epa,
                       avg(case when won then 1.0 else 0.0 end) as win_pct
                from gold.mart_team_efficiency where season = {prior} group by team
            )
            select r.team, r.sp_rating, e.net_epa, e.win_pct
            from silver.silver_ratings_sp r
            join eff e on r.team = e.team
            where r.season = {prior} and r.sp_rating is not null
        """).fetch_df()
        coef = con.execute("""
            select term, estimate from gold.model_coefficients
            where model = 'priors_winprob' and language = 'r'
        """).fetch_df()
    finally:
        con.close()

    b = dict(zip(coef.term, coef.estimate, strict=True))
    p = priors.set_index("team")
    sched = _schedule(season)

    # keep games where BOTH teams have prior-season priors (FBS matchups); FCS opponents drop out
    sched = sched[sched.home_team.isin(p.index) & sched.away_team.isin(p.index)].copy()

    def diff(col: str) -> np.ndarray:
        return (sched.home_team.map(p[col]).to_numpy()
                - sched.away_team.map(p[col]).to_numpy())

    z = (b["(Intercept)"]
         + b["prior_sp_diff"] * diff("sp_rating")
         + b["prior_net_epa_diff"] * diff("net_epa")
         + b["prior_win_pct_diff"] * diff("win_pct"))
    sched["home_win_prob"] = 1.0 / (1.0 + np.exp(-z))
    sched["favored_team"] = np.where(sched.home_win_prob >= 0.5, sched.home_team, sched.away_team)
    sched["favored_win_prob"] = np.where(sched.home_win_prob >= 0.5,
                                         sched.home_win_prob, 1 - sched.home_win_prob)
    sched["forecast_season"] = season

    GOLD_DIR.mkdir(parents=True, exist_ok=True)
    out_csv = GOLD_DIR / f"forecast_{season}.csv"
    sched.to_csv(out_csv, index=False)

    con = duckdb.connect(str(DUCKDB_PATH))
    try:
        con.execute("CREATE SCHEMA IF NOT EXISTS gold")
        con.register("_f", sched)
        con.execute(f"CREATE OR REPLACE TABLE gold.forecast_{season} AS SELECT * FROM _f")
    finally:
        con.close()

    print(f"  gold.forecast_{season}: {len(sched):,} FBS-vs-FBS games scored "
          f"(preseason priors; prior season {prior})")
    return sched


if __name__ == "__main__":
    yr = int(sys.argv[1]) if len(sys.argv) > 1 else 2026
    forecast(yr)
