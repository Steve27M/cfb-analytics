"""Build the 2026 forecast scoreboard page (docs/forecast.html).

Reads every frozen version in predictions/<season>/ (the immutable registry), pulls settled
results from CFBD's /games endpoint (one call, polite UA), and scores each version against the
games that were still in the future when that version was generated — the before-kickoff rule
that keeps mid-season model improvements honest. Emits data/gold/forecast_page.json and injects
it into docs/forecast.html via dashboard/forecast_template.html.

Two kinds of registry version:
  * a flat version (v1-preseason): one forecast, one generated_at, scored forward from that.
  * a series (v2-inseason): a sealed model plus timestamped snapshots/, each re-rated from the
    results settled at that moment. The refresh first asks the model for a new snapshot (written
    only when new results have settled), then scores every snapshot forward-only AND the "live"
    series — for each game, the latest snapshot that predates its kickoff, which is what a reader
    following the season actually saw.

Runs fine without a CFBD key (or offline): the page then shows the frozen predictions with the
accuracy sections waiting for results. The registry is the only required input, so a clean
clone can build this page.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone

import pandas as pd

from cfb_analytics import inseason
from cfb_analytics.config import REPO_ROOT

SEASON = 2026
REGISTRY = REPO_ROOT / "predictions" / str(SEASON)
TEMPLATE = REPO_ROOT / "dashboard" / "forecast_template.html"
OUT_HTML = REPO_ROOT / "docs" / "forecast.html"
OUT_JSON = REPO_ROOT / "data" / "gold" / "forecast_page.json"


def _iso(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _read_version(d) -> dict:
    manifest = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    return {"dir": d.name, "manifest": manifest,
            "games": pd.read_csv(d / f"forecast_{SEASON}.csv"),
            "teams": pd.read_csv(d / f"forecast_{SEASON}_teams.csv")}


def _load_versions() -> list[dict]:
    versions = []
    for d in sorted(p for p in REGISTRY.iterdir() if p.is_dir()):
        manifest = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        if manifest.get("kind") == "series":
            snaps = [_read_version(s) for s in sorted((d / "snapshots").iterdir())
                     if s.is_dir()] if (d / "snapshots").exists() else []
            snaps.sort(key=lambda v: v["manifest"]["generated_at"])
            versions.append({"dir": d.name, "manifest": manifest, "series": True,
                             "snapshots": snaps})
        else:
            versions.append({**_read_version(d), "series": False})
    if not versions:
        raise SystemExit(f"no frozen versions under {REGISTRY}")
    versions.sort(key=lambda v: (v["series"], v["manifest"]["generated_at"]))
    return versions


def _score(df: pd.DataFrame) -> dict:
    """Accuracy/Brier/log-loss for settled games with a prediction (home_win_prob vs home_won)."""
    n = len(df)
    if n == 0:
        return {"n": 0}
    p = df.home_win_prob.clip(1e-6, 1 - 1e-6)
    y = df.home_won.astype(float)
    picked_home = df.home_win_prob >= 0.5
    return {
        "n": int(n),
        "acc": round(float((picked_home == df.home_won).mean()), 4),
        "brier": round(float(((df.home_win_prob - y) ** 2).mean()), 4),
        "logloss": round(float(-(y * p.map(math.log) + (1 - y) * (1 - p).map(math.log)).mean()), 4),
        "home_acc": round(float(y.mean()), 4),  # baseline: pick the home team every game
    }


def _weekly(settled: pd.DataFrame) -> list[dict]:
    return [dict(week=int(w), **_score(g)) for w, g in settled.groupby("week")] if len(settled) else []


def _forward_only(pred: pd.DataFrame, games: pd.DataFrame, generated_at: str) -> tuple[pd.DataFrame, int]:
    """Games this forecast may be scored on (kickoff after generated_at) and how many settled."""
    gen = _iso(generated_at)
    vg = pred.merge(games[["game_id", "start_ts", "settled", "home_won"]], on="game_id", how="inner")
    eligible = vg[vg.start_ts > gen]
    return eligible[eligible.settled.fillna(False)].copy(), int(len(eligible))


def _live_series(snaps: list[dict], games: pd.DataFrame) -> pd.DataFrame:
    """For every game, the prediction of the latest snapshot that predates its kickoff."""
    if not snaps:
        return pd.DataFrame(columns=["game_id", "home_win_prob", "pred_margin", "snapshot"])
    rows = {}
    for s in snaps:                       # sorted oldest -> newest, so later ones overwrite
        gen = _iso(s["manifest"]["generated_at"])
        g = s["games"].merge(games[["game_id", "start_ts"]], on="game_id")
        g = g[g.start_ts > gen]
        for r in g.itertuples():
            rows[r.game_id] = {"game_id": r.game_id, "home_win_prob": r.home_win_prob,
                               "pred_margin": getattr(r, "pred_margin", None), "snapshot": s["dir"]}
    return pd.DataFrame(list(rows.values()))


def build() -> dict:
    results = inseason.settled_games(SEASON)
    # let every sealed in-season model add a snapshot if new results have settled (no-op otherwise)
    for d in sorted(p for p in REGISTRY.iterdir() if p.is_dir()):
        manifest = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        if manifest.get("kind") == "series" and len(results):
            inseason.snapshot(SEASON, d.name, results=results)

    versions = _load_versions()
    original = versions[0]
    # one canonical game frame: the frozen 740, results aligned by team into the frozen
    # orientation, kickoff = CFBD's current start time (the before-kickoff rule uses it)
    games = inseason.align_results(original["games"].copy(), results)
    games["start_ts"] = games.kickoff.map(_iso)
    games.loc[games.settled, "home_won"] = (
        games.loc[games.settled, "home_points"] > games.loc[games.settled, "away_points"])

    scored_versions = []
    live: pd.DataFrame | None = None
    latest_teams: pd.DataFrame | None = None
    for v in versions:
        if not v["series"]:
            settled, n_eligible = _forward_only(v["games"], games, v["manifest"]["generated_at"])
            scored_versions.append({
                "version": v["dir"], "label": v["manifest"].get("label", v["dir"]),
                "series": False, "generated_at": v["manifest"]["generated_at"],
                "n_games": int(len(v["games"])), "n_eligible": n_eligible,
                "overall": _score(settled), "weekly": _weekly(settled),
            })
            continue
        snaps = v["snapshots"]
        live = _live_series(snaps, games)
        live_settled = live.merge(games[["game_id", "week", "settled", "home_won"]], on="game_id")
        live_settled = live_settled[live_settled.settled.fillna(False)]
        snap_rows = []
        for s in snaps:
            settled, n_eligible = _forward_only(s["games"], games, s["manifest"]["generated_at"])
            snap_rows.append({
                "snapshot": s["dir"], "generated_at": s["manifest"]["generated_at"],
                "results_in": int(s["manifest"].get("n_settled", 0)),
                "through_week": int(s["manifest"].get("through_week", 0)),
                "n_eligible": n_eligible, "overall": _score(settled),
            })
        m = v["manifest"]
        scored_versions.append({
            "version": v["dir"], "label": m.get("label", v["dir"]), "series": True,
            "generated_at": m["generated_at"], "n_games": int(len(original["games"])),
            "n_eligible": int(len(live)), "overall": _score(live_settled),
            "weekly": _weekly(live_settled), "snapshots": snap_rows,
            "latest_generated_at": snaps[-1]["manifest"]["generated_at"] if snaps else None,
            "method": m.get("method"), "hyperparameters": m.get("hyperparameters"),
            "holdout_metrics": m.get("holdout_metrics"), "holdout_season": m.get("holdout_season"),
        })
        if snaps:
            latest_teams = snaps[-1]["teams"].set_index("team")

    # team table: original projection vs latest updated projection vs actual record so far
    settled_g = games[games.settled.fillna(False)]
    wins: dict[str, int] = {}
    losses: dict[str, int] = {}
    for _, g in settled_g.iterrows():
        w, l = ((g.home_team, g.away_team) if g.home_won else (g.away_team, g.home_team))
        wins[w] = wins.get(w, 0) + 1
        losses[l] = losses.get(l, 0) + 1
    teams = []
    for _, t in original["teams"].iterrows():
        row = {
            "team": t.team, "g": int(t.games),
            "pw": round(float(t.projected_wins), 1), "rank": int(t.projected_rank),
            "aw": wins.get(t.team, 0), "al": losses.get(t.team, 0),
        }
        row["left"] = row["g"] - row["aw"] - row["al"]
        if latest_teams is not None and t.team in latest_teams.index:
            lt = latest_teams.loc[t.team]
            row["pwl"] = round(float(lt.projected_wins), 1)
            row["rt"] = round(float(lt.rating), 1)
            row["rk"] = int(lt.rating_rank)
            row["rt0"] = round(float(lt.prior_rating), 1)
        teams.append(row)

    # per-game rows: original prob, plus the live updated prob/margin when a snapshot preceded it
    live_by_id = live.set_index("game_id") if live is not None and len(live) else None
    game_rows = []
    for _, g in games.sort_values(["week", "kickoff"]).iterrows():
        r = {"id": int(g.game_id), "wk": int(g.week), "date": g.kickoff[:10],
             "home": g.home_team, "away": g.away_team,
             "neutral": bool(g.neutral_site), "p": round(float(g.home_win_prob), 3)}
        if bool(g.flipped) and not bool(g.neutral_site):
            r["host"] = g.away_team      # CFBD moved the game to the frozen away team's field
        if live_by_id is not None and g.game_id in live_by_id.index:
            lv = live_by_id.loc[g.game_id]
            r["pl"] = round(float(lv.home_win_prob), 3)
            if lv.pred_margin is not None and not pd.isna(lv.pred_margin):
                r["pm"] = round(float(lv.pred_margin), 1)
        if bool(g.settled):
            r.update(hp=int(g.home_points), ap=int(g.away_points), hw=bool(g.home_won))
        game_rows.append(r)

    n_settled = int(games.settled.fillna(False).sum())
    series = [v for v in scored_versions if v["series"]]
    payload = {
        "season": SEASON,
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "results_available": bool(len(results)),
        "original": original["dir"],
        "latest": series[-1]["version"] if series else original["dir"],
        "versions": scored_versions,
        "teams": teams,
        "games": game_rows,
        "settled": n_settled,
        "total": int(len(games)),
        "season_complete": n_settled == len(games),
        "coinflip_brier": 0.25,
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload), encoding="utf-8")
    ov = scored_versions[-1]["overall"]
    n_snaps = sum(len(v.get("snapshots", [])) for v in series)
    print(f"  {len(versions)} version(s), {n_snaps} snapshot(s) · {n_settled}/{len(games)} games "
          f"settled" + (f" · latest acc {ov['acc']:.1%}, Brier {ov['brier']}" if ov.get("n") else ""))

    html = TEMPLATE.read_text(encoding="utf-8").replace("__FORECAST_DATA__", json.dumps(payload))
    OUT_HTML.write_text(html, encoding="utf-8")
    print(f"  wrote {OUT_HTML}")
    return payload


if __name__ == "__main__":
    build()
