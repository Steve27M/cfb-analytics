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
    # Game win-prob feed: one row per FBS-vs-FBS game. Features are HOME-minus-AWAY differences
    # of each side's season-to-date "entering" form (strictly prior games → leakage-safe). The
    # consensus spread is the market benchmark (not a feature); home_won is the target.
    "game_model": """
        with mte as (select * from gold.mart_team_efficiency),
        home as (
            select game_id, std_net_epa_entering, std_off_epa_entering, std_def_epa_entering,
                   roll3_net_epa_entering, std_win_pct_entering, sos_sp_entering,
                   games_played_entering
            from mte where home_away = 'home'
        ),
        away as (
            select game_id, std_net_epa_entering, std_off_epa_entering, std_def_epa_entering,
                   roll3_net_epa_entering, std_win_pct_entering, sos_sp_entering,
                   games_played_entering
            from mte where home_away = 'away'
        )
        select
            g.game_id,
            g.season,
            g.week,
            cast(g.home_won as integer)                             as home_won,
            g.home_spread_consensus,
            h.std_net_epa_entering - a.std_net_epa_entering         as net_epa_diff,
            h.std_off_epa_entering - a.std_off_epa_entering         as off_epa_diff,
            h.std_def_epa_entering - a.std_def_epa_entering         as def_epa_diff,
            h.roll3_net_epa_entering - a.roll3_net_epa_entering     as roll3_net_epa_diff,
            h.std_win_pct_entering - a.std_win_pct_entering         as win_pct_diff,
            h.sos_sp_entering - a.sos_sp_entering                   as sos_diff,
            least(h.games_played_entering, a.games_played_entering) as min_games_entering
        from gold.dim_game g
        inner join home h on g.game_id = h.game_id
        inner join away a on g.game_id = a.game_id
        where g.home_won is not null
          and g.home_spread_consensus is not null
          and least(h.games_played_entering, a.games_played_entering) >= 2
          and h.std_net_epa_entering is not null
          and a.std_net_epa_entering is not null
          and h.roll3_net_epa_entering is not null
          and a.roll3_net_epa_entering is not null
          and h.sos_sp_entering is not null
          and a.sos_sp_entering is not null
    """,
    # Team style profile: one row per FBS team-season, built from play-by-play (the SP+
    # success/explosiveness columns came back empty). Multi-stat identity used for PCA + k-means
    # archetypes (M6): efficiency, success rate, explosiveness, play-calling, pace, havoc.
    "team_profile": """
        with fbs as (select distinct school from gold.dim_team where team_id <> -1),
        off_agg as (
            select
                p.offense_team as team, p.season,
                count(*) filter (where p.is_rush or p.is_pass_attempt)     as off_plays,
                count(distinct p.game_id)                                  as off_games,
                avg(p.epa)                                                 as off_epa_play,
                avg(case when p.is_success then 1.0 else 0.0 end)          as off_success_rate,
                avg(p.epa) filter (where p.is_success)                     as off_explosiveness,
                avg(case when p.is_rush then 1.0 else 0.0 end)
                    filter (where p.is_rush or p.is_pass_attempt)          as rush_rate
            from gold.fct_play p
            inner join fbs on p.offense_team = fbs.school
            where not p.is_garbage_time and (p.is_rush or p.is_pass_attempt)
            group by p.offense_team, p.season
        ),
        def_agg as (
            select
                p.defense_team as team, p.season,
                avg(p.epa)                                                 as def_epa_play,
                avg(case when p.is_success then 1.0 else 0.0 end)          as def_success_rate
            from gold.fct_play p
            inner join fbs on p.defense_team = fbs.school
            where not p.is_garbage_time and (p.is_rush or p.is_pass_attempt)
            group by p.defense_team, p.season
        )
        select
            o.team, o.season,
            o.off_epa_play,
            o.off_success_rate,
            o.off_explosiveness,
            o.rush_rate,
            (o.off_plays * 1.0 / o.off_games)                             as off_pace,
            d.def_epa_play,
            d.def_success_rate
        from off_agg o
        inner join def_agg d on o.team = d.team and o.season = d.season
        where o.off_games >= 8
    """,
    # Expected-points surface: mean cfbfastR EP by field position (yards to goal) and down —
    # the canonical "expected points by field position" curve. Built from the calibrated
    # play-level EPA already in the warehouse (a from-scratch next-score EP model is not rebuilt:
    # it would duplicate this validated EP, and next-score labels reconstructed from the
    # available start-of-play scores are only ~91% exact). This is the play-level EPA view.
    "ep_surface": """
        select
            down,
            yards_to_goal,
            avg(ep_before)      as expected_points,
            count(*)            as n_plays
        from gold.fct_play
        where down between 1 and 4
          and yards_to_goal between 1 and 99
          and ep_before is not null
          and not is_garbage_time
        group by down, yards_to_goal
        having count(*) >= 20
    """,
    # M8: recruiting rank (scraped) vs on-field production. One row per top-25-recruiting
    # team-season, with that season's SP+ rating and win rate — the inputs for "do teams beat
    # their recruiting?" (production regressed on recruiting rank; the residual is over/under-
    # performance).
    "recruiting_production": """
        with wins as (
            select team, season,
                   avg(case when won then 1.0 else 0.0 end) as win_pct,
                   count(*) as games
            from gold.fct_team_game
            where team_sk <> '-1'
            group by team, season
        )
        select
            r.team,
            r.season,
            r.recruiting_rank_247,
            r.recruiting_rank_rivals,
            r.recruiting_rank_on3,
            s.sp_rating,
            w.win_pct
        from staging.stg_wiki__recruiting r
        left join silver.silver_ratings_sp s on r.team = s.team and r.season = s.season
        join wins w on r.team = w.team and r.season = w.season
        where s.sp_rating is not null
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
