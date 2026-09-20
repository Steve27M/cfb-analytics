"""Build the data payload for the team-comparison dashboard (docs/compare.html).

Pulls every 2025 FBS team's identity (name, conference, colors, ESPN logo), season stats (SP+,
scoring, yards, EPA, success rate, strength of schedule, recruiting rank, projected 2026 wins),
and top passing/rushing/receiving leaders (from CFBD's season-stats API, since 2025 play-by-play
is only ~56% player-attributed). Radar axes are percentiles across FBS. The head-to-head model
coefficients are embedded so the page can predict any matchup client-side. Emits data/gold/
compare_data.json and injects it into docs/compare.html via dashboard/compare_template.html.
"""
from __future__ import annotations

import json
import os
import re

import pandas as pd
import requests

from cfb_analytics.config import REPO_ROOT
from cfb_analytics.db import read_only_conn
from cfb_analytics.reference import check_season
from cfb_analytics.team_stats import team_stats

SEASON = 2025
TEMPLATE = REPO_ROOT / "dashboard" / "compare_template.html"
OUT_HTML = REPO_ROOT / "docs" / "compare.html"
OUT_JSON = REPO_ROOT / "data" / "gold" / "compare_data.json"
REPORT_JSON = REPO_ROOT / "data" / "gold" / "reference_report.json"


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _leaders(key: str) -> dict:
    """Top passer/rusher/receiver per team from CFBD season stats (best-effort)."""
    if not key:
        return {}
    base, params = "https://api.collegefootballdata.com/stats/player/season", {"year": str(SEASON)}
    hdr = {"Authorization": f"Bearer {key}"}
    want = {"passing": ("YDS", "TD", "PCT"), "rushing": ("YDS", "TD"), "receiving": ("YDS", "TD")}
    rows: dict[tuple, dict] = {}
    for cat in want:
        try:
            data = requests.get(base, params={**params, "category": cat},
                                 headers=hdr, timeout=60).json()
        except Exception:  # noqa: BLE001
            continue
        for r in data:
            k = (r["team"], cat, r["player"])
            rows.setdefault(k, {})[r["statType"]] = r["stat"]
    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    leaders: dict = {}
    for (team, cat, player), stats in rows.items():
        yds = _f(stats.get("YDS"))
        cur = leaders.setdefault(team, {}).get(cat)
        if cur is None or yds > cur["yds"]:
            leaders[team][cat] = {"name": player, "yds": yds,
                                  "td": stats.get("TD", 0), "pct": stats.get("PCT")}
    return leaders


def _pctile(s: pd.Series, invert: bool = False) -> pd.Series:
    r = s.rank(pct=True)
    return ((1 - r) if invert else r) * 100


def _fmt_leader(d: dict | None) -> list:
    """Format a leader's stat line: 'X,XXX yds · N TD · P%'."""
    def num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None
    if not d:
        return ["—", "—"]
    yv, tv, pv = num(d.get("yds")), num(d.get("td")), num(d.get("pct"))
    if pv is not None and pv <= 1.5:   # CFBD returns completion % as a fraction
        pv *= 100
    yds = f"{int(yv):,} yds" if yv else "—"
    td = f" · {int(tv)} TD" if tv else ""
    pct = f" · {pv:.0f}%" if pv else ""
    return [d["name"], f"{yds}{td}{pct}"]


def build() -> dict:
    con = read_only_conn()
    try:
        df = team_stats(con, SEASON)   # shared with the live lane (build_live.py)
        # Nothing is published until the numbers have been checked against the official source.
        report = check_season(con, SEASON, df)
        REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
        REPORT_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")
        if not report["ok"]:
            raise SystemExit("reference check FAILED — refusing to publish (see "
                             f"{REPORT_JSON.relative_to(REPO_ROOT)})")
        margins_df = con.execute(f"""
            select team, week, point_margin from gold.fct_team_game
            where season = {SEASON} and team_sk <> '-1' order by team, week, game_id
        """).fetch_df()
    finally:
        con.close()
    margins = {t: g.sort_values("week")["point_margin"].astype(int).tolist()
               for t, g in margins_df.groupby("team")}

    df = df.dropna(subset=["sp_rating"]).reset_index(drop=True)
    # radar percentiles (0-100) across FBS
    df["r_off"] = _pctile(df["epa_off"])
    df["r_def"] = _pctile(df["epa_def"], invert=True)          # lower EPA allowed = better
    df["r_st"] = _pctile(df["special_teams_rating"].fillna(df["special_teams_rating"].median()))
    df["r_exp"] = _pctile(df["explosive_rate"].fillna(df["explosive_rate"].median()))
    df["r_eff"] = _pctile(df["sr_off"])
    df["r_tal"] = _pctile(df["recruit_rank"].fillna(130), invert=True)  # better rank = higher
    df["sos_rank"] = df["sos_metric"].rank(ascending=False, method="min")  # tougher schedule = #1

    leaders = _leaders(os.getenv("CFBD_API_KEY", ""))

    teams = []
    for _, t in df.iterrows():
        tl = leaders.get(t["team"], {})
        teams.append({
            "id": _slug(t["team"]), "abbr": t["abbr"] or t["team"][:4].upper(),
            "name": t["team"], "conference": t["conference"] or "FBS",
            "primary": t["primary"] or "#888888", "secondary": t["secondary"] or "#cccccc",
            "logo": (t["logo"] or "").replace("http://", "https://"),
            "record": f"{int(t['wins'])}-{int(t['losses'])}",
            "spRank": int(t["sp_ranking"]) if pd.notna(t["sp_ranking"]) else None,
            "spPlus": round(float(t["sp_rating"]), 1),
            "ppg": round(float(t["ppg"]), 1), "oppPpg": round(float(t["opp_ppg"]), 1),
            "ypg": round(float(t["ypg"]), 0), "oppYpg": round(float(t["opp_ypg"]), 0),
            "epaOff": round(float(t["epa_off"]), 3), "epaDef": round(float(t["epa_def"]), 3),
            "netEpa": round(float(t["net_epa"]), 3),
            "srOff": round(float(t["sr_off"]) * 100, 0),
            "srDef": round(float(t["sr_def"]) * 100, 0),
            "sosRank": int(t["sos_rank"]) if pd.notna(t["sos_rank"]) else None,
            "toMargin": int(t["turnover_margin"]) if pd.notna(t["turnover_margin"]) else None,
            "thirdDown": (round(float(t["third_down_rate"]) * 100, 1)
                          if pd.notna(t["third_down_rate"]) else None),
            "recruitRank": int(t["recruit_rank"]) if pd.notna(t["recruit_rank"]) else None,
            "proj2026": (round(float(t["proj_2026_wins"]), 1)
                         if pd.notna(t["proj_2026_wins"]) else None),
            "winPct": round(float(t["wins"]) / max(t["games"], 1), 3),
            "radar": {k: round(float(t[f"r_{k}"]), 0)
                      for k in ["off", "def", "st", "exp", "eff", "tal"]},
            "leaders": {"pass": _fmt_leader(tl.get("passing")),
                        "rush": _fmt_leader(tl.get("rushing")),
                        "rec": _fmt_leader(tl.get("receiving"))},
            "margins": margins.get(t["team"], []),
        })

    teams.sort(key=lambda x: x["spPlus"], reverse=True)
    # Head-to-head projection uses the SP+ rating difference (SP+ is a neutral-field points margin)
    # and the project's margin model (final margin ~ Normal(mean, 13.5)) to turn it into a win prob.
    payload = {"season": SEASON, "teams": teams, "marginSd": 13.5}

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload), encoding="utf-8")
    n_lead = sum(1 for t in teams if t["leaders"]["pass"][0] != "—")
    print(f"  {len(teams)} teams · {n_lead} with player leaders · "
          f"margins for {sum(1 for t in teams if t['margins'])} teams")

    if TEMPLATE.exists():
        html = TEMPLATE.read_text(encoding="utf-8")
        html = html.replace("__CFB_DATA__", json.dumps(payload))
        OUT_HTML.write_text(html, encoding="utf-8")
        print(f"  wrote {OUT_HTML}")
    return payload


if __name__ == "__main__":
    build()
