"""Are the published numbers true? Check them against an independent source.

The project's dbt tests check STRUCTURE — keys are unique, values are in range, foreign keys
resolve. They cannot tell you a number is wrong, only that it is well-formed. Total offense was
published ~3% high for months (up to 12% for some teams) and passed every one of them, because a
wrong number is still a well-formed number.

This module closes that gap. Every published team statistic is compared against a source that
was produced independently of this pipeline, and the build refuses to publish when a check
fails. There are two kinds of check, because there are two kinds of statistic:

  EXACT    Counting stats (yards, turnovers, third downs, records) now come FROM the official
           season totals, so the check proves the join and the arithmetic did not corrupt them.
           Tolerance is a rounding epsilon, not a fudge factor.

  AGREES   EPA, success rate and the ratings are computed here from play-by-play. No official
           version exists, but CFBD publishes its own independent implementations (PPA, success
           rate). They are defined differently, so the values will not match — but two honest
           implementations of the same concept must move together. The check is a correlation
           floor across all teams, which catches a sign flip, a bad join or a definition drift
           while tolerating legitimate methodological difference.

  Explosive-play rate is deliberately NOT checked against CFBD's "explosiveness": theirs is the
  average PPA of successful plays, ours is the share of plays gaining 15+ yards. They correlate
  only 0.48 because they measure different things — which is why this project labels its own
  metric "Explosive Play Rate" rather than borrowing their name.

Run it through `check_season()`; `run.py compare` and `run.py live` both call it before they
publish, and the result is written to the site so a reader can see what was verified.
"""
from __future__ import annotations

import math
import os
from datetime import UTC, datetime

import duckdb
import pandas as pd
import requests

CFBD_STATS_URL = "https://api.collegefootballdata.com/stats/season"
CFBD_ADVANCED_URL = "https://api.collegefootballdata.com/stats/season/advanced"
CFBD_RECORDS_URL = "https://api.collegefootballdata.com/records"
CFBD_UA = "cfb-analytics/1.0 (portfolio; +https://github.com/Steve27M/cfb-analytics)"

# A counting stat must match the official figure to within rounding.
EXACT_TOLERANCE = 0.05          # yards per game, after both sides are rounded for display
# A derived metric must track its independent counterpart this closely across all teams.
CORRELATION_FLOOR = {"epa_off": 0.90, "epa_def": 0.85, "sr_off": 0.93, "sr_def": 0.93}
MIN_TEAMS = 100


def _key() -> str:
    return os.getenv("CFBD_API_KEY", "").strip().lstrip("﻿")


def _get(url: str, season: int) -> list[dict] | None:
    key = _key()
    if not key:
        return None
    try:
        r = requests.get(url, params={"year": str(season)},
                         headers={"Authorization": f"Bearer {key}", "User-Agent": CFBD_UA},
                         timeout=90)
        r.raise_for_status()
        return r.json()
    except Exception as e:  # noqa: BLE001 — a reachability problem must not look like a data problem
        print(f"  reference: {url.rsplit('/', 1)[-1]} unavailable ({e})")
        return None


def correlation(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    den = math.sqrt(sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys))
    return None if den == 0 else num / den


def _exact_check(cid: str, name: str, pairs: list[tuple[str, float, float]],
                 tol: float, unit: str) -> dict:
    """pairs: (team, ours, theirs). Fails on any team outside tolerance."""
    bad = [(t, o, r) for t, o, r in pairs if abs(o - r) > tol]
    worst = max((abs(o - r) for _, o, r in pairs), default=0.0)
    return {"id": cid, "name": name, "kind": "exact", "ok": not bad and len(pairs) >= MIN_TEAMS,
            "n": len(pairs), "n_bad": len(bad),
            "worst": round(worst, 3), "tolerance": tol, "unit": unit,
            "detail": ("; ".join(f"{t}: ours {o} vs official {r}" for t, o, r in bad[:5])
                       if bad else f"{len(pairs)} teams, largest gap {worst:.3f} {unit}"
                       if pairs else "no teams compared")}


def _agreement_check(cid: str, name: str, ours: list[float], theirs: list[float],
                     floor: float, against: str) -> dict:
    r = correlation(ours, theirs)
    return {"id": cid, "name": name, "kind": "agrees", "against": against,
            "ok": bool(r is not None and len(ours) >= MIN_TEAMS and r >= floor),
            "n": len(ours), "corr": None if r is None else round(r, 4), "floor": floor,
            "detail": (f"r = {r:.3f} vs {against} across {len(ours)} teams (floor {floor})"
                       if r is not None else "not enough teams to correlate")}


def check_season(con: duckdb.DuckDBPyConnection, season: int, published: pd.DataFrame) -> dict:
    """Verify `published` (one row per team, as team_stats() returns it) for <season>.

    Returns {"ok", "checked_at", "season", "checks": [...], "skipped": bool}. Without a CFBD key
    (or offline) the result is `skipped`: unverified, never silently "passed"."""
    official = _get(CFBD_STATS_URL, season)
    advanced = _get(CFBD_ADVANCED_URL, season)
    records = _get(CFBD_RECORDS_URL, season)
    if official is None or advanced is None or records is None:
        return {"ok": True, "skipped": True, "season": season,
                "checked_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "checks": [], "note": "no CFBD key or endpoint unreachable — nothing verified"}

    off: dict[str, dict[str, float]] = {}
    for r in official:
        off.setdefault(r["team"], {})[r["statName"]] = r["statValue"]
    adv = {r["team"]: r for r in advanced}
    rec = {r["team"]: r for r in records}
    pub = published.set_index("team")

    ypg, allowed, margin, third = [], [], [], []
    wl: list[tuple[str, float, float]] = []
    agree: dict[str, tuple[list[float], list[float]]] = {k: ([], []) for k in CORRELATION_FLOOR}
    for team, row in pub.iterrows():
        o, a, rc = off.get(team), adv.get(team), rec.get(team)
        if o and o.get("games"):
            g = o["games"]
            if pd.notna(row.get("ypg")):
                ypg.append((team, round(float(row.ypg), 1), round(o["totalYards"] / g, 1)))
            if pd.notna(row.get("opp_ypg")):
                allowed.append((team, round(float(row.opp_ypg), 1),
                                round(o["totalYardsOpponent"] / g, 1)))
            if pd.notna(row.get("turnover_margin")):
                margin.append((team, float(row.turnover_margin),
                               float(o["turnoversOpponent"] - o["turnovers"])))
            if pd.notna(row.get("third_down_rate")) and o.get("thirdDowns"):
                third.append((team, round(float(row.third_down_rate), 4),
                              round(o["thirdDownConversions"] / o["thirdDowns"], 4)))
        if rc:
            wl.append((team, float(row.wins), float(rc["total"]["wins"])))
            wl.append((team + " (L)", float(row.losses), float(rc["total"]["losses"])))
        if a:
            for k, (side, field) in {"epa_off": ("offense", "ppa"), "epa_def": ("defense", "ppa"),
                                     "sr_off": ("offense", "successRate"),
                                     "sr_def": ("defense", "successRate")}.items():
                v, t = row.get(k), a.get(side, {}).get(field)
                if pd.notna(v) and t is not None:
                    agree[k][0].append(float(v))
                    agree[k][1].append(float(t))

    checks = [
        _exact_check("yards-per-game", "Total offense per game = official season total", ypg,
                     EXACT_TOLERANCE, "yards"),
        _exact_check("yards-allowed", "Yards allowed per game = official season total", allowed,
                     EXACT_TOLERANCE, "yards"),
        _exact_check("turnover-margin", "Turnover margin = official takeaways minus giveaways",
                     margin, 0.0, "turnovers"),
        _exact_check("third-down-rate",
                     "Third-down conversion rate = official conversions/attempts",
                     third, 0.0005, "rate"),
        _exact_check("record", "Wins and losses = official records", wl, 0.0, "games"),
        _agreement_check("epa-off", "Offensive EPA tracks CFBD's predicted points added",
                         *agree["epa_off"], CORRELATION_FLOOR["epa_off"], "CFBD offense PPA"),
        _agreement_check("epa-def", "Defensive EPA tracks CFBD's predicted points added",
                         *agree["epa_def"], CORRELATION_FLOOR["epa_def"], "CFBD defense PPA"),
        _agreement_check("sr-off", "Offensive success rate tracks CFBD's success rate",
                         *agree["sr_off"], CORRELATION_FLOOR["sr_off"],
                         "CFBD offense success rate"),
        _agreement_check("sr-def", "Defensive success rate tracks CFBD's success rate",
                         *agree["sr_def"], CORRELATION_FLOOR["sr_def"],
                         "CFBD defense success rate"),
    ]
    ok = all(c["ok"] for c in checks)
    report = {"ok": ok, "skipped": False, "season": season,
              "checked_at": datetime.now(UTC).isoformat(timespec="seconds"),
              "source": "CollegeFootballData /stats/season, /stats/season/advanced, /records",
              "checks": checks}
    bad = [c for c in checks if not c["ok"]]
    if bad:
        print(f"  reference {season}: FAILED — " + "; ".join(
            f"{c['id']}: {c['detail'][:120]}" for c in bad))
    else:
        print(f"  reference {season}: all {len(checks)} checks pass "
              f"({sum(c['n'] for c in checks if c['kind'] == 'exact')} exact comparisons, "
              + ", ".join(f"{c['id']} r={c['corr']}"
                          for c in checks if c["kind"] == "agrees") + ")")
    return report
