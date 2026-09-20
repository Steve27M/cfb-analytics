"""cfb_analytics.team_stats — the shared team-stat query and the live-season EPA quality gate."""
import importlib.util
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from cfb_analytics import team_stats as ts

SEASON = 2026


def _warehouse() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(":memory:")
    for schema in ("bronze", "silver", "gold", "staging"):
        con.execute(f"create schema {schema}")
    con.execute("""create table gold.fct_play (game_id int, season int, offense_team varchar,
        defense_team varchar, yards_gained double, epa double, is_rush boolean,
        is_pass_attempt boolean, is_sack boolean, is_garbage_time boolean)""")
    con.execute("""create table gold.dim_game (game_id int, season int, home_team varchar,
        away_team varchar, home_points int, away_points int)""")
    return con


def _season_of_games(con, n: int, sign: float) -> None:
    """n games; the home offense's EPA differential is `sign` x the real margin."""
    for g in range(n):
        margin = (g % 35) - 17 or 3                      # -17..17, never a tie
        con.execute("insert into gold.dim_game values (?, ?, 'H', 'A', ?, ?)",
                    [g, SEASON, 30 + margin, 30])
        con.execute("insert into gold.fct_play values (?, ?, 'H', 'A', 5, ?, true, false, false, false)",
                    [g, SEASON, sign * margin])
        con.execute("insert into gold.fct_play values (?, ?, 'A', 'H', 5, 0, true, false, false, false)",
                    [g, SEASON])


def test_gate_passes_when_epa_tracks_the_scoreboard():
    con = _warehouse()
    _season_of_games(con, 80, +1.0)
    q = ts.epa_quality(con, SEASON)
    assert q["ok"] and q["n_games"] == 80 and q["corr"] > 0.99 and q["winner_agreement"] == 1.0


def test_gate_fails_when_epa_points_the_wrong_way():
    """September 2026: scoring offenses were charged negative EPA. The gate must refuse."""
    con = _warehouse()
    _season_of_games(con, 80, -1.0)
    q = ts.epa_quality(con, SEASON)
    assert not q["ok"] and q["corr"] < 0 and q["winner_agreement"] == 0.0


def test_gate_needs_enough_games_and_ignores_other_seasons():
    con = _warehouse()
    _season_of_games(con, ts.MIN_GAMES - 1, +1.0)
    assert not ts.epa_quality(con, SEASON)["ok"]
    assert ts.epa_quality(con, SEASON - 1) == {
        "season": SEASON - 1, "ok": False, "n_games": 0, "corr": None, "winner_agreement": None,
        "median_abs_error": None,
        "thresholds": {"corr": ts.MIN_CORR, "winner_agreement": ts.MIN_WINNER_AGREEMENT,
                       "games": ts.MIN_GAMES}}


@pytest.fixture
def lane():
    con = _warehouse()
    con.execute("""create table bronze.teams (school varchar, abbreviation varchar,
        conference varchar, color varchar, alt_color varchar, logo varchar, cfb_season int)""")
    con.execute("insert into bronze.teams values ('Alpha','ALP','Big','#111','#222','x', ?)", [SEASON])
    con.execute("""create table silver.silver_ratings_sp (season int, team varchar, sp_rating double,
        sp_ranking int, special_teams_rating double, strength_of_schedule double)""")
    con.execute("insert into silver.silver_ratings_sp values (?, 'Alpha', 12.5, 20, 0.4, null)", [SEASON])
    con.execute("""create table gold.mart_team_efficiency (season int, team varchar,
        offensive_epa_per_play double, defensive_epa_per_play double, offensive_success_rate double,
        defensive_success_rate double, net_epa_per_play double)""")
    con.execute("""create table gold.fct_team_game (season int, team varchar, team_sk varchar,
        opponent varchar, won boolean, points_for int, points_against int)""")
    con.execute("insert into gold.fct_team_game values (?, 'Alpha', 'sk', 'Beta', true, 31, 10)", [SEASON])
    plays = [  # (yards, rush, pass_attempt, sack)
        (12, True, False, False), (20, False, True, False), (-7, False, False, True),
        (40, False, False, False),    # a 40-yard field goal: not offense
        (25, False, False, False)]    # a kickoff return: not offense
    for y, r, p, s in plays:
        con.execute("insert into gold.fct_play values (1, ?, 'Alpha', 'Beta', ?, 0.1, ?, ?, ?, false)",
                    [SEASON, y, r, p, s])
    return con


def test_total_offense_counts_scrimmage_plays_only(lane):
    row = ts.team_stats(lane, SEASON).iloc[0]
    assert row.off_yds == 12 + 20 - 7          # not 90: field-goal distance and returns excluded
    assert (row.wins, row.losses, row.games, row.ppg) == (1, 0, 1, 31)
    assert row.explosiveness == 0.5            # 1 of 2 rush/pass plays gained 15+


def test_a_lane_without_recruiting_or_projections_gets_nulls(lane):
    row = ts.team_stats(lane, SEASON).iloc[0]
    assert pd.isna(row.recruit_rank) and pd.isna(row.proj_2026_wins)
    lane.execute("create table staging.stg_wiki__recruiting (team varchar, season int, recruiting_rank_247 int)")
    lane.execute("insert into staging.stg_wiki__recruiting values ('Alpha', ?, 7)", [SEASON])
    assert ts.team_stats(lane, SEASON).iloc[0].recruit_rank == 7


# ---- what the team profiles are handed
_spec = importlib.util.spec_from_file_location(
    "build_learn", Path(__file__).resolve().parents[1] / "dashboard" / "build_learn.py")
build_learn = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_learn)


def _live(ok: bool) -> dict:
    team = {"name": "Alpha", "abbr": "ALP", "record": "2-0", "games": 2, "pbpGames": 1,
            "spPlus": 12.5, "spRank": 20, "ypg": 410.0, "oppYpg": 300.0, "margins": [21, 3],
            "radar": {"exp": 80.0, "st": 60.0}}
    if ok:
        team.update({"epaOff": 0.2, "epaDef": -0.1, "netEpa": 0.3, "srOff": 48.0, "srDef": 38.0})
        team["radar"].update({"off": 90.0, "def": 70.0, "eff": 85.0})
    return {"season": SEASON, "built_at": "2026-09-20T12:00:00+00:00", "through_week": 3,
            "games_settled": 10, "games_with_pbp": 6, "epa_reference": [],
            "epa_quality": {"ok": ok, "corr": 0.9 if ok else 0.3,
                            "winner_agreement": 0.8 if ok else 0.54, "n_games": 60},
            "teams": [team]}


def test_failed_gate_keeps_every_epa_metric_off_the_live_sheet():
    out = build_learn.build_live(_live(ok=False))
    names = {s["name"] for g in out["groups"] for s in g["stats"]}
    assert names == {"SP+ Rating", "SP+ Rank", "Yards / Game", "Yards Allowed", "Explosiveness",
                     "ST", "EXP"}
    assert "EPA / Play (Off)" in out["withheld"] and "Success Rate % (Off)" in out["withheld"]
    assert out["teams"]["Alpha"]["pbpGames"] == 1 and out["teams"]["Alpha"]["games"] == 2


def test_passing_gate_publishes_the_epa_family():
    out = build_learn.build_live(_live(ok=True))
    names = {s["name"] for g in out["groups"] for s in g["stats"]}
    assert {"EPA / Play (Off)", "Net EPA / Play", "Success Rate % (Def)", "OFF", "DEF", "EFF"} <= names
    assert out["withheld"] == []
