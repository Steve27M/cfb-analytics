"""cfb_analytics.reference — the check that would have caught the yards bug.

The bug it exists for: total offense was published ~3% high (12% for the worst team) for months
and passed every structural test, because a wrong number is still a well-formed number. These
tests prove the check fails on exactly that shape of error and passes on honest data.
"""
import duckdb
import pandas as pd
import pytest

from cfb_analytics import reference as ref

SEASON = 2025
TEAMS = [f"Team {i:03d}" for i in range(130)]


def _published(**overrides) -> pd.DataFrame:
    rows = []
    for i, t in enumerate(TEAMS):
        rows.append({"team": t, "ypg": 300.0 + i, "opp_ypg": 400.0 - i,
                     "turnover_margin": float(i % 11 - 5), "third_down_rate": 0.30 + i / 1000,
                     "wins": float(i % 13), "losses": float(12 - i % 13),
                     "epa_off": (i - 65) / 300, "epa_def": (65 - i) / 300,
                     "sr_off": 0.30 + i / 500, "sr_def": 0.55 - i / 500})
    df = pd.DataFrame(rows)
    for col, fn in overrides.items():
        df[col] = df[col].map(fn)
    return df


def _api(published: pd.DataFrame, *, ppa_scale=1.0, noise=0.0):
    """CFBD's answers for the same teams: official totals that agree, and an independent
    implementation of the derived metrics that is differently scaled but correlated."""
    official, advanced, records = [], [], []
    for i, r in enumerate(published.itertuples()):
        g = 12.0
        base = 300.0 + i
        official += [
            {"team": r.team, "statName": "games", "statValue": g},
            {"team": r.team, "statName": "totalYards", "statValue": base * g},
            {"team": r.team, "statName": "totalYardsOpponent", "statValue": (400.0 - i) * g},
            {"team": r.team, "statName": "turnovers", "statValue": 10.0},
            {"team": r.team, "statName": "turnoversOpponent", "statValue": 10.0 + (i % 11 - 5)},
            {"team": r.team, "statName": "thirdDowns", "statValue": 1000.0},
            {"team": r.team, "statName": "thirdDownConversions",
             "statValue": (0.30 + i / 1000) * 1000},
        ]
        wiggle = noise * ((i % 7) - 3)
        advanced.append({"team": r.team,
                         "offense": {"ppa": (i - 65) / 300 * ppa_scale + wiggle,
                                     "successRate": 0.30 + i / 500 + wiggle},
                         "defense": {"ppa": (65 - i) / 300 * ppa_scale + wiggle,
                                     "successRate": 0.55 - i / 500 + wiggle}})
        records.append({"team": r.team,
                        "total": {"wins": i % 13, "losses": 12 - i % 13}})
    return official, advanced, records


@pytest.fixture
def api(monkeypatch):
    """Point the module's fetches at a fixture; returns a setter."""
    state = {}

    def fake_get(url, season):
        if url == ref.CFBD_STATS_URL:
            return state["official"]
        if url == ref.CFBD_ADVANCED_URL:
            return state["advanced"]
        return state["records"]

    monkeypatch.setattr(ref, "_get", fake_get)

    def use(published, **kw):
        o, a, r = _api(published, **kw)
        state.update(official=o, advanced=a, records=r)
    return use


CON = duckdb.connect(":memory:")


def test_honest_data_passes_every_check(api):
    pub = _published()
    api(pub, ppa_scale=1.3)          # CFBD's scale differs; correlation still ~1
    rep = ref.check_season(CON, SEASON, pub)
    assert rep["ok"] and not rep["skipped"]
    assert {c["id"] for c in rep["checks"] if not c["ok"]} == set()
    assert all(c["corr"] >= c["floor"] for c in rep["checks"] if c["kind"] == "agrees")


def test_the_yards_bug_is_caught(api):
    """Exactly the historical failure: every team's total offense inflated ~3%."""
    pub = _published()
    api(pub)
    inflated = pub.assign(ypg=pub.ypg * 1.03)
    rep = ref.check_season(CON, SEASON, inflated)
    assert not rep["ok"]
    c = next(c for c in rep["checks"] if c["id"] == "yards-per-game")
    assert not c["ok"] and c["n_bad"] == len(TEAMS) and c["worst"] > 9
    assert next(c for c in rep["checks"] if c["id"] == "yards-allowed")["ok"]


def test_a_single_wrong_team_is_caught(api):
    pub = _published()
    api(pub)
    one = pub.copy()
    one.loc[one.index[7], "ypg"] = one.loc[one.index[7], "ypg"] + 0.4
    rep = ref.check_season(CON, SEASON, one)
    assert not rep["ok"]
    assert next(c for c in rep["checks"] if c["id"] == "yards-per-game")["n_bad"] == 1


def test_rounding_noise_is_tolerated(api):
    pub = _published()
    api(pub)
    rep = ref.check_season(CON, SEASON, pub.assign(ypg=pub.ypg + 0.04))
    assert rep["ok"]


@pytest.mark.parametrize("cid,col", [("turnover-margin", "turnover_margin"),
                                     ("third-down-rate", "third_down_rate"),
                                     ("record", "wins")])
def test_every_counting_stat_is_checked(api, cid, col):
    pub = _published()
    api(pub)
    rep = ref.check_season(CON, SEASON, pub.assign(**{col: pub[col] + 1}))
    assert not rep["ok"]
    assert not next(c for c in rep["checks"] if c["id"] == cid)["ok"]


def test_a_sign_flip_in_a_derived_metric_is_caught(api):
    """No official EPA exists, so the guard is agreement with an independent implementation."""
    pub = _published()
    api(pub)
    rep = ref.check_season(CON, SEASON, pub.assign(epa_off=-pub.epa_off))
    assert not rep["ok"]
    c = next(c for c in rep["checks"] if c["id"] == "epa-off")
    assert not c["ok"] and c["corr"] < 0


def test_a_scrambled_join_is_caught(api):
    pub = _published()
    api(pub)
    scrambled = pub.assign(sr_off=pub.sr_off.sample(frac=1, random_state=0).to_numpy())
    rep = ref.check_season(CON, SEASON, scrambled)
    assert not next(c for c in rep["checks"] if c["id"] == "sr-off")["ok"]


def test_legitimate_methodological_difference_still_passes(api):
    """A differently-defined but honest implementation must not trip the floor."""
    pub = _published()
    api(pub, ppa_scale=0.7, noise=0.012)
    rep = ref.check_season(CON, SEASON, pub)
    assert rep["ok"]


def test_no_key_reports_skipped_not_passed(monkeypatch):
    monkeypatch.setattr(ref, "_get", lambda url, season: None)
    rep = ref.check_season(CON, SEASON, _published())
    assert rep["skipped"] and rep["checks"] == []
    assert "nothing verified" in rep["note"]


def test_too_few_teams_cannot_pass(api):
    pub = _published().head(20)
    api(pub)
    rep = ref.check_season(CON, SEASON, pub)
    assert not rep["ok"]        # a handful of teams is not evidence the season is right


def test_correlation_helper():
    assert ref.correlation([1, 2, 3], [2, 4, 6]) == pytest.approx(1.0)
    assert ref.correlation([1, 2, 3], [6, 4, 2]) == pytest.approx(-1.0)
    assert ref.correlation([1, 1, 1], [1, 2, 3]) is None
    assert ref.correlation([1], [1]) is None
