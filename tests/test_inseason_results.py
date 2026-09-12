"""Results alignment for the in-season model and the scoreboard.

Regression for the 2026 week-1 Notre Dame–Wisconsin game at Lambeau Field: frozen as
Wisconsin (home) vs Notre Dame, later re-oriented by CFBD to Notre Dame (home) 41, Wisconsin 13.
Attaching homePoints to the frozen home team scored that as a Wisconsin win.
"""
import numpy as np
import pandas as pd
import pytest

from cfb_analytics.inseason import align_results, ridge_ratings

SCHED = pd.DataFrame({
    "game_id": [1, 2, 3, 4, 5],
    "week": [1, 1, 1, 2, 2],
    "start_date": ["2026-09-05T20:00:00.000Z", "2026-09-06T23:30:00.000Z",
                   "2026-09-05T04:00:00.000Z", "2026-09-12T19:30:00.000Z",
                   "2026-09-12T19:30:00.000Z"],
    "neutral_site": [False, True, False, False, False],
    "home_team": ["USC", "Wisconsin", "Illinois", "Notre Dame", "Purdue"],
    "away_team": ["San José State", "Notre Dame", "Northwestern", "Rice", "Ball State"],
})

RESULTS = pd.DataFrame({
    "game_id": [1, 2, 3, 4, 5],
    # game 2: neutral-site host re-designated; game 3: venue moved to the frozen away team;
    # game 5: teams no longer match (renamed / replaced) -> must not settle
    "home_team": ["USC", "Notre Dame", "Northwestern", "Notre Dame", "Purdue"],
    "away_team": ["San José State", "Wisconsin", "Illinois", "Rice", "Somebody Else"],
    "start_date": ["2026-09-05T20:00:00.000Z", "2026-09-06T23:30:00.000Z",
                   "2026-09-05T00:00:00.000Z", None, "2026-09-12T19:30:00.000Z"],
    "home_points": [31, 41, 20, None, 24],
    "away_points": [10, 13, 17, None, 3],
    "completed": [True, True, True, False, True],
})


def test_same_orientation_passes_through():
    out = align_results(SCHED, RESULTS).set_index("game_id")
    g = out.loc[1]
    assert (g.home_points, g.away_points) == (31, 10)
    assert (g.settled, g.flipped, g.home_ind) == (True, False, 1.0)


def test_flipped_neutral_game_is_aligned_by_team():
    out = align_results(SCHED, RESULTS).set_index("game_id")
    g = out.loc[2]
    # frozen home team is Wisconsin, so Wisconsin's score must land in home_points
    assert (g.home_team, g.away_team) == ("Wisconsin", "Notre Dame")
    assert (g.home_points, g.away_points) == (13, 41)
    assert g.home_points < g.away_points      # Notre Dame won
    assert g.settled and g.flipped and g.home_ind == 0.0


def test_flipped_non_neutral_game_moves_home_field_to_the_other_team():
    out = align_results(SCHED, RESULTS).set_index("game_id")
    g = out.loc[3]
    assert (g.home_points, g.away_points) == (17, 20)
    assert g.flipped and g.home_ind == -1.0    # Northwestern actually hosted
    assert g.kickoff == "2026-09-05T00:00:00.000Z"   # CFBD's current kickoff wins


def test_kickoff_falls_back_to_frozen_when_cfbd_has_none():
    out = align_results(SCHED, RESULTS).set_index("game_id")
    assert out.loc[4].kickoff == "2026-09-12T19:30:00.000Z"
    assert not out.loc[4].settled


def test_unmatched_teams_are_left_unsettled(capsys):
    out = align_results(SCHED, RESULTS).set_index("game_id")
    g = out.loc[5]
    assert not g.settled and not g.flipped
    assert pd.isna(g.home_points) and pd.isna(g.away_points)
    assert "no longer match" in capsys.readouterr().out


def test_no_results_means_nothing_settled():
    out = align_results(SCHED, pd.DataFrame(columns=RESULTS.columns))
    assert len(out) == len(SCHED)
    assert not out.settled.any()
    assert list(out.kickoff) == list(SCHED.start_date)
    assert list(out.home_ind) == [1.0, 0.0, 1.0, 1.0, 1.0]


def test_ridge_ratings_are_invariant_to_orientation_with_flipped_host():
    """Encoding a game as (A home, +m, host=A) or (B home, -m, host=A via home_ind=-1) must give
    identical ratings — that is what lets the frozen orientation stay canonical."""
    strength = pd.Series({"A": 0.0, "B": 0.0, "C": 0.0})
    k, gamma, home_adv = 2.0, 1.0, 3.0
    a = pd.DataFrame({"home_team": ["A", "C"], "away_team": ["B", "A"],
                      "home_margin": [10.0, -4.0], "home_ind": [1.0, 1.0]})
    b = pd.DataFrame({"home_team": ["B", "C"], "away_team": ["A", "A"],
                      "home_margin": [-10.0, -4.0], "home_ind": [-1.0, 1.0]})
    ra = ridge_ratings(a, strength, k, gamma, home_adv)
    rb = ridge_ratings(b, strength, k, gamma, home_adv)
    assert np.allclose(ra.to_numpy(), rb.to_numpy())
    assert ra["A"] > ra["B"]


@pytest.mark.parametrize("neutral", [True, False])
def test_flipped_result_counts_as_away_win_for_the_frozen_home_team(neutral):
    sched = SCHED.loc[SCHED.game_id == 2].assign(neutral_site=neutral)
    out = align_results(sched, RESULTS)
    assert bool((out.home_points > out.away_points).iloc[0]) is False
