"""Build the 2026 forecast scoreboard page (docs/forecast.html).

Reads every frozen version in predictions/<season>/ (the immutable registry), pulls settled
results from CFBD's /games endpoint (one call, polite UA), and scores each version against the
games that were still in the future when that version was generated — the before-kickoff rule
that keeps mid-season model improvements honest. Emits data/gold/forecast_page.json and injects
it into docs/forecast.html via dashboard/forecast_template.html.

Runs fine without a CFBD key (or offline): the page then shows the frozen predictions with the
accuracy sections waiting for results. The registry CSVs are the only required input, so a clean
clone can build this page.
"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone

import pandas as pd
import requests

from cfb_analytics.config import REPO_ROOT

SEASON = 2026
REGISTRY = REPO_ROOT / "predictions" / str(SEASON)
TEMPLATE = REPO_ROOT / "dashboard" / "forecast_template.html"
OUT_HTML = REPO_ROOT / "docs" / "forecast.html"
OUT_JSON = REPO_ROOT / "data" / "gold" / "forecast_page.json"
CFBD_GAMES_URL = "https://api.collegefootballdata.com/games"
CFBD_UA = "cfb-analytics/1.0 (portfolio; +https://github.com/Steve27M/cfb-analytics)"


def _load_versions() -> list[dict]:
    versions = []
    for d in sorted(p for p in REGISTRY.iterdir() if p.is_dir()):
        manifest = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        games = pd.read_csv(d / f"forecast_{SEASON}.csv")
        teams = pd.read_csv(d / f"forecast_{SEASON}_teams.csv")
        versions.append({"dir": d.name, "manifest": manifest, "games": games, "teams": teams})
    if not versions:
        raise SystemExit(f"no frozen versions under {REGISTRY}")
    versions.sort(key=lambda v: v["manifest"]["generated_at"])
    return versions


def _results() -> pd.DataFrame:
    """Settled 2026 games from CFBD (best-effort: empty frame without a key / offline)."""
    key = os.getenv("CFBD_API_KEY", "")
    cols = ["game_id", "home_points", "away_points", "completed"]
    if not key:
        print("  CFBD_API_KEY not set — building the page without results")
        return pd.DataFrame(columns=cols)
    try:
        resp = requests.get(CFBD_GAMES_URL, params={"year": str(SEASON), "seasonType": "regular"},
                            headers={"Authorization": f"Bearer {key}", "User-Agent": CFBD_UA},
                            timeout=60)
        resp.raise_for_status()
    except Exception as e:  # noqa: BLE001 — page must still build offline
        print(f"  results pull failed ({e}) — building the page without results")
        return pd.DataFrame(columns=cols)
    return pd.DataFrame([{
        "game_id": g["id"], "home_points": g.get("homePoints"),
        "away_points": g.get("awayPoints"), "completed": bool(g.get("completed")),
    } for g in resp.json()])


def _iso(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


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


def build() -> dict:
    versions = _load_versions()
    results = _results()

    # one canonical game frame from the ORIGINAL version's scope (the frozen 740)
    original = versions[0]
    latest = versions[-1]
    games = original["games"].copy()
    games["start_ts"] = games.start_date.map(_iso)
    if len(results):
        games = games.merge(results, on="game_id", how="left")
    else:
        games[["home_points", "away_points", "completed"]] = None
    games["settled"] = (games.completed.fillna(False).astype(bool)
                        & games.home_points.notna() & games.away_points.notna())
    games.loc[games.settled, "home_won"] = (
        games.loc[games.settled, "home_points"] > games.loc[games.settled, "away_points"])

    # score every version, before-kickoff rule: only games scheduled after generated_at count
    scored_versions = []
    for v in versions:
        gen = _iso(v["manifest"]["generated_at"])
        vg = v["games"].merge(
            games[["game_id", "start_ts", "settled", "home_won"]], on="game_id", how="inner",
            suffixes=("", "_c"))
        eligible = vg[vg.start_ts > gen]
        settled = eligible[eligible.settled.fillna(False)].copy()
        weekly = [dict(week=int(w), **_score(g))
                  for w, g in settled.groupby("week")] if len(settled) else []
        scored_versions.append({
            "version": v["dir"],
            "label": v["manifest"].get("label", v["dir"]),
            "generated_at": v["manifest"]["generated_at"],
            "n_games": int(len(v["games"])),
            "n_eligible": int(len(eligible)),
            "overall": _score(settled),
            "weekly": weekly,
        })

    # team table: original projection vs (latest projection) vs actual record so far
    lt = latest["teams"].set_index("team") if latest is not original else None
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
        if lt is not None and t.team in lt.index:
            row["pwl"] = round(float(lt.loc[t.team, "projected_wins"]), 1)
        teams.append(row)

    game_rows = []
    lg = (latest["games"].set_index("game_id").home_win_prob
          if latest is not original else None)
    for _, g in games.sort_values(["week", "start_date"]).iterrows():
        r = {"id": int(g.game_id), "wk": int(g.week), "date": g.start_date[:10],
             "home": g.home_team, "away": g.away_team,
             "neutral": bool(g.neutral_site), "p": round(float(g.home_win_prob), 3)}
        if lg is not None and g.game_id in lg.index:
            r["pl"] = round(float(lg.loc[g.game_id]), 3)
        if bool(g.settled):
            r.update(hp=int(g.home_points), ap=int(g.away_points), hw=bool(g.home_won))
        game_rows.append(r)

    n_settled = int(games.settled.fillna(False).sum())
    payload = {
        "season": SEASON,
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "results_available": bool(len(results)),
        "original": original["dir"],
        "latest": latest["dir"],
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
    print(f"  {len(versions)} version(s) · {n_settled}/{len(games)} games settled"
          + (f" · latest acc {ov['acc']:.1%}, Brier {ov['brier']}" if ov.get("n") else ""))

    html = TEMPLATE.read_text(encoding="utf-8").replace("__FORECAST_DATA__", json.dumps(payload))
    OUT_HTML.write_text(html, encoding="utf-8")
    print(f"  wrote {OUT_HTML}")
    return payload


if __name__ == "__main__":
    build()
