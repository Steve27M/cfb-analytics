"""Build the 2026 forecast scoreboard page (docs/forecast.html).

Reads every frozen version in predictions/<season>/ (the immutable registry), pulls CFBD's
current listing for the season (one call, polite UA), reconciles it against the frozen schedule
and VALIDATES it, and scores each version against the games that were still in the future when
that version was generated — the before-kickoff rule that keeps mid-season model improvements
honest. Emits data/gold/forecast_page.json and injects it into docs/forecast.html via
dashboard/forecast_template.html.

Gates, in order (all reported on the page under "Data integrity"):
  1. registry.verify      every sealed file matches its manifest hash; snapshot chain is sound
  2. results.reconcile    frozen orientation, scores aligned by TEAM, live kickoff, re-keyed ids
  3. results.validate     hard invariants (winner-by-name, team records, settled-after-kickoff,
                          no ties, sane points, unique ids); soft notes (drift)
A hard failure QUARANTINES the results: the page is still built (frozen predictions, banner,
no scoring from the bad pull), no snapshot is sealed, and the process exits 2 so the scheduled
workflow fails loudly after committing the flagged page.

Two kinds of registry version:
  * a flat version (v1-preseason): one forecast, one generated_at, scored forward from that.
  * a series (v2-inseason): a sealed model plus timestamped snapshots/, each re-rated from the
    results settled at that moment. The refresh first asks the model for a new snapshot (written
    only when new, validated results have settled), then scores every snapshot forward-only AND
    the "live" series — for each game, the latest snapshot that predates its kickoff, which is
    what a reader following the season actually saw.

Runs fine without a CFBD key (or offline): the page then shows the frozen predictions with the
accuracy sections waiting for results. The registry is the only required input, so a clean
clone can build this page.
"""
from __future__ import annotations

import json
import math
import sys
from datetime import UTC, datetime

import pandas as pd

from cfb_analytics import inseason, registry, results
from cfb_analytics.config import REPO_ROOT

SEASON = 2026
TEMPLATE = REPO_ROOT / "dashboard" / "forecast_template.html"
OUT_HTML = REPO_ROOT / "docs" / "forecast.html"
OUT_JSON = REPO_ROOT / "data" / "gold" / "forecast_page.json"
OUT_CHECKS = REPO_ROOT / "data" / "gold" / "forecast_checks.json"
# the same payload, published beside the page so other pages (compare.html's 2026 mode) can
# fetch the live season to date; committed by the score workflow with the page
OUT_DATA = REPO_ROOT / "docs" / "forecast_data.json"


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
        "logloss": round(float(-(y * p.map(math.log)
                                 + (1 - y) * (1 - p).map(math.log)).mean()), 4),
        "home_acc": round(float(y.mean()), 4),  # baseline: pick the home team every game
    }


def _weekly(settled: pd.DataFrame) -> list[dict]:
    if not len(settled):
        return []
    return [dict(week=int(w), **_score(g)) for w, g in settled.groupby("week")]


def _forward_only(pred: pd.DataFrame, games: pd.DataFrame,
                  generated_at: str) -> tuple[pd.DataFrame, int]:
    """Games this forecast may be scored on (kickoff after generated_at) and how many settled."""
    gen = _iso(generated_at)
    vg = pred.merge(games[["game_id", "start_ts", "settled", "home_won"]], on="game_id",
                    how="inner")
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


def _drift_summary(drift: dict) -> dict:
    """What the page shows: counts for everything, rows for the identity-level changes."""
    lists = {k: v for k, v in drift.items() if isinstance(v, list)}
    return {
        "counts": {k: len(v) for k, v in lists.items()},
        "rows": {k: lists[k] for k in ("mirrored", "rekeyed", "missing", "changed",
                                       "neutral_changed", "week_moved") if lists.get(k)},
        "n_listed": drift.get("n_listed", 0), "n_frozen": drift.get("n_frozen", 0),
    }


def build() -> dict:
    # gate 1: the registry itself
    integrity = registry.verify(SEASON)

    # gate 2 + 3: live listing, reconciled to the frozen schedule and validated
    raw = results.fetch_games(SEASON)
    sched = registry.load_schedule(SEASON)
    games, drift = results.reconcile(sched, raw)
    report = results.validate(games, raw)
    quarantined = bool(len(raw)) and not report["ok"]
    if quarantined:
        # keep the frozen predictions on the page, but score NOTHING from this pull
        games["settled"] = False
        games[["home_points", "away_points"]] = None

    # let every sealed in-season model add a snapshot if new, validated results have settled
    if len(raw) and integrity["ok"] and not quarantined:
        for d in sorted(p for p in registry.registry_dir(SEASON).iterdir() if p.is_dir()):
            if registry.read_manifest(d).get("kind") == "series":
                inseason.snapshot(SEASON, d.name, results=raw)

    versions = registry.load_versions(SEASON)
    original = versions[0]
    games = games.merge(original["games"][["game_id", "home_win_prob"]], on="game_id")
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
        w, lo = ((g.home_team, g.away_team) if g.home_won else (g.away_team, g.home_team))
        wins[w] = wins.get(w, 0) + 1
        losses[lo] = losses.get(lo, 0) + 1
    dropped = games[games.status == "missing"]
    dropped_by_team: dict[str, int] = {}
    for _, g in dropped.iterrows():
        for t in (g.home_team, g.away_team):
            dropped_by_team[t] = dropped_by_team.get(t, 0) + 1
    teams = []
    for _, t in original["teams"].iterrows():
        row = {
            "team": t.team, "g": int(t.games),
            "pw": round(float(t.projected_wins), 1), "rank": int(t.projected_rank),
            "aw": wins.get(t.team, 0), "al": losses.get(t.team, 0),
        }
        row["left"] = row["g"] - row["aw"] - row["al"] - dropped_by_team.get(t.team, 0)
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
        if g.status == "missing":
            r["gone"] = True             # CFBD no longer lists it (cancelled / not yet re-keyed)
        if live_by_id is not None and g.game_id in live_by_id.index:
            lv = live_by_id.loc[g.game_id]
            r["pl"] = round(float(lv.home_win_prob), 3)
            if lv.pred_margin is not None and not pd.isna(lv.pred_margin):
                r["pm"] = round(float(lv.pred_margin), 1)
        if bool(g.settled):
            r.update(hp=int(g.home_points), ap=int(g.away_points), hw=bool(g.home_won))
        game_rows.append(r)

    n_settled = int(games.settled.fillna(False).sum())
    n_dropped = int(len(dropped))
    series = [v for v in scored_versions if v["series"]]
    checks = {"registry": integrity, "results": report, "drift": _drift_summary(drift),
              "quarantined": quarantined, "results_available": bool(len(raw))}
    payload = {
        "season": SEASON,
        "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "results_available": bool(len(raw)),
        "quarantined": quarantined,
        "original": original["dir"],
        "latest": series[-1]["version"] if series else original["dir"],
        "versions": scored_versions,
        "teams": teams,
        "games": game_rows,
        "settled": n_settled,
        "dropped": n_dropped,
        "total": int(len(games)),
        "season_complete": n_settled + n_dropped == len(games) and n_settled > 0,
        "coinflip_brier": 0.25,
        "checks": checks,
        # the sealed in-season model's win-probability map, so a page can turn a rating
        # difference into a neutral-field probability exactly as the scoreboard does
        "inseason": next(({"version": v["dir"],
                           "coefficients": v["manifest"].get("coefficients"),
                           "hyperparameters": v["manifest"].get("hyperparameters")}
                          for v in versions if v["series"]), None),
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload), encoding="utf-8")
    OUT_CHECKS.write_text(json.dumps(checks, indent=2), encoding="utf-8")
    OUT_DATA.write_text(json.dumps(payload), encoding="utf-8", newline="\n")
    ov = scored_versions[-1]["overall"]
    n_snaps = sum(len(v.get("snapshots", [])) for v in series)
    print(f"  {len(versions)} version(s), {n_snaps} snapshot(s) · {n_settled}/{len(games)} games "
          f"settled"
          + (f" · latest acc {ov['acc']:.1%}, Brier {ov['brier']}" if ov.get("n") else "")
          + (" · RESULTS QUARANTINED" if quarantined else ""))

    html = TEMPLATE.read_text(encoding="utf-8").replace("__FORECAST_DATA__", json.dumps(payload))
    OUT_HTML.write_text(html, encoding="utf-8")
    print(f"  wrote {OUT_HTML}")
    return payload


if __name__ == "__main__":
    out = build()
    if out["quarantined"] or not out["checks"]["registry"]["ok"]:
        print("  exiting 2: data integrity gate failed (page built and flagged)")
        sys.exit(2)
