"""dashboard/build_learn.py — the per-stat rankings behind the Stat Guide and the team profiles."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "build_learn", Path(__file__).resolve().parents[1] / "dashboard" / "build_learn.py")
build_learn = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_learn)

TEAMS = [
    {"name": "Alpha", "abbr": "ALP", "ppg": 40.0, "oppPpg": 30.0, "spRank": 2, "winPct": 0.75,
     "record": "9-3", "radar": {"exp": 90.0}, "recruitRank": None},
    {"name": "Bravo", "abbr": "BRV", "ppg": 20.0, "oppPpg": 10.0, "spRank": 1, "winPct": 0.9,
     "record": "11-1", "radar": {"exp": 40.0}, "recruitRank": 5},
    {"name": "Charlie", "abbr": "CHA", "ppg": 30.0, "oppPpg": 20.0, "spRank": 3, "winPct": 0.5,
     "record": "6-6", "radar": {"exp": 60.0}, "recruitRank": None},
]


def names(d):
    return [r["name"] for r in d["ranked"]]


def test_ranked_is_best_to_worst_for_each_direction():
    assert names(build_learn._dist(TEAMS, "ppg", 1, "high")) == ["Alpha", "Charlie", "Bravo"]
    assert names(build_learn._dist(TEAMS, "oppPpg", 1, "low")) == ["Bravo", "Charlie", "Alpha"]
    assert names(build_learn._dist(TEAMS, "spRank", 0, "rank")) == ["Bravo", "Alpha", "Charlie"]


def test_dotted_keys_reach_into_nested_fields():
    d = build_learn._dist(TEAMS, "radar.exp", 0, "high")
    assert names(d) == ["Alpha", "Charlie", "Bravo"] and d["max"] == 90 and d["min"] == 40


def test_display_field_rides_along_and_missing_values_are_left_out():
    d = build_learn._dist(TEAMS, "winPct", 3, "high", "record")
    assert [r["disp"] for r in d["ranked"]] == ["11-1", "9-3", "6-6"]
    r = build_learn._dist(TEAMS, "recruitRank", 0, "rank")
    assert names(r) == ["Bravo"]
    assert build_learn._dist(TEAMS, "nope", 0, "high") is None


def test_every_guide_stat_with_a_key_gets_a_ranking():
    gloss = build_learn.build_glossary(TEAMS)
    keyed = [s for g in gloss["groups"] for s in g["stats"] if "dec" in s]
    assert keyed and all(s["dist"] is None or s["dist"]["ranked"] for s in keyed)
    assert [t["name"] for t in gloss["teams"]] == ["Alpha", "Bravo", "Charlie"]
