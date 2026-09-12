"""cfb_analytics.results — reconcile the live CFBD listing against the frozen schedule, validate.

Each test is one way the live schedule has drifted (or a feed can be wrong) and the behaviour
the gates must show. The frozen schedule is the key space; everything else is live.
"""
from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from cfb_analytics.results import RAW_COLS, reconcile, validate

NOW = datetime(2026, 9, 13, 12, 0, tzinfo=UTC)

SCHED = pd.DataFrame({
    "game_id": [1, 2, 3, 4, 5, 6],
    "week": [1, 1, 1, 2, 2, 3],
    "start_date": ["2026-09-05T20:00:00.000Z", "2026-09-06T23:30:00.000Z",
                   "2026-09-05T04:00:00.000Z", "2026-09-12T19:30:00.000Z",
                   "2026-09-12T19:30:00.000Z", "2026-09-19T04:00:00.000Z"],
    "neutral_site": [False, True, False, False, False, False],
    "home_team": ["USC", "Wisconsin", "Illinois", "Notre Dame", "Purdue", "Iowa"],
    "away_team": ["San José State", "Notre Dame", "Northwestern", "Rice", "Ball State", "Nevada"],
})


def raw(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=RAW_COLS)


def game(game_id, home, away, hp=None, ap=None, completed=False, start=None, week=1,
         neutral=False, wp=None, tbd=False) -> dict:
    return {"game_id": game_id, "week": week, "start_date": start, "start_time_tbd": tbd,
            "neutral_site": neutral, "home_team": home, "away_team": away,
            "home_points": hp, "away_points": ap, "completed": completed,
            "home_postgame_wp": wp}


CLEAN = raw([
    game(1, "USC", "San José State", 31, 10, True, "2026-09-05T20:00:00.000Z", wp=0.99),
    # mirrored neutral-site host, Notre Dame won
    game(2, "Notre Dame", "Wisconsin", 41, 13, True, "2026-09-06T23:30:00.000Z", neutral=True,
         wp=0.91),
    # moved to Northwestern's field, kickoff moved earlier
    game(3, "Northwestern", "Illinois", 20, 17, True, "2026-09-05T00:00:00.000Z", wp=0.7),
    game(4, "Notre Dame", "Rice", None, None, False, "2026-09-12T19:30:00.000Z", week=2),
    # game 5 is gone from CFBD; game 6 was re-created under a new id (postponement)
    game(60, "Iowa", "Nevada", None, None, False, "2026-09-26T23:00:00.000Z", week=4, tbd=False),
    # an unrelated FCS game CFBD also lists
    game(999, "North Dakota State", "Montana", 28, 24, True, "2026-09-05T20:00:00.000Z"),
])


# ----------------------------------------------------------------------------- reconcile
def test_reconcile_statuses_cover_every_drift_case():
    out, drift = reconcile(SCHED, CLEAN)
    st = out.set_index("game_id").status
    assert st.to_dict() == {1: "same", 2: "mirrored", 3: "mirrored", 4: "same", 5: "missing",
                            6: "rekeyed"}
    assert drift["n_listed"] == 5 and drift["n_frozen"] == 6
    assert [r["id"] for r in drift["mirrored"]] == [2, 3]
    assert drift["rekeyed"][0]["cfbd_id"] == 60
    assert [r["id"] for r in drift["missing"]] == [5]


def test_mirrored_neutral_game_scores_by_team():
    out, _ = reconcile(SCHED, CLEAN)
    g = out.set_index("game_id").loc[2]
    assert (g.home_team, g.away_team) == ("Wisconsin", "Notre Dame")   # frozen orientation kept
    assert (g.home_points, g.away_points) == (13, 41)                  # Wisconsin's score is home
    assert g.settled and g.flipped and g.home_ind == 0.0


def test_moved_non_neutral_game_flips_home_field_and_uses_live_kickoff():
    out, _ = reconcile(SCHED, CLEAN)
    g = out.set_index("game_id").loc[3]
    assert (g.home_points, g.away_points) == (17, 20)
    assert g.home_ind == -1.0
    assert g.kickoff == "2026-09-05T00:00:00.000Z" and g.kickoff_moved


def test_rekeyed_game_keeps_frozen_id_and_takes_live_attributes():
    out, _ = reconcile(SCHED, CLEAN)
    g = out.set_index("game_id").loc[6]
    assert g.cfbd_id == 60 and g.status == "rekeyed"
    assert g.kickoff == "2026-09-26T23:00:00.000Z"
    assert g.cfbd_week == 4 and not g.settled


def test_rekey_requires_exactly_one_candidate():
    two = pd.concat([CLEAN, raw([game(61, "Nevada", "Iowa", None, None, False,
                                      "2026-11-01T00:00:00.000Z", week=9)])])
    out, drift = reconcile(SCHED, two)
    assert out.set_index("game_id").loc[6].status == "missing"
    assert not drift["rekeyed"]


def test_rekey_never_steals_a_game_another_frozen_id_owns():
    # frozen game 5 (Purdue–Ball State) vanished; CFBD's 4 is Notre Dame–Rice, which frozen 4
    # already owns; nothing else matches -> missing, not a false match
    out, _ = reconcile(SCHED, CLEAN)
    assert out.set_index("game_id").loc[5].status == "missing"


def test_changed_pairing_is_never_settled():
    swapped = CLEAN.copy()
    swapped.loc[swapped.game_id == 1, "away_team"] = "Somebody Else"
    out, drift = reconcile(SCHED, swapped)
    g = out.set_index("game_id").loc[1]
    assert g.status == "changed" and not g.settled
    assert pd.isna(g.home_points) and pd.isna(g.away_points)
    assert drift["changed"][0]["cfbd_away"] == "Somebody Else"


def test_missing_game_falls_back_to_frozen_attributes():
    out, _ = reconcile(SCHED, CLEAN)
    g = out.set_index("game_id").loc[5]
    assert g.kickoff == "2026-09-12T19:30:00.000Z" and g.home_ind == 1.0 and not g.settled


def test_empty_raw_frame_means_nothing_settled_and_no_drift():
    out, drift = reconcile(SCHED, raw([]))
    assert not out.settled.any() and (out.status == "unknown").all()
    assert not drift["missing"]                       # no listing is not the same as dropped
    assert list(out.kickoff) == list(SCHED.start_date)
    assert drift["n_listed"] == 0 and not drift["mirrored"] and not drift["kickoff_moved"]


# ----------------------------------------------------------------------------- validate
def test_clean_pull_passes_every_hard_check():
    out, _ = reconcile(SCHED, CLEAN)
    rep = validate(out, CLEAN, now=NOW)
    assert rep["ok"] and rep["n_settled"] == 3
    hard = {c["id"]: c["ok"] for c in rep["checks"] if c["severity"] == "hard"}
    assert hard == {"winner-by-name": True, "team-records": True, "settled-after-kick": True,
                    "no-ties": True, "points-sane": True, "unique-ids": True}
    soft = {c["id"]: c for c in rep["checks"] if c["severity"] == "soft"}
    assert soft["cfbd-wp-agrees"]["ok"]
    assert soft["missing-games"]["n"] == 1 and soft["rekeyed-games"]["n"] == 1
    assert soft["kickoff-moved"]["n"] == 2   # game 3 moved, game 6 re-keyed with a new time


def test_the_original_bug_is_caught_as_a_hard_failure():
    """Simulate the pre-fix pipeline: points attached to the frozen home team regardless of
    CFBD's orientation. The winner-by-name and team-records gates must both trip."""
    out, _ = reconcile(SCHED, CLEAN)
    broken = out.copy()
    m = broken.game_id == 2
    broken.loc[m, ["home_points", "away_points"]] = [41, 13]   # Wisconsin "wins"
    rep = validate(broken, CLEAN, now=NOW)
    assert not rep["ok"]
    failed = {c["id"] for c in rep["checks"] if not c["ok"] and c["severity"] == "hard"}
    assert failed == {"winner-by-name", "team-records"}
    detail = next(c["detail"] for c in rep["checks"] if c["id"] == "team-records")
    assert "Notre Dame" in detail and "Wisconsin" in detail


def test_result_before_kickoff_is_a_hard_failure():
    early = CLEAN.copy()
    early.loc[early.game_id == 4, ["home_points", "away_points", "completed"]] = [52, 0, True]
    out, _ = reconcile(SCHED, early)
    rep = validate(out, early, now=datetime(2026, 9, 12, 18, 0, tzinfo=UTC))
    assert not rep["ok"]
    assert next(c for c in rep["checks"] if c["id"] == "settled-after-kick")["n"] == 1


def test_tie_and_absurd_scores_are_hard_failures():
    bad = CLEAN.copy()
    bad.loc[bad.game_id == 1, ["home_points", "away_points"]] = [21, 21]
    bad.loc[bad.game_id == 3, ["home_points", "away_points"]] = [150, 120]
    out, _ = reconcile(SCHED, bad)
    rep = validate(out, bad, now=NOW)
    ids = {c["id"] for c in rep["checks"] if not c["ok"] and c["severity"] == "hard"}
    assert {"no-ties", "points-sane"} <= ids


def test_duplicate_cfbd_id_is_a_hard_failure():
    out, _ = reconcile(SCHED, CLEAN)
    out.loc[out.game_id == 4, "cfbd_id"] = 1
    rep = validate(out, CLEAN, now=NOW)
    assert next(c for c in rep["checks"] if c["id"] == "unique-ids")["n"] == 1


def test_postgame_wp_disagreement_is_only_a_soft_note():
    odd = CLEAN.copy()
    odd.loc[odd.game_id == 1, "home_postgame_wp"] = 0.2     # USC won but CFBD's wp says no
    out, _ = reconcile(SCHED, odd)
    rep = validate(out, odd, now=NOW)
    assert rep["ok"]
    assert next(c for c in rep["checks"] if c["id"] == "cfbd-wp-agrees")["n"] == 1


def test_postgame_wp_is_read_in_cfbd_orientation_for_mirrored_games():
    out, _ = reconcile(SCHED, CLEAN)
    rep = validate(out, CLEAN, now=NOW)
    assert next(c for c in rep["checks"] if c["id"] == "cfbd-wp-agrees")["ok"]


def test_no_results_validates_trivially():
    out, _ = reconcile(SCHED, raw([]))
    rep = validate(out, raw([]), now=NOW)
    assert rep["ok"] and rep["n_settled"] == 0


@pytest.mark.parametrize("minutes", [0, 4])
def test_settled_after_kick_tolerates_clock_skew(minutes):
    late = CLEAN.copy()
    kick = (NOW + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    late.loc[late.game_id == 1, "start_date"] = kick
    out, _ = reconcile(SCHED, late)
    assert validate(out, late, now=NOW)["ok"]
