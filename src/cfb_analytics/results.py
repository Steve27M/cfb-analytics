"""Season results: fetch, reconcile against the frozen schedule, validate.

The frozen schedule (predictions/<season>/v1-preseason) is the registry's KEY SPACE — the 740
games every version predicts and is scored on. Everything else about a game is live and can
change after the freeze: CFBD re-designates neutral-site hosts, moves games to the other team's
field, shifts kickoff times (many are placeholders until TV picks), re-keys a postponed game under
a new id, and drops cancelled games. The 2026 week-1 Notre Dame–Wisconsin game (frozen as
Wisconsin home, settled as Notre Dame home 41–13) was scored backwards because the refresh
trusted the frozen orientation. This module is the single path from CFBD rows to a scoreable
frame, and it never trusts the frozen copy for anything but identity:

  fetch_games(season)        one polite CFBD /games call -> raw rows (empty when keyless/offline)
  reconcile(sched, raw)      frozen orientation, results aligned BY TEAM, live kickoff, drift report
  validate(aligned, raw)     hard/soft invariants; hard failures QUARANTINE the results (nothing
                             is sealed, the page says so, the workflow fails loudly)

Everything downstream (in-season snapshots, the scoreboard) consumes only the reconciled frame.
"""
from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd
import requests

CFBD_GAMES_URL = "https://api.collegefootballdata.com/games"
CFBD_UA = "cfb-analytics/1.0 (portfolio; +https://github.com/Steve27M/cfb-analytics)"

RAW_COLS = ["game_id", "week", "start_date", "start_time_tbd", "neutral_site", "home_team",
            "away_team", "home_points", "away_points", "completed", "home_postgame_wp"]
SCHED_COLS = ["game_id", "week", "start_date", "neutral_site", "home_team", "away_team"]


# --------------------------------------------------------------------------- fetch
def fetch_games(season: int) -> pd.DataFrame:
    """Every regular-season game CFBD lists for <season> (all divisions), raw. Best-effort: an
    empty frame without a key or offline, so the page can always build from the registry."""
    # strip a UTF-8 BOM: a BOM-prefixed key (Windows-written .env pasted into a CI secret)
    # is invisible in every UI but breaks latin-1 header encoding
    key = os.getenv("CFBD_API_KEY", "").strip().lstrip("﻿")
    if not key:
        print("  CFBD_API_KEY not set — continuing without results")
        return pd.DataFrame(columns=RAW_COLS)
    try:
        resp = requests.get(CFBD_GAMES_URL, params={"year": str(season), "seasonType": "regular"},
                            headers={"Authorization": f"Bearer {key}", "User-Agent": CFBD_UA},
                            timeout=60)
        resp.raise_for_status()
        rows = resp.json()
    except Exception as e:  # noqa: BLE001 — the page must still build offline
        print(f"  results pull failed ({e}) — continuing without results")
        return pd.DataFrame(columns=RAW_COLS)
    return pd.DataFrame([{
        "game_id": g["id"], "week": g.get("week"), "start_date": g.get("startDate"),
        "start_time_tbd": bool(g.get("startTimeTBD")), "neutral_site": bool(g.get("neutralSite")),
        "home_team": g.get("homeTeam"), "away_team": g.get("awayTeam"),
        "home_points": g.get("homePoints"), "away_points": g.get("awayPoints"),
        "completed": bool(g.get("completed")),
        "home_postgame_wp": g.get("homePostgameWinProbability"),
    } for g in rows], columns=RAW_COLS)


# --------------------------------------------------------------------------- reconcile
def _pair(h: str, a: str) -> tuple[str, str]:
    return (h, a) if h <= a else (a, h)


def reconcile(sched: pd.DataFrame, raw: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Attach CFBD's current listing + results to the frozen schedule, in the schedule's own
    home/away orientation, and report every way the live schedule has drifted from the freeze.

    Matching: by game id first; a frozen id CFBD no longer lists is re-keyed to the CFBD game
    between the same two teams when there is exactly one (a postponed game re-created under a
    new id) and otherwise reported missing. Orientation: `same`, `mirrored` (points swapped so
    the frozen home team's score is home_points), or `changed` (teams differ — left unsettled).

    Adds per game: cfbd_id, status (same|mirrored|rekeyed|missing|changed), home_points,
    away_points (frozen orientation), completed, settled, flipped, home_ind (+1 the frozen home
    team hosts, -1 the frozen away team hosts, 0 neutral), kickoff (CFBD's current start, frozen
    as fallback), kickoff_moved, cfbd_week, cfbd_neutral, home_postgame_wp.
    """
    out = sched[SCHED_COLS].copy() if set(SCHED_COLS) <= set(sched.columns) else sched.copy()
    out["cfbd_id"] = out.game_id
    raw = raw.copy()
    for c in RAW_COLS:                     # tolerate a partial raw frame (tests, older callers)
        if c not in raw.columns:
            raw[c] = None
    if len(raw):
        raw["_pair"] = [_pair(str(h), str(a)) for h, a in zip(raw.home_team, raw.away_team,
                                                              strict=True)]
        frozen_ids = set(out.game_id)
        by_id = raw.set_index("game_id")
        # re-key: frozen ids CFBD dropped, matched to the unique unclaimed CFBD game between
        # the same two teams (a postponement re-created under a new event id)
        unclaimed = raw[~raw.game_id.isin(frozen_ids)]
        pair_to_ids = unclaimed.groupby("_pair").game_id.apply(list).to_dict()
        for i in out.index[~out.game_id.isin(by_id.index)]:
            cands = pair_to_ids.get(_pair(out.at[i, "home_team"], out.at[i, "away_team"]), [])
            if len(cands) == 1:
                out.at[i, "cfbd_id"] = cands[0]
        r = raw.drop(columns=["_pair"]).rename(columns={
            "game_id": "cfbd_id", "home_team": "cfbd_home", "away_team": "cfbd_away",
            "start_date": "cfbd_start", "week": "cfbd_week", "neutral_site": "cfbd_neutral"})
        out = out.merge(r, on="cfbd_id", how="left")
    else:
        for c in ("cfbd_home", "cfbd_away", "cfbd_start", "cfbd_week", "cfbd_neutral",
                  "start_time_tbd", "home_points", "away_points", "completed", "home_postgame_wp"):
            out[c] = None

    listed = out.cfbd_home.notna()
    same = listed & (out.cfbd_home == out.home_team) & (out.cfbd_away == out.away_team)
    mirrored = listed & (out.cfbd_home == out.away_team) & (out.cfbd_away == out.home_team)
    changed = listed & ~same & ~mirrored
    rekeyed = listed & (out.cfbd_id != out.game_id)
    # "missing" means CFBD's listing exists and lacks the game; with no listing at all
    # (keyless / offline) nothing is known, and nothing is reported as dropped
    out["status"] = np.select([~listed, changed, rekeyed, mirrored], ["missing", "changed",
                                                                     "rekeyed", "mirrored"], "same")
    if not len(raw):
        out["status"] = "unknown"
        listed = pd.Series(False, index=out.index)
    # a changed pairing is not the frozen game: never settle it, never feed it to a model
    out.loc[changed, ["home_points", "away_points", "home_postgame_wp"]] = None
    out.loc[changed, "completed"] = False
    if mirrored.any():
        hp, ap = out.home_points.copy(), out.away_points.copy()
        out.loc[mirrored, "home_points"] = ap[mirrored]
        out.loc[mirrored, "away_points"] = hp[mirrored]
    out["flipped"] = mirrored.to_numpy()
    out["settled"] = (out.completed.fillna(False).astype(bool)
                      & out.home_points.notna() & out.away_points.notna())
    # a moved non-neutral game: the frozen away team hosts, so home advantage flips sign
    out["home_ind"] = np.where(out.neutral_site.astype(bool), 0.0,
                               np.where(out.flipped, -1.0, 1.0))
    out["kickoff"] = out.cfbd_start.where(out.cfbd_start.notna(), out.start_date)
    out["kickoff_moved"] = listed & (out.cfbd_start != out.start_date)

    def _rows(mask: pd.Series, **extra) -> list[dict]:
        return [{"id": int(g.game_id), "wk": int(g.week), "home": g.home_team, "away": g.away_team,
                 "neutral": bool(g.neutral_site),
                 **{k: (f(g) if callable(f) else f) for k, f in extra.items()}}
                for g in out[mask].itertuples()]

    drift: dict[str, Any] = {
        "mirrored": _rows(mirrored),
        "rekeyed": _rows(rekeyed, cfbd_id=lambda g: int(g.cfbd_id)),
        "missing": _rows(out.status == "missing"),
        "changed": _rows(changed, cfbd_home=lambda g: g.cfbd_home, cfbd_away=lambda g: g.cfbd_away),
        "kickoff_moved": _rows(out.kickoff_moved, frozen=lambda g: g.start_date,
                               now=lambda g: g.cfbd_start,
                               tbd=lambda g: bool(g.start_time_tbd)),
        "week_moved": _rows(out.cfbd_week.notna()
                            & (out.cfbd_week.fillna(-1).astype(int) != out.week),
                            cfbd_week=lambda g: int(g.cfbd_week)),
        "neutral_changed": _rows(out.cfbd_neutral.notna()
                                 & (out.cfbd_neutral.fillna(False).astype(bool)
                                    != out.neutral_site.astype(bool)),
                                 cfbd_neutral=lambda g: bool(g.cfbd_neutral)),
    }
    drift["n_listed"] = int(listed.sum())
    drift["n_frozen"] = int(len(out))
    for k in ("mirrored", "rekeyed", "missing", "changed"):
        if drift[k]:
            shown = drift[k][:12]
            print(f"  schedule drift · {k} ({len(drift[k])}): " + "; ".join(
                f"{r['id']} {r['away']} at {r['home']}" for r in shown)
                + (f"; … {len(drift[k]) - len(shown)} more" if len(drift[k]) > len(shown) else ""))
    return out.drop(columns=["cfbd_home", "cfbd_away", "cfbd_start"]), drift


# --------------------------------------------------------------------------- validate
def _winner(home: pd.Series, away: pd.Series, hp: pd.Series, ap: pd.Series) -> pd.Series:
    return pd.Series(np.where(hp > ap, home, away), index=home.index)


def validate(aligned: pd.DataFrame, raw: pd.DataFrame,
             now: datetime | None = None) -> dict:
    """Invariants a scoreable results frame must satisfy. Returns
    {"ok": bool, "checks": [{"id", "name", "severity", "ok", "n", "detail"}], "n_settled"}.

    HARD (any failure quarantines the results — nothing sealed, page flagged, workflow fails):
      winner-by-name      for every settled game the winner named by our aligned frame is the
                          winner CFBD names — the invariant the orientation bug violated
      team-records        per-team W-L derived from our frame equals W-L derived from CFBD's own
                          rows by team name over the same games (catches any mis-assignment)
      settled-after-kick  no game is settled before its (live) kickoff
      no-ties             a completed FBS game has a winner (overtime since 1996)
      points-sane         integer, non-negative, no absurd totals
      unique-ids          no CFBD id is claimed by two frozen games
    SOFT (reported, never blocking):
      cfbd-wp-agrees      CFBD's own postgame win probability names the same winner it scores
      changed-pairings    frozen games whose teams CFBD no longer lists (left unsettled)
      missing-games       frozen games CFBD no longer lists at all (cancelled?)
      rekeyed-games       frozen games matched to a new CFBD id
      kickoff-moved       games whose kickoff differs from the frozen one (rule uses live time)
    """
    now = now or datetime.now(UTC)
    s = aligned[aligned.settled].copy()
    checks: list[dict] = []

    def add(cid: str, name: str, severity: str, bad: pd.DataFrame | list, detail: str = "") -> None:
        n = len(bad)
        checks.append({"id": cid, "name": name, "severity": severity, "ok": n == 0, "n": int(n),
                       "detail": detail if n else ""})

    raw_by_id = raw.set_index("game_id") if len(raw) else None

    # winner-by-name
    if raw_by_id is not None and len(s):
        rr = raw_by_id.loc[s.cfbd_id]
        ours = _winner(s.home_team, s.away_team, s.home_points, s.away_points)
        theirs = pd.Series(np.where(rr.home_points.to_numpy() > rr.away_points.to_numpy(),
                                    rr.home_team.to_numpy(), rr.away_team.to_numpy()),
                           index=s.index)
        bad = s[ours != theirs]
        add("winner-by-name", "Winner named by our frame = winner named by CFBD", "hard", bad,
            "; ".join(f"{int(g.game_id)} {g.away_team} at {g.home_team}" for g in bad.itertuples()))
    else:
        add("winner-by-name", "Winner named by our frame = winner named by CFBD", "hard", [])

    # team-records: independent derivation by team name from CFBD's rows
    if raw_by_id is not None and len(s):
        rr = raw_by_id.loc[s.cfbd_id]
        rec_theirs: dict[str, list[int]] = {}
        for h, a, hp, ap in zip(rr.home_team, rr.away_team, rr.home_points, rr.away_points,
                                strict=True):
            w, lo = (h, a) if hp > ap else (a, h)
            rec_theirs.setdefault(w, [0, 0])[0] += 1
            rec_theirs.setdefault(lo, [0, 0])[1] += 1
        rec_ours: dict[str, list[int]] = {}
        for g in s.itertuples():
            w, lo = ((g.home_team, g.away_team) if g.home_points > g.away_points
                     else (g.away_team, g.home_team))
            rec_ours.setdefault(w, [0, 0])[0] += 1
            rec_ours.setdefault(lo, [0, 0])[1] += 1
        diff = sorted(t for t in set(rec_ours) | set(rec_theirs)
                      if rec_ours.get(t) != rec_theirs.get(t))
        add("team-records", "Per-team W-L equals CFBD-derived W-L", "hard", diff,
            "; ".join(f"{t}: ours {rec_ours.get(t)} vs CFBD {rec_theirs.get(t)}" for t in diff))
    else:
        add("team-records", "Per-team W-L equals CFBD-derived W-L", "hard", [])

    # settled-after-kick
    if len(s):
        kick = pd.to_datetime(s.kickoff, utc=True, errors="coerce")
        bad = s[kick.isna() | (kick > now + timedelta(minutes=5))]
        add("settled-after-kick", "No result recorded before its kickoff", "hard", bad,
            "; ".join(f"{int(g.game_id)} kickoff {g.kickoff}" for g in bad.itertuples()))
    else:
        add("settled-after-kick", "No result recorded before its kickoff", "hard", [])

    # no-ties
    bad = s[s.home_points == s.away_points]
    add("no-ties", "Every completed game has a winner", "hard", bad,
        "; ".join(f"{int(g.game_id)} {g.home_points}-{g.away_points}" for g in bad.itertuples()))

    # points-sane
    if len(s):
        hp, ap = s.home_points.astype(float), s.away_points.astype(float)
        bad = s[(hp < 0) | (ap < 0) | (hp != hp.round()) | (ap != ap.round()) | (hp + ap > 200)]
    else:
        bad = s
    add("points-sane", "Scores are non-negative integers with a plausible total", "hard", bad,
        "; ".join(f"{int(g.game_id)} {g.home_points}-{g.away_points}" for g in bad.itertuples()))

    # unique-ids
    dup = aligned[aligned.status != "missing"].cfbd_id
    dups = sorted(set(dup[dup.duplicated()].astype(int)))
    add("unique-ids", "No CFBD game is claimed by two frozen games", "hard", dups,
        ", ".join(map(str, dups)))

    # soft
    if len(s) and s.home_postgame_wp.notna().any():
        w = s[s.home_postgame_wp.notna()]
        # our frame is in frozen orientation; CFBD's wp is in CFBD's — undo the flip
        wp_home = np.where(w.flipped, 1 - w.home_postgame_wp.astype(float),
                           w.home_postgame_wp.astype(float))
        bad = w[(wp_home > 0.5) != (w.home_points > w.away_points)]
        add("cfbd-wp-agrees", "CFBD's postgame win probability names the scored winner", "soft",
            bad, "; ".join(f"{int(g.game_id)} {g.away_team} at {g.home_team}"
                           for g in bad.itertuples()))
    else:
        add("cfbd-wp-agrees", "CFBD's postgame win probability names the scored winner", "soft", [])
    for status, cid, name in (
            ("changed", "changed-pairings", "Frozen games whose teams changed"),
            ("missing", "missing-games", "Frozen games CFBD no longer lists"),
            ("rekeyed", "rekeyed-games", "Frozen games matched to a new CFBD id")):
        bad = aligned[aligned.status == status]
        add(cid, name, "soft", bad, "; ".join(
            f"{int(g.game_id)} {g.away_team} at {g.home_team}" for g in bad.itertuples()))
    moved = aligned[aligned.kickoff_moved.fillna(False).astype(bool)]
    add("kickoff-moved", "Games whose kickoff moved since the freeze (live time is used)", "soft",
        moved, f"{len(moved)} game(s)")

    ok = all(c["ok"] for c in checks if c["severity"] == "hard")
    report = {"ok": ok, "checked_at": now.isoformat(timespec="seconds"),
              "n_settled": int(len(s)), "checks": checks}
    hard_bad = [c for c in checks if c["severity"] == "hard" and not c["ok"]]
    if hard_bad:
        print("  RESULTS QUARANTINED — hard checks failed: " + "; ".join(
            f"{c['id']} ({c['n']}): {c['detail'][:200]}" for c in hard_bad))
    else:
        soft_bad = [c for c in checks if c["severity"] == "soft" and not c["ok"]]
        print(f"  results validated: {len(s)} settled, all hard checks pass"
              + (f", soft notes: {', '.join(c['id'] for c in soft_bad)}" if soft_bad else ""))
    return report
