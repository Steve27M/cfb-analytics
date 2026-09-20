"""Team-season stats from the warehouse, and the source-quality gate for a live season.

One query, two lanes. The sealed lane (data/cfb.duckdb, complete seasons) feeds the comparison
page, the Stat Guide and the 2025 team profiles. The live lane (data/cfb_live.duckdb, built by
`run.py live` from the in-progress season with the SAME dbt models) feeds the 2026 team profiles.
Sharing the SQL is what makes a 2026 number mean exactly what its 2025 counterpart means.

The live lane has one more job: deciding whether the in-progress season's EPA can be trusted.
cfbfastR publishes play-by-play during the season, and its expected-points columns are revised
as the season goes on — in September 2026 the feed's EPA margins named the actual winner in 54%
of games, a coin flip, against 80% for 2023 and 2024. Success rate is derived from the same EPA
values (it matches EPA > 0 on ~90% of plays), so it inherits the problem; yardage does not.
`epa_quality` measures this on every refresh and the pages withhold EPA-family metrics until it
passes, rather than publish numbers that contradict the scoreboard.
"""
from __future__ import annotations

import duckdb
import pandas as pd

# A season's EPA is usable when, over its settled games, the EPA differential between the two
# offenses tracks the final score. Sealed seasons: corr 0.84 / 0.84 / 0.69 and winner agreement
# 0.80 / 0.80 / 0.73 (2023 / 2024 / 2025). The thresholds sit just under the weakest sealed season.
MIN_CORR = 0.60
MIN_WINNER_AGREEMENT = 0.70
MIN_GAMES = 50

# Stats that are EPA, or are computed from it; withheld together when the gate fails.
EPA_FAMILY = ("epa_off", "epa_def", "net_epa", "sr_off", "sr_def")


def _has(con: duckdb.DuckDBPyConnection, schema: str, table: str) -> bool:
    res = con.execute(
        "select count(*) from information_schema.tables where table_schema = ? and table_name = ?",
        [schema, table]).fetchone()
    return bool(res and res[0])


def epa_quality(con: duckdb.DuckDBPyConnection, season: int) -> dict:
    """Does this season's EPA agree with what actually happened? Per settled game, the summed
    EPA of the home offense minus the away offense is compared with the final margin."""
    row = con.execute("""
        with e as (
            select game_id, offense_team as team, sum(epa) as epa_sum
            from gold.fct_play
            where season = ? and epa is not null and (is_rush or is_pass_attempt)
            group by 1, 2
        ),
        g as (
            select game_id, home_team, away_team, home_points - away_points as margin
            from gold.dim_game
            where season = ? and home_points is not null and away_points is not null
                  and home_points <> away_points
        )
        select count(*) as n,
               corr(eh.epa_sum - ea.epa_sum, g.margin) as r,
               avg(case when sign(eh.epa_sum - ea.epa_sum) = sign(g.margin) then 1.0 else 0.0 end),
               median(abs((eh.epa_sum - ea.epa_sum) - g.margin))
        from g
        join e eh on g.game_id = eh.game_id and eh.team = g.home_team
        join e ea on g.game_id = ea.game_id and ea.team = g.away_team
    """, [season, season]).fetchone() or (0, None, None, None)
    n = int(row[0] or 0)
    corr = None if row[1] is None or pd.isna(row[1]) else round(float(row[1]), 3)
    agree = None if row[2] is None else round(float(row[2]), 3)
    ok = bool(n >= MIN_GAMES and corr is not None and agree is not None
              and corr >= MIN_CORR and agree >= MIN_WINNER_AGREEMENT)
    return {"season": season, "ok": ok, "n_games": n, "corr": corr, "winner_agreement": agree,
            "median_abs_error": None if row[3] is None else round(float(row[3]), 1),
            "thresholds": {"corr": MIN_CORR, "winner_agreement": MIN_WINNER_AGREEMENT,
                           "games": MIN_GAMES}}


def team_stats(con: duckdb.DuckDBPyConnection, season: int) -> pd.DataFrame:
    """One row per FBS team for <season>: identity, SP+, efficiency, record and scoring (all
    games), yardage, explosive-play rate, recruiting rank, projected wins, schedule strength.
    Recruiting and the 2026 projection are optional tables: a lane without them gets nulls."""
    rk = ("select team, recruiting_rank_247 from staging.stg_wiki__recruiting "
          f"where season = {season}" if _has(con, "staging", "stg_wiki__recruiting")
          else "select null::varchar as team, null::integer as recruiting_rank_247 where false")
    proj = ("select team, projected_wins from gold.forecast_2026_teams"
            if _has(con, "gold", "forecast_2026_teams")
            else "select null::varchar as team, null::double as projected_wins where false")
    return con.execute(f"""
        with base as (
            select school as team, abbreviation as abbr, conference,
                   color as primary, alt_color as secondary, logo
            from bronze.teams where cfb_season = {season}
        ),
        sp as (
            select team, sp_rating, sp_ranking, special_teams_rating, strength_of_schedule
            from silver.silver_ratings_sp where season = {season}
        ),
        eff as (
            select team, avg(offensive_epa_per_play) epa_off, avg(defensive_epa_per_play) epa_def,
                   avg(offensive_success_rate) sr_off, avg(defensive_success_rate) sr_def,
                   avg(net_epa_per_play) net_epa
            from gold.mart_team_efficiency where season = {season} group by team
        ),
        rec as (
            select team, sum(case when won then 1 else 0 end) wins,
                   sum(case when not won then 1 else 0 end) losses,
                   avg(points_for) ppg, avg(points_against) opp_ppg, count(*) games
            from gold.fct_team_game where season = {season} and team_sk <> '-1' group by team
        ),
        -- total offense = scrimmage plays only (rushes, pass attempts, sacks). Summing every
        -- play's yards_gained also counts field-goal distance (~36 "yards" an attempt), kickoff
        -- and punt returns and penalty yardage, which inflated yards/game by ~90 (FBS median
        -- 522 instead of 401).
        oy as (select offense_team team, sum(yards_gained) yds from gold.fct_play
               where season = {season} and (is_rush or is_pass_attempt or is_sack) group by 1),
        dy as (select defense_team team, sum(yards_gained) yds from gold.fct_play
               where season = {season} and (is_rush or is_pass_attempt or is_sack) group by 1),
        expl as (   -- explosive-play rate (share of plays gaining 15+ yards)
            select offense_team team,
                   avg(case when yards_gained >= 15 then 1.0 else 0.0 end) exp
            from gold.fct_play
            where season = {season} and (is_rush or is_pass_attempt) and not is_garbage_time
            group by 1
        ),
        rk as ({rk}),
        proj as ({proj}),
        sos as (   -- strength of schedule = mean SP+ rating of opponents faced (SP+ SoS is null)
            select tg.team, avg(opp.sp_rating) as opp_sp
            from gold.fct_team_game tg
            join silver.silver_ratings_sp opp on tg.opponent = opp.team and opp.season = {season}
            where tg.season = {season} and tg.team_sk <> '-1'
            group by tg.team
        )
        select base.*, sp.sp_rating, sp.sp_ranking, sp.special_teams_rating,
               eff.epa_off, eff.epa_def, eff.sr_off, eff.sr_def, eff.net_epa,
               rec.wins, rec.losses, rec.ppg, rec.opp_ppg, rec.games,
               oy.yds as off_yds, dy.yds as def_yds, expl.exp as explosiveness,
               rk.recruiting_rank_247 as recruit_rank, proj.projected_wins as proj_2026_wins,
               sos.opp_sp as sos_metric
        from base
        join rec on base.team = rec.team
        left join sp on base.team = sp.team
        left join eff on base.team = eff.team
        left join oy on base.team = oy.team
        left join dy on base.team = dy.team
        left join expl on base.team = expl.team
        left join rk on base.team = rk.team
        left join proj on base.team = proj.team
        left join sos on base.team = sos.team
    """).fetch_df()
