"""inseason.snapshot — seals only validated results, and checks its own output before writing.

End-to-end on a tiny sealed model in a temporary registry: the same code path CI runs.
"""
import json

import pandas as pd
import pytest

from cfb_analytics import inseason, registry
from cfb_analytics.results import RAW_COLS

SEASON = 2026
SCHED = pd.DataFrame({
    "game_id": [1, 2, 3],
    "week": [1, 1, 2],
    "start_date": ["2026-09-05T20:00:00.000Z", "2026-09-06T23:30:00.000Z",
                   "2026-09-12T19:30:00.000Z"],
    "neutral_site": [False, True, False],
    "home_team": ["USC", "Wisconsin", "Notre Dame"],
    "away_team": ["Rice", "Notre Dame", "Rice"],
    "home_win_prob": [0.8, 0.25, 0.9], "favored_team": ["USC", "Notre Dame", "Notre Dame"],
    "favored_win_prob": [0.8, 0.75, 0.9], "forecast_season": [SEASON] * 3,
})
TEAMS = ["USC", "Rice", "Wisconsin", "Notre Dame"]


def raw(rows) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=RAW_COLS)


def game(game_id, home, away, hp=None, ap=None, completed=False, start=None, neutral=False,
         week=1):
    return {"game_id": game_id, "week": week, "start_date": start, "start_time_tbd": False,
            "neutral_site": neutral, "home_team": home, "away_team": away,
            "home_points": hp, "away_points": ap, "completed": completed,
            "home_postgame_wp": None}


# CFBD after week 1: Notre Dame re-designated as the neutral-site home team and won 41-13
WEEK1 = raw([
    game(1, "USC", "Rice", 31, 10, True, "2026-09-05T20:00:00.000Z"),
    game(2, "Notre Dame", "Wisconsin", 41, 13, True, "2026-09-06T23:30:00.000Z", neutral=True),
    game(3, "Notre Dame", "Rice", None, None, False, "2026-09-12T19:30:00.000Z", week=2),
])


@pytest.fixture
def model(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "PREDICTIONS_DIR", tmp_path)
    monkeypatch.setattr(inseason, "PREDICTIONS_DIR", tmp_path)
    root = tmp_path / str(SEASON)
    v1 = root / "v1-preseason"
    v1.mkdir(parents=True)
    SCHED.to_csv(v1 / f"forecast_{SEASON}.csv", index=False)
    v2 = root / "v2-inseason"
    v2.mkdir()
    pd.DataFrame({"term": ["(Intercept)", "pred_margin", "ridge_k", "gamma", "home_adv"],
                  "estimate": [0.0, 0.15, 2.0, 12.0, 3.0]}).to_csv(
        v2 / "coef__inseason__r.csv", index=False)
    pd.DataFrame({"team": TEAMS, "strength": [0.5, -1.0, -0.2, 1.2]}).assign(
        prior_rating=lambda d: 12.0 * d.strength, prior_rank=[2, 4, 3, 1]).to_csv(
        v2 / "team_prior_strength.csv", index=False)
    (v2 / "manifest.json").write_text(json.dumps({
        "version": "v2-inseason", "kind": "series",
        "generated_at": "2026-09-01T00:00:00+00:00"}), encoding="utf-8")
    return v2


def _teams(snap):
    return pd.read_csv(snap / f"forecast_{SEASON}_teams.csv").set_index("team")


def test_snapshot_scores_the_mirrored_game_for_the_right_team(model):
    snap = inseason.snapshot(SEASON, "v2-inseason", results=WEEK1)
    assert snap is not None and snap.parent == model / "snapshots"
    t = _teams(snap)
    assert (t.loc["Notre Dame", "wins"], t.loc["Notre Dame", "losses"]) == (1, 0)
    assert (t.loc["Wisconsin", "wins"], t.loc["Wisconsin", "losses"]) == (0, 1)
    assert t.loc["Notre Dame", "rating"] > t.loc["Notre Dame", "prior_rating"]
    assert t.loc["Wisconsin", "rating"] < t.loc["Wisconsin", "prior_rating"]
    m = json.loads((snap / "manifest.json").read_text(encoding="utf-8"))
    assert m["results_validation"]["ok"]
    assert "winner-by-name" in m["results_validation"]["hard_checks"]
    assert m["schedule_drift"]["mirrored"] == 1 and m["n_settled"] == 2
    g = pd.read_csv(snap / f"forecast_{SEASON}.csv").set_index("game_id")
    assert list(g.home_team) == list(SCHED.home_team)       # frozen orientation preserved


def test_quiet_day_seals_nothing(model):
    first = inseason.snapshot(SEASON, "v2-inseason", results=WEEK1)
    assert first is not None
    assert inseason.snapshot(SEASON, "v2-inseason", results=WEEK1) is None
    assert [p.name for p in (model / "snapshots").iterdir()] == [first.name]


def test_quarantined_results_are_refused(model, capsys):
    tie = WEEK1.copy()
    tie.loc[tie.game_id == 1, ["home_points", "away_points"]] = [21, 21]
    assert inseason.snapshot(SEASON, "v2-inseason", results=tie) is None
    assert not (model / "snapshots").exists()
    out = capsys.readouterr().out
    assert "QUARANTINED" in out and "refusing to seal" in out


def test_no_results_yet_writes_a_prior_only_snapshot(model):
    snap = inseason.snapshot(SEASON, "v2-inseason", results=raw([]))
    assert snap is not None
    t = _teams(snap)
    assert (t.wins == 0).all() and (t.rating == t.prior_rating).all()


def test_check_snapshot_catches_a_projection_outside_the_record():
    sched = pd.DataFrame({"home_win_prob": [0.6]})
    teams = pd.DataFrame({"team": ["A", "B"], "games": [1, 1], "wins": [1, 0], "losses": [0, 1],
                          "remaining": [0, 0], "projected_wins": [1.4, 0.0],
                          "rating": [1.0, -1.0]})
    played = pd.DataFrame({"home_team": ["A"], "away_team": ["B"], "home_margin": [7.0]})
    with pytest.raises(SystemExit, match="projected_wins outside"):
        inseason.check_snapshot(sched, teams, played)


def test_check_snapshot_catches_a_record_that_disagrees_with_the_games():
    sched = pd.DataFrame({"home_win_prob": [0.6]})
    teams = pd.DataFrame({"team": ["A", "B"], "games": [1, 1], "wins": [0, 1], "losses": [1, 0],
                          "remaining": [0, 0], "projected_wins": [0.0, 1.0],
                          "rating": [1.0, -1.0]})
    played = pd.DataFrame({"home_team": ["A"], "away_team": ["B"], "home_margin": [7.0]})
    with pytest.raises(SystemExit, match="disagree with the settled games"):
        inseason.check_snapshot(sched, teams, played)


def test_check_snapshot_passes_a_consistent_snapshot():
    sched = pd.DataFrame({"home_win_prob": [0.6, 0.3]})
    teams = pd.DataFrame({"team": ["A", "B"], "games": [2, 2], "wins": [1, 0], "losses": [0, 1],
                          "remaining": [1, 1], "projected_wins": [1.7, 0.3],
                          "rating": [1.0, -1.0]})
    played = pd.DataFrame({"home_team": ["A"], "away_team": ["B"], "home_margin": [7.0]})
    inseason.check_snapshot(sched, teams, played)
