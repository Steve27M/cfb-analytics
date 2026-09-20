"""Live-season team stats for the 2026 team profiles (data/gold/live_team_stats.json).

Reads the LIVE lane's warehouse (data/cfb_live.duckdb — the in-progress season, built by
`run.py live` with the same dbt models as the sealed seasons) through the same team-stat query
the comparison page uses, so a 2026 yards-per-game or explosiveness figure means exactly what
the 2025 one means.

Two things differ from a sealed season, and both are reported rather than hidden:
  * coverage — play-by-play lags the scoreboard by a few days, so play-based stats are averaged
    over the games that HAVE play-by-play (pbpGames), never over games played;
  * EPA quality — the in-season feed's expected-points columns are provisional. team_stats.
    epa_quality() checks them against final scores on every refresh; when the season fails, every
    EPA-derived metric (EPA/play, net EPA, success rate, the OFF/DEF/EFF radar axes) is withheld
    and the pages fall back to the badged 2025 baseline. The moment the feed passes, they appear.

build_learn.py picks the JSON up when it exists; without it the team page keeps its baseline.
"""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime

import duckdb
import pandas as pd

from cfb_analytics.config import DUCKDB_PATH, REPO_ROOT
from cfb_analytics.team_stats import epa_quality, team_stats

LIVE_SEASON = int(os.getenv("CFB_LIVE_SEASON", "2026"))
LIVE_DB = REPO_ROOT / "data" / "cfb_live.duckdb"
OUT_JSON = REPO_ROOT / "data" / "gold" / "live_team_stats.json"


def _pctile(s: pd.Series, invert: bool = False) -> pd.Series:
    r = s.rank(pct=True)
    return ((1 - r) if invert else r) * 100


def _num(v, dec):
    return None if v is None or pd.isna(v) else round(float(v), dec)


def _sealed_reference() -> list[dict]:
    """The same quality check on every sealed season, for the note that explains the gate."""
    if not DUCKDB_PATH.exists() or DUCKDB_PATH.resolve() == LIVE_DB.resolve():
        return []
    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    try:
        seasons = [r[0] for r in con.execute(
            "select distinct season from gold.dim_game order by 1").fetchall()]
        return [{k: q[k] for k in ("season", "n_games", "corr", "winner_agreement")}
                for q in (epa_quality(con, s) for s in seasons)]
    finally:
        con.close()


def build() -> dict | None:
    if not LIVE_DB.exists():
        print(f"  no live warehouse at {LIVE_DB} — run `python run.py live` first; skipping")
        return None
    con = duckdb.connect(str(LIVE_DB), read_only=True)
    try:
        quality = epa_quality(con, LIVE_SEASON)
        df = team_stats(con, LIVE_SEASON)
        pbp = con.execute(f"""
            select offense_team as team, count(distinct game_id) as pbp_games
            from gold.fct_play where season = {LIVE_SEASON} group by 1
        """).fetch_df()
        through_week, n_settled = con.execute(f"""
            select max(week), count(*) from gold.dim_game
            where season = {LIVE_SEASON} and home_points is not null
        """).fetchone()
        n_pbp = con.execute(
            f"select count(distinct game_id) from gold.fct_play where season = {LIVE_SEASON}"
        ).fetchone()[0]
        margins_df = con.execute(f"""
            select team, week, point_margin from gold.fct_team_game
            where season = {LIVE_SEASON} and team_sk <> '-1' order by team, week, game_id
        """).fetch_df()
    finally:
        con.close()

    df = df.merge(pbp, on="team", how="left")
    df["pbp_games"] = df.pbp_games.fillna(0).astype(int)
    played = df.pbp_games.where(df.pbp_games > 0)
    # per game WITH play-by-play, never per game played
    df["ypg"] = df.off_yds / played
    df["opp_ypg"] = df.def_yds / played
    df["r_exp"] = _pctile(df.explosiveness)
    df["r_st"] = _pctile(df.special_teams_rating)
    df["sos_rank"] = df.sos_metric.rank(ascending=False, method="min")
    epa_ok = quality["ok"]
    if epa_ok:
        df["r_off"] = _pctile(df.epa_off)
        df["r_def"] = _pctile(df.epa_def, invert=True)
        df["r_eff"] = _pctile(df.sr_off)
    margins = {t: g.sort_values("week").point_margin.astype(int).tolist()
               for t, g in margins_df.groupby("team")}

    teams = []
    for _, t in df.iterrows():
        games = int(t.games)
        row = {
            "name": t.team, "abbr": t.abbr or t.team[:4].upper(),
            "record": f"{int(t.wins)}-{int(t.losses)}", "games": games,
            "pbpGames": int(t.pbp_games),
            "winPct": round(float(t.wins) / max(games, 1), 3),
            "ppg": _num(t.ppg, 1), "oppPpg": _num(t.opp_ppg, 1),
            "spPlus": _num(t.sp_rating, 1),
            "spRank": int(t.sp_ranking) if pd.notna(t.sp_ranking) else None,
            "ypg": _num(t.ypg, 0), "oppYpg": _num(t.opp_ypg, 0),
            "sosRank": int(t.sos_rank) if pd.notna(t.sos_rank) else None,
            "radar": {"exp": _num(t.r_exp, 0), "st": _num(t.r_st, 0)},
            "margins": margins.get(t.team, []),
        }
        if epa_ok:
            row.update({
                "epaOff": _num(t.epa_off, 3), "epaDef": _num(t.epa_def, 3),
                "netEpa": _num(t.net_epa, 3),
                "srOff": _num(t.sr_off * 100 if pd.notna(t.sr_off) else None, 0),
                "srDef": _num(t.sr_def * 100 if pd.notna(t.sr_def) else None, 0)})
            row["radar"].update({"off": _num(t.r_off, 0), "def": _num(t.r_def, 0),
                                 "eff": _num(t.r_eff, 0)})
        teams.append(row)
    # the live warehouse is rebuilt from scratch on every refresh and SQL returns rows in no
    # particular order: sort, so identical data always produces an identical file
    teams.sort(key=lambda r: r["name"])

    payload = {
        "season": LIVE_SEASON,
        "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "through_week": int(through_week) if through_week is not None else 0,
        "games_settled": int(n_settled), "games_with_pbp": int(n_pbp),
        "epa_quality": quality, "epa_reference": _sealed_reference(),
        "teams": teams,
    }
    # A refresh that finds nothing new must leave the pages byte-identical, so a weekly run does
    # not publish a commit whose only change is a timestamp: keep the previous build stamp.
    unchanged = False
    if OUT_JSON.exists():
        try:
            old = json.loads(OUT_JSON.read_text(encoding="utf-8"))
            same = {k: v for k, v in old.items() if k != "built_at"} == {
                k: v for k, v in payload.items() if k != "built_at"}
            if same:
                payload["built_at"], unchanged = old["built_at"], True
        except (ValueError, KeyError):
            pass
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload), encoding="utf-8")
    print(f"  live {LIVE_SEASON}: {len(teams)} teams through week {payload['through_week']} · "
          f"{n_pbp}/{n_settled} settled games have play-by-play")
    print(f"  EPA quality: corr {quality['corr']} · winner agreement {quality['winner_agreement']} "
          f"over {quality['n_games']} games -> "
          + ("PASS — EPA-family metrics published" if epa_ok
             else "FAIL — EPA-family metrics WITHHELD (2025 baseline stays on the page)"))
    print(f"  wrote {OUT_JSON}" + (" (no change since the last refresh)" if unchanged else ""))
    return payload


if __name__ == "__main__":
    build()
