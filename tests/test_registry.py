"""cfb_analytics.registry.verify — the registry proves its own integrity on every refresh."""
import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from cfb_analytics import registry

SEASON = 2026
GAMES = pd.DataFrame({
    "game_id": [1, 2, 3], "week": [1, 1, 2],
    "start_date": ["2026-09-05T20:00:00.000Z", "2026-09-06T23:30:00.000Z",
                   "2026-09-12T19:30:00.000Z"],
    "neutral_site": [False, True, False],
    "home_team": ["USC", "Wisconsin", "Notre Dame"],
    "away_team": ["San José State", "Notre Dame", "Rice"],
    "home_win_prob": [0.87, 0.25, 0.93], "favored_team": ["USC", "Notre Dame", "Notre Dame"],
    "favored_win_prob": [0.87, 0.75, 0.93], "forecast_season": [SEASON] * 3,
})
TEAMS = pd.DataFrame({"team": ["USC", "Wisconsin", "Notre Dame", "San José State", "Rice"],
                      "games": [1, 1, 2, 1, 1], "projected_wins": [0.87, 0.25, 1.68, 0.13, 0.07],
                      "projected_rank": [2, 3, 1, 4, 5]})


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _seal(d: Path, games: pd.DataFrame, teams: pd.DataFrame, manifest: dict) -> None:
    d.mkdir(parents=True)
    games.to_csv(d / f"forecast_{SEASON}.csv", index=False)
    teams.to_csv(d / f"forecast_{SEASON}_teams.csv", index=False)
    manifest["files"] = {f"forecast_{SEASON}.csv": {"sha256": _sha(d / f"forecast_{SEASON}.csv"),
                                                    "rows": len(games)},
                         f"forecast_{SEASON}_teams.csv": {
                             "sha256": _sha(d / f"forecast_{SEASON}_teams.csv"),
                             "rows": len(teams)}}
    (d / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


@pytest.fixture
def reg(tmp_path, monkeypatch) -> Path:
    """A minimal but complete registry: a flat v1 and a series v2 with two snapshots."""
    monkeypatch.setattr(registry, "PREDICTIONS_DIR", tmp_path)
    root = tmp_path / str(SEASON)
    _seal(root / "v1-preseason", GAMES, TEAMS,
          {"version": "v1-preseason", "generated_at": "2026-07-01T12:00:00+00:00"})
    v2 = root / "v2-inseason"
    v2.mkdir()
    (v2 / "coef.csv").write_text("term,estimate\nx,1\n", encoding="utf-8")
    (v2 / "manifest.json").write_text(json.dumps({
        "version": "v2-inseason", "kind": "series", "generated_at": "2026-09-06T11:24:09+00:00",
        "files": {"coef.csv": {"sha256": _sha(v2 / "coef.csv"), "rows": 1}}}), encoding="utf-8")
    for ts in ("2026-09-06T11:24:09+00:00", "2026-09-12T23:32:42+00:00"):
        _seal(v2 / "snapshots" / (ts[:16].replace(":", "-") + "Z"),
              GAMES.assign(pred_margin=[10.0, -16.5, 31.3]), TEAMS,
              {"version": "v2-inseason", "generated_at": ts, "results_hash": "abc"})
    return root


def test_intact_registry_verifies(reg):
    rep = registry.verify(SEASON)
    assert rep["ok"] and rep["n_versions"] == 2 and rep["n_snapshots"] == 2
    assert all(c["ok"] for c in rep["checks"])


def test_load_versions_orders_flat_then_series_with_sorted_snapshots(reg):
    vs = registry.load_versions(SEASON)
    assert [v["dir"] for v in vs] == ["v1-preseason", "v2-inseason"]
    assert [s["dir"] for s in vs[1]["snapshots"]] == ["2026-09-06T11-24Z", "2026-09-12T23-32Z"]
    assert len(registry.load_schedule(SEASON)) == 3


def test_edited_forecast_fails_manifest_hashes(reg):
    p = reg / "v1-preseason" / f"forecast_{SEASON}.csv"
    p.write_text(p.read_text(encoding="utf-8").replace("0.25", "0.75"), encoding="utf-8")
    rep = registry.verify(SEASON)
    assert not rep["ok"]
    c = next(c for c in rep["checks"] if c["id"] == "manifest-hashes")
    assert not c["ok"] and "v1-preseason" in c["detail"] and "SHA-256" in c["detail"]


def test_edited_snapshot_fails_manifest_hashes(reg):
    p = reg / "v2-inseason" / "snapshots" / "2026-09-12T23-32Z" / f"forecast_{SEASON}_teams.csv"
    p.write_text(p.read_text(encoding="utf-8") + "Extra,1,1.0,6\n", encoding="utf-8")
    c = next(c for c in registry.verify(SEASON)["checks"] if c["id"] == "manifest-hashes")
    assert not c["ok"] and "rows" in c["detail"] or "SHA-256" in c["detail"]


def test_missing_sealed_file_fails(reg):
    (reg / "v2-inseason" / "coef.csv").unlink()
    c = next(c for c in registry.verify(SEASON)["checks"] if c["id"] == "manifest-hashes")
    assert not c["ok"] and "coef.csv missing" in c["detail"]


def test_snapshot_directory_name_must_match_generated_at(reg):
    s = reg / "v2-inseason" / "snapshots" / "2026-09-12T23-32Z"
    s.rename(s.with_name("2026-09-12T23-59Z"))
    c = next(c for c in registry.verify(SEASON)["checks"] if c["id"] == "snapshot-chain")
    assert not c["ok"] and "directory name" in c["detail"]


def test_snapshot_predating_its_model_fails_chain(reg):
    s = reg / "v2-inseason" / "snapshots" / "2026-09-06T11-24Z"
    m = json.loads((s / "manifest.json").read_text(encoding="utf-8"))
    m["generated_at"] = "2026-09-01T11:24:09+00:00"
    (s / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
    s.rename(s.with_name("2026-09-01T11-24Z"))
    c = next(c for c in registry.verify(SEASON)["checks"] if c["id"] == "snapshot-chain")
    assert not c["ok"] and "predates its model" in c["detail"]


def test_snapshot_must_predict_exactly_the_frozen_games(reg):
    s = reg / "v2-inseason" / "snapshots" / "2026-09-12T23-32Z"
    g = pd.read_csv(s / f"forecast_{SEASON}.csv").iloc[:2]
    g.to_csv(s / f"forecast_{SEASON}.csv", index=False)
    m = json.loads((s / "manifest.json").read_text(encoding="utf-8"))
    m["files"][f"forecast_{SEASON}.csv"] = {"sha256": _sha(s / f"forecast_{SEASON}.csv"), "rows": 2}
    (s / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
    rep = registry.verify(SEASON)
    c = next(c for c in rep["checks"] if c["id"] == "frozen-scope")
    assert not c["ok"] and "predicts 2 games" in c["detail"]
    assert next(c for c in rep["checks"] if c["id"] == "manifest-hashes")["ok"]


def test_duplicate_frozen_game_id_fails_scope(reg):
    p = reg / "v1-preseason" / f"forecast_{SEASON}.csv"
    g = pd.read_csv(p)
    pd.concat([g, g.iloc[[0]]]).to_csv(p, index=False)
    rep = registry.verify(SEASON)
    assert not next(c for c in rep["checks"] if c["id"] == "frozen-scope")["ok"]


def test_line_ending_conversion_is_not_tampering_but_content_change_is(reg):
    """A checkout on another platform may flip CRLF/LF; the sealed hash must still verify.
    Any change to the content must still fail."""
    p = reg / "v1-preseason" / f"forecast_{SEASON}.csv"
    lf = p.read_bytes().replace(b"\r\n", b"\n")
    p.write_bytes(lf.replace(b"\n", b"\r\n"))
    assert registry.verify(SEASON)["ok"]
    p.write_bytes(lf)
    assert registry.verify(SEASON)["ok"]
    p.write_bytes(lf.replace(b"0.25", b"0.26"))
    assert not registry.verify(SEASON)["ok"]


def test_sha256_text_ignores_line_endings(tmp_path):
    a, b = tmp_path / "a.csv", tmp_path / "b.csv"
    a.write_bytes(b"x,y\n1,2\n")
    b.write_bytes(b"x,y\r\n1,2\r\n")
    assert registry.sha256_text(a) == registry.sha256_text(b)
    assert registry.sha256(a) != registry.sha256(b)
    assert registry.hash_matches(b, registry.sha256(a))


def test_real_registry_is_intact():
    """The committed registry must always verify — this is the CI tripwire."""
    rep = registry.verify(SEASON)
    assert rep["ok"], [c for c in rep["checks"] if not c["ok"]]
