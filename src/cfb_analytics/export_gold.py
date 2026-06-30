"""Export gold tables to data/gold/*.csv — the model-input side of the polyglot contract.

R and Python communicate ONLY through flat files + the warehouse (never in-memory). This step
reads the served gold/silver tables and writes analysis-ready CSV feeds that BOTH the R
(analysis/R/*.R) and Python (analysis/python/*.py) implementations of the book's models read.
Keeping the feed identical for both languages is what makes the R-vs-Python parity check fair.

Feeds:
  plays_model        one row per non-garbage FBS scrimmage play, with the situational features
                     RYOE (rush) and CPOE (pass) regress on + the actual outcomes. Enriched with
                     the opponent defense's SP+ rating as the "defense quality" control (M3).
  player_rushing     mart_player_rushing — per-rusher-season production + split-half inputs (M1).
  team_game_passing  one row per team-game: passing-TD counts + exposure for the Poisson model (M5).
"""
from __future__ import annotations

from pathlib import Path

from .config import REPO_ROOT
from .db import read_only_conn

GOLD_DIR = REPO_ROOT / "data" / "gold"

# Each feed is a (name -> SQL) pair; the result is written to data/gold/<name>.csv.
# Booleans are cast to integer 0/1 so the CSV round-trips cleanly into both R and pandas.
FEEDS: dict[str, str] = {
    "plays_model": """
        with fbs as (select distinct school from gold.dim_team where team_id <> -1),
        ratings as (select season, team, sp_rating, defense_rating from silver.silver_ratings_sp)
        select
            p.play_key,
            p.game_id,
            p.season,
            p.week,
            p.offense_team,
            p.defense_team,
            p.rusher_player_name,
            p.passer_player_name,
            p.receiver_player_name,
            p.down,
            p.distance,
            p.yards_to_goal,
            p.offense_score_diff_start,
            p.period,
            cast(p.is_goal_to_go as integer)        as is_goal_to_go,
            cast(p.is_rush as integer)              as is_rush,
            cast(p.is_pass as integer)              as is_pass,
            cast(p.is_pass_attempt as integer)      as is_pass_attempt,
            cast(p.is_completion as integer)        as is_completion,
            p.rush_yards,
            p.receiving_yards,
            p.yards_gained,
            p.epa,
            r.sp_rating                             as defense_sp_rating,
            r.defense_rating                        as defense_def_rating
        from gold.fct_play p
        inner join fbs on p.offense_team = fbs.school
        left join ratings r on p.defense_team = r.team and p.season = r.season
        where not p.is_garbage_time
          and (p.is_rush or p.is_pass_attempt)
    """,
    "player_rushing": """
        select * from gold.mart_player_rushing
    """,
    "team_game_passing": """
        with fbs as (select distinct school from gold.dim_team where team_id <> -1),
        ratings as (select season, team, defense_rating from silver.silver_ratings_sp)
        select
            p.game_id,
            p.season,
            p.week,
            p.offense_team,
            p.defense_team,
            count(*) filter (where p.is_pass_attempt)               as pass_attempts,
            sum(cast(p.is_completion as integer))                   as completions,
            sum(case when p.is_pass and p.is_touchdown then 1 else 0 end) as passing_tds,
            avg(p.epa) filter (where p.is_pass_attempt)             as pass_epa_per_attempt,
            r.defense_rating                                        as opponent_defense_rating
        from gold.fct_play p
        inner join fbs on p.offense_team = fbs.school
        left join ratings r on p.defense_team = r.team and p.season = r.season
        where not p.is_garbage_time
        group by p.game_id, p.season, p.week, p.offense_team, p.defense_team, r.defense_rating
        having count(*) filter (where p.is_pass_attempt) > 0
    """,
}


def export(out_dir: Path = GOLD_DIR) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    con = read_only_conn()
    try:
        for name, sql in FEEDS.items():
            df = con.execute(sql).fetch_df()
            path = out_dir / f"{name}.csv"
            df.to_csv(path, index=False)
            print(f"  data/gold/{name + '.csv':24s} {len(df):>8,} rows  {df.shape[1]} cols")
    finally:
        con.close()


if __name__ == "__main__":
    export()
