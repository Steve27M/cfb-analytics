"""Build the two companion learn pages: docs/glossary.html and docs/models.html.

glossary.html — a plain-English data dictionary for every metric shown on the comparison
dashboard, each with a live 2025 FBS distribution (min / median / max + leader & laggard).

models.html — an explainer + effectiveness showcase for the project's statistical models. It
reads the real model outputs written to data/results/ (metrics, R & Python coefficients, and the
held-out game predictions) so the page can plot a genuine calibration curve, compare the win-prob
model against naive and Vegas-market baselines, and prove the R<->Python parity gate numerically.

Both pages reuse the team list in data/gold/compare_data.json (built by build_compare.py) so the
glossary distributions and the models page's interactive matchup predictor stay in sync with the
comparison dashboard. Run build_compare.py first.
"""
from __future__ import annotations

import json
from statistics import median

import pandas as pd

from cfb_analytics.config import REPO_ROOT

SEASON = 2025
RESULTS = REPO_ROOT / "data" / "results"
COMPARE_JSON = REPO_ROOT / "data" / "gold" / "compare_data.json"
GLOSS_TEMPLATE = REPO_ROOT / "dashboard" / "glossary_template.html"
MODELS_TEMPLATE = REPO_ROOT / "dashboard" / "models_template.html"
TEAM_TEMPLATE = REPO_ROOT / "dashboard" / "team_template.html"
INDEX_TEMPLATE = REPO_ROOT / "dashboard" / "index_template.html"
LIVE_JSON = REPO_ROOT / "data" / "gold" / "live_team_stats.json"   # written by build_live.py
REPORT_JSON = REPO_ROOT / "data" / "gold" / "reference_report.json"  # written by build_compare.py
GLOSS_OUT = REPO_ROOT / "docs" / "glossary.html"
MODELS_OUT = REPO_ROOT / "docs" / "models.html"
TEAM_OUT = REPO_ROOT / "docs" / "team.html"
INDEX_OUT = REPO_ROOT / "docs" / "index.html"


# --------------------------------------------------------------------------- glossary


def _val(t: dict, key: str):
    """A field of a compare-page team, with dotted access into nested dicts (radar.exp)."""
    v: object = t
    for part in key.split("."):
        v = v.get(part) if isinstance(v, dict) else None
    return v


def _dist(teams: list[dict], key: str, dec: int, direction: str = "high",
          disp: str | None = None) -> dict | None:
    """min/median/max of a numeric field across teams, the leader & laggard team, and every
    team ranked best -> worst by the stat's direction (`ranked`), for the per-stat dropdown.
    `disp` names a field whose string is shown instead of the number (e.g. the W-L record)."""
    vals = [(_val(t, key), t["name"], t["abbr"], t.get(disp) if disp else None)
            for t in teams if _val(t, key) is not None]
    if not vals:
        return None
    nums = [v[0] for v in vals]
    lo = min(vals, key=lambda v: v[0])
    hi = max(vals, key=lambda v: v[0])
    ranked = sorted(vals, key=lambda v: v[0], reverse=(direction == "high"))
    return {
        "min": round(min(nums), dec), "med": round(median(nums), dec),
        "max": round(max(nums), dec),
        "hi": {"name": hi[1], "abbr": hi[2], "val": round(hi[0], dec)},
        "lo": {"name": lo[1], "abbr": lo[2], "val": round(lo[0], dec)},
        "ranked": [{"name": v[1], "abbr": v[2], "val": round(v[0], dec),
                    **({"disp": v[3]} if v[3] is not None else {})} for v in ranked],
    }


# Each stat: how it's defined, how to read it, which direction is "good", and (for numeric
# fields present in compare_data.json) the live 2025 distribution key + display decimals.
GLOSSARY_DEFS: list[tuple[str, list[dict]]] = [
    ("Team strength & record", [
        {"name": "Team Rating", "key": None, "dir": "high",
         "def": "This project's own rating, in points: how much better or worse than an average "
                "FBS team, on a neutral field. Every team starts at its preseason strength and "
                "moves toward its opponent-adjusted scoring margins as games settle.",
         "read": "This is the rating the site stands behind - it drives the forecast scoreboard "
                 "and the 2026 team profiles. A team at +20 facing one at +5 is favoured by about "
                 "15 on neutral turf. It exists only for a season in progress; for a completed "
                 "season, SP+ below is the strength summary."},
        {"name": "SP+ Rating", "key": "spPlus", "dec": 1, "dir": "high", "sign": True,
         "def": "A third-party tempo- and opponent-adjusted rating (Bill Connelly, via "
                "CollegeFootballData) expressed in points against an average FBS team.",
         "read": "Not this project's rating - it is ingested, used as a model input, and shown "
                 "for reference. Positive is above average; the chip on a team page carries the "
                 "national rank (1 = best)."},
        {"name": "Record", "key": "winPct", "dec": 3, "dir": "high", "disp": "record",
         "def": "Wins and losses over the season, from the official records.",
         "read": "Context, not a ranking input - a 10-2 team in a weak league can rate below an "
                 "8-4 team in a brutal one. Read it next to Strength of Schedule. Teams are "
                 "ranked here by win rate, so a 12-1 team outranks an 11-2 one."},
    ]),
    ("Scoring & production", [
        {"name": "Points / Game", "key": "ppg", "dec": 1, "dir": "high",
         "def": "Average points scored per game.",
         "read": "Raw output - not schedule-adjusted, so read it against Strength of Schedule. "
                 "Combined with the opponent's Points Allowed to project a game's total."},
        {"name": "Points Allowed", "key": "oppPpg", "dec": 1, "dir": "low",
         "def": "Average points surrendered per game.",
         "read": "Lower is better. A defence-first team can look ordinary on scoring and still "
                 "rate highly."},
        {"name": "Yards / Game", "key": "ypg", "dec": 0, "dir": "high",
         "def": "Total offence per game, taken from the official season totals - not counted "
                "from play-by-play, which records phantom yardage on plays that gained nothing.",
         "read": "Volume, not efficiency: a fast-tempo team runs more plays and piles up yards "
                 "without necessarily being efficient. Cross-check with EPA and Success Rate."},
        {"name": "Yards Allowed", "key": "oppYpg", "dec": 0, "dir": "low",
         "def": "Total offence surrendered per game, from the official season totals.",
         "read": "Lower is better, with the same tempo caveat as Yards / Game."},
        {"name": "Turnover Margin", "key": "toMargin", "dec": 0, "dir": "high", "sign": True,
         "def": "Takeaways minus giveaways over the season, from the official totals.",
         "read": "The single largest source of luck in a football season. A team riding a big "
                 "positive margin is usually a candidate to fall back the following year, which "
                 "is why the forecast models lean on efficiency rather than on this."},
        {"name": "Third-Down Rate", "key": "thirdDown", "dec": 1, "dir": "high",
         "def": "Share of third downs converted, from the official totals.",
         "read": "Situational efficiency: staying on the field. It correlates with Success Rate, "
                 "but it is the number broadcasts actually quote."},
    ]),
    ("Play-by-play efficiency", [
        {"name": "EPA / Play (Off)", "key": "epaOff", "dec": 3, "dir": "high", "sign": True,
         "def": "Expected Points Added per offensive play. Every game state (down, distance, "
                "field position) has an expected point value; EPA is how much a play changes it, "
                "averaged over the season.",
         "read": "Around zero is average; elite offences live near +0.20. The most predictive "
                 "single efficiency number and the biggest driver of the game win-probability "
                 "model. Verified to track CFBD's independent implementation (r about 0.95)."},
        {"name": "EPA / Play (Def)", "key": "epaDef", "dec": 3, "dir": "low", "sign": True,
         "def": "Expected Points Added allowed per defensive play.",
         "read": "Negative is good - the defence is taking expected points away from offences. "
                 "On the profile radar this axis is inverted so that more is better."},
        {"name": "Net EPA / Play", "key": "netEpa", "dec": 3, "dir": "high", "sign": True,
         "def": "Offensive EPA per play minus defensive EPA per play allowed - one efficiency "
                "number for the whole team.",
         "read": "The cleanest one-line efficiency summary; it tracks SP+ closely."},
        {"name": "Success Rate % (Off)", "key": "srOff", "dec": 0, "dir": "high",
         "def": "Share of plays that are successful - 50%+ of needed yards on 1st down, 70%+ on "
                "2nd, 100% on 3rd or 4th.",
         "read": "Consistency (staying on schedule) rather than explosiveness. About 45%+ is "
                 "strong. High EPA with a mediocre Success Rate is a boom-or-bust profile."},
        {"name": "Success Rate % (Def)", "key": "srDef", "dec": 0, "dir": "low",
         "def": "Share of opponent plays that were successful.",
         "read": "Lower is better. Shown on the efficiency split as the rate the defence allows."},
        {"name": "Explosive Play Rate", "key": "explosiveness", "dec": 1, "dir": "high",
         "def": "Share of scrimmage plays gaining 15+ yards, with garbage time excluded.",
         "read": "The big-play dimension of an offence. This is not the same as CFBD's "
                 "explosiveness, which averages the predicted points added of successful plays - "
                 "the two correlate only about 0.48, so this project uses its own name for its "
                 "own definition. High Success Rate plus a high explosive rate is the ideal."},
    ]),
    ("Context", [
        {"name": "Strength of Schedule", "key": "sosRank", "dec": 0, "dir": "rank",
         "def": "Rank by the average SP+ rating of the opponents a team actually played "
                "(1 = toughest slate). Computed from opponents faced, because the SP+ strength "
                "of schedule field was empty for this season.",
         "read": "Read every counting stat through this lens - gaudy scoring against a #120 "
                 "schedule means less than solid numbers against a #10 one. Feeds the "
                 "win-probability models."},
        {"name": "Recruiting Rank", "key": "recruitRank", "dec": 0, "dir": "rank",
         "def": "The team's 247Sports recruiting-class rank (1 = best incoming talent). Only the "
                "top ~25 classes per season are published, so most teams have no value.",
         "read": "A proxy for raw talent. The recruiting model here shows it explains about 37% "
                 "of the variance in team rating - real signal, far from the whole story."},
        {"name": "Team Profile Radar", "key": None, "dir": "high",
         "def": "The six-axis shape on each team page: offence and defence (EPA percentiles), "
                "special teams (the SP+ component), explosive-play rate, offensive success rate, "
                "and talent (recruiting rank).",
         "read": "Each axis is a 0-100 percentile against FBS, so 50 is the median team and 100 "
                 "is the best in the country. The axes are percentile views of the metrics "
                 "above, not additional measurements."},
    ]),
    ("Projection", [
        {"name": "2026 Projected Wins", "key": "proj2026", "dec": 1, "dir": "high",
         "def": "Expected wins from the preseason priors model, which forecasts games before any "
                "current-season form exists, using prior-year strength and recruiting.",
         "read": "A preseason expectation, not a guarantee - read it as about this many wins if "
                 "the season plays out as expected. The forecast scoreboard scores it against "
                 "reality all season."},
    ]),
]


def build_glossary(teams: list[dict]) -> dict:
    groups = []
    for gname, stats in GLOSSARY_DEFS:
        out_stats = []
        for s in stats:
            entry = {"name": s["name"], "def": s["def"], "read": s["read"], "dir": s["dir"]}
            if s.get("key"):
                entry["dist"] = _dist(teams, s["key"], s["dec"], s["dir"], s.get("disp"))
                entry["dec"] = s["dec"]
            out_stats.append(entry)
        groups.append({"name": gname, "stats": out_stats})
    roster = sorted(({"name": t["name"], "abbr": t["abbr"]} for t in teams),
                    key=lambda t: t["name"])
    out = {"season": SEASON, "nTeams": len(teams), "groups": groups, "teams": roster}
    if REPORT_JSON.exists():   # what was verified, and against what
        out["verification"] = json.loads(REPORT_JSON.read_text(encoding="utf-8"))
    return out


# Stat Guide metrics the live lane can state for the season in progress. Record, scoring and
# schedule come from the live scoreboard on the page itself (FBS opponents only, like the rest of
# the site), so they are not repeated here. The EPA family is added only when the season's EPA
# passed team_stats.epa_quality — build_live.py leaves those fields out otherwise.
LIVE_ALWAYS = {"SP+ Rating", "Yards / Game", "Yards Allowed", "Explosive Play Rate",
               "Turnover Margin", "Third-Down Rate"}
LIVE_EPA = {"EPA / Play (Off)", "EPA / Play (Def)", "Net EPA / Play", "Success Rate % (Off)",
            "Success Rate % (Def)"}


def build_live(live: dict) -> dict:
    """The live season in the same shape as the glossary groups (value + best->worst ranking per
    stat), plus the provenance the page must show: coverage and the EPA quality verdict."""
    teams = live["teams"]
    wanted = LIVE_ALWAYS | (LIVE_EPA if live["epa_quality"]["ok"] else set())
    stats = []
    for _, defs in GLOSSARY_DEFS:
        for s in defs:
            if s["name"] not in wanted or not s.get("key"):
                continue
            dist = _dist(teams, s["key"], s["dec"], s["dir"], s.get("disp"))
            if dist:
                stats.append({"name": s["name"], "def": s["def"], "read": s["read"],
                              "dir": s["dir"], "dec": s["dec"], "dist": dist, "src": "pbp"})
    return {
        "season": live["season"], "built_at": live["built_at"],
        "through_week": live["through_week"], "games_settled": live["games_settled"],
        "games_with_pbp": live["games_with_pbp"], "epa_quality": live["epa_quality"],
        "epa_reference": live["epa_reference"],
        "withheld": sorted(LIVE_EPA) if not live["epa_quality"]["ok"] else [],
        "teams": {t["name"]: {k: t.get(k) for k in ("record", "games", "pbpGames", "spPlus",
                                                     "spRank", "radar", "margins")}
                  for t in teams},
        "groups": [{"name": f"From the warehouse · {live['season']} · all games through week "
                            f"{live['through_week']}", "stats": stats}],
    }


# --------------------------------------------------------------------------- models


def _metrics(name: str, lang: str = "r") -> dict:
    """Read a metrics__<name>__<lang>.csv into a {metric: value} dict (numeric where possible)."""
    path = RESULTS / f"metrics__{name}__{lang}.csv"
    if not path.exists():
        return {}
    df = pd.read_csv(path)
    out: dict = {}
    has_model = "model" in df.columns
    for _, row in df.iterrows():
        try:
            val = float(row["value"])
        except (TypeError, ValueError):
            val = row["value"]
        out[row["metric"]] = val  # bare key (last row wins on collision)
        if has_model:  # composite key disambiguates files with repeated metric names
            out[f"{row['model']}_{row['metric']}"] = val
    return out


def _calibration(name: str = "game", bins: int = 8) -> list[dict]:
    """Bin held-out predicted win probs and compare to the realized win rate (model reliability)."""
    path = RESULTS / f"gamepred__{name}__r.csv"
    if not path.exists():
        return []
    df = pd.read_csv(path)
    edges = [i / bins for i in range(bins + 1)]
    out = []
    for i in range(bins):
        lo, hi = edges[i], edges[i + 1]
        m = (df["home_win_prob"] >= lo) & (
            df["home_win_prob"] < hi if i < bins - 1 else df["home_win_prob"] <= hi)
        sub = df[m]
        if len(sub) == 0:
            continue
        out.append({
            "lo": round(lo, 3), "hi": round(hi, 3), "mid": round((lo + hi) / 2, 3),
            "n": int(len(sub)),
            "pred": round(float(sub["home_win_prob"].mean()), 3),
            "actual": round(float(sub["home_won"].mean()), 3),
        })
    return out


def _coef_parity(name: str) -> list[dict]:
    """Pair R and Python coefficient estimates term-by-term to demonstrate the parity gate."""
    r_path, py_path = RESULTS / f"coef__{name}__r.csv", RESULTS / f"coef__{name}__py.csv"
    if not (r_path.exists() and py_path.exists()):
        return []
    r_df, py_df = pd.read_csv(r_path), pd.read_csv(py_path)
    py_est = dict(zip(py_df["term"], py_df["estimate"], strict=False))
    rows = []
    for _, row in r_df.iterrows():
        term = row["term"]
        rows.append({
            "term": term,
            "r": round(float(row["estimate"]), 4),
            "py": round(float(py_est.get(term, float("nan"))), 4),
            "odds": (round(float(row["odds_ratio"]), 3)
                     if "odds_ratio" in r_df.columns and pd.notna(row["odds_ratio"]) else None),
            "p": (float(row["p_value"]) if "p_value" in r_df.columns else None),
        })
    return rows


# Plain-English term labels for the game win-prob coefficient table.
GAME_TERMS = {
    "(Intercept)": "Home-field baseline",
    "off_epa_diff": "Offensive EPA/play edge",
    "def_epa_diff": "Defensive EPA/play edge",
    "roll3_net_epa_diff": "Recent form (last 3 games)",
    "win_pct_diff": "Win % edge",
    "sos_diff": "Schedule-strength edge",
}


def _market_edge() -> dict:
    """Read the market-efficiency diagnostic (metrics + blend curve); {} if it hasn't been run."""
    metrics = _metrics("market_edge", "py")
    if not metrics:
        return {}
    blend_path = RESULTS / "market_blend__py.csv"
    blend = []
    if blend_path.exists():
        bdf = pd.read_csv(blend_path)
        blend = [{"w": round(float(r.w), 2), "brier": round(float(r.brier), 4)}
                 for r in bdf.itertuples()]
    return {"metrics": metrics, "blend": blend}


def build_models(teams: list[dict]) -> dict:
    game = _metrics("game")
    game_cv = _metrics("game_cv")
    priors = _metrics("priors")
    # slim the team list for the interactive matchup predictor
    slim = [{"id": t["id"], "abbr": t["abbr"], "name": t["name"], "spPlus": t["spPlus"],
             "primary": t["primary"], "secondary": t["secondary"], "spRank": t.get("spRank")}
            for t in teams]
    slim.sort(key=lambda x: x["spPlus"], reverse=True)

    game_coef = _coef_parity("game")
    for c in game_coef:
        c["label"] = GAME_TERMS.get(c["term"], c["term"])

    return {
        "season": SEASON, "marginSd": 13.5, "teams": slim,
        "game": {"metrics": {**game, **game_cv}, "coef": game_coef,
                 "calib": _calibration("game")},
        "market": _market_edge(),
        "priors": {"metrics": priors},
        "inseason": {"metrics": _metrics("inseason")},
        "recruiting": _metrics("recruiting"),
        "stability": _metrics("stability"),
        "cpoe": _metrics("cpoe"),
        "ryoe": _metrics("ryoe"),
        "poisson": _metrics("poisson"),
        "shrinkage": _metrics("shrinkage"),
        "archetype": _metrics("archetype"),
    }


# --------------------------------------------------------------------------- emit


def _inject(template, token: str, payload: dict, out) -> None:
    if not template.exists():
        print(f"  (template missing: {template.name})")
        return
    html = template.read_text(encoding="utf-8").replace(token, json.dumps(payload))
    out.write_text(html, encoding="utf-8")
    print(f"  wrote {out}")


def build() -> None:
    if not COMPARE_JSON.exists():
        raise SystemExit("compare_data.json not found — run build_compare.py first.")
    teams = json.loads(COMPARE_JSON.read_text(encoding="utf-8"))["teams"]

    gloss = build_glossary(teams)
    models = build_models(teams)
    print(f"  glossary: {sum(len(g['stats']) for g in gloss['groups'])} stats defined")
    print(f"  models: game AUC {models['game']['metrics'].get('auc'):.3f} · "
          f"{len(models['game']['calib'])} calibration bins · "
          f"{len(models['game']['coef'])} coefficients (R vs Python)")

    _inject(GLOSS_TEMPLATE, "__GLOSSARY_DATA__", gloss, GLOSS_OUT)
    _inject(MODELS_TEMPLATE, "__MODELS_DATA__", models, MODELS_OUT)
    # team.html: one standardized profile for every team — the compare page's team objects
    # (identity, colors, radar, margins, leaders) plus every Stat Guide metric with its
    # best -> worst ranking, so a team's value and national rank come from the same numbers
    # the guide shows. The 2026 block is fetched live from docs/forecast_data.json.
    # the landing page: one sentence of thesis, the live headline, and what was verified
    _inject(INDEX_TEMPLATE, "__HOME_DATA__",
            {"season": 2026, "verification": gloss.get("verification")}, INDEX_OUT)

    team_page = {"season": SEASON, "teams": teams, "groups": gloss["groups"]}
    if LIVE_JSON.exists():
        team_page["live"] = build_live(json.loads(LIVE_JSON.read_text(encoding="utf-8")))
        q = team_page["live"]["epa_quality"]
        print(f"  team profiles: live {team_page['live']['season']} stats through week "
              f"{team_page['live']['through_week']} · EPA "
              + ("published" if q["ok"]
                 else f"WITHHELD (winner agreement {q['winner_agreement']})"))
    else:
        print("  team profiles: no live_team_stats.json — 2026 view uses the scoreboard + baseline")
    _inject(TEAM_TEMPLATE, "__TEAM_DATA__", team_page, TEAM_OUT)


if __name__ == "__main__":
    build()
