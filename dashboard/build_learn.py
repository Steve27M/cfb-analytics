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
GLOSS_OUT = REPO_ROOT / "docs" / "glossary.html"
MODELS_OUT = REPO_ROOT / "docs" / "models.html"


# --------------------------------------------------------------------------- glossary


def _dist(teams: list[dict], key: str, dec: int) -> dict | None:
    """min/median/max of a numeric field across teams, with the leader & laggard team."""
    vals = [(t[key], t["name"], t["abbr"]) for t in teams if t.get(key) is not None]
    if not vals:
        return None
    nums = [v[0] for v in vals]
    lo = min(vals, key=lambda v: v[0])
    hi = max(vals, key=lambda v: v[0])
    return {
        "min": round(min(nums), dec), "med": round(median(nums), dec),
        "max": round(max(nums), dec),
        "hi": {"name": hi[1], "abbr": hi[2], "val": round(hi[0], dec)},
        "lo": {"name": lo[1], "abbr": lo[2], "val": round(lo[0], dec)},
    }


# Each stat: how it's defined, how to read it, which direction is "good", and (for numeric
# fields present in compare_data.json) the live 2025 distribution key + display decimals.
GLOSSARY_DEFS: list[tuple[str, list[dict]]] = [
    ("Team Rating & Record", [
        {"name": "SP+ Rating", "key": "spPlus", "dec": 1, "dir": "high",
         "def": "A tempo- and opponent-adjusted rating expressed in points: the margin a team "
                "would be expected to win (or lose) by against a perfectly average FBS team on a "
                "neutral field.",
         "read": "Positive is above average, negative below. A team rated +20 facing one rated +5 "
                 "is favored by ~15 on a neutral field. This is the single best summary of team "
                 "strength on the dashboard and drives the matchup projection."},
        {"name": "SP+ Rank", "key": None, "dir": "rank",
         "def": "The team's rank (1 = best) among all FBS teams by SP+ rating.",
         "read": "1 through ~136. Shown as the 'SP+ #' chip on the hero card."},
        {"name": "Record", "key": None, "dir": "high",
         "def": "Wins–losses over the season (FBS games with a resolved result).",
         "read": "Context, not a ranking input — a 10–2 team in a weak league can rate below an "
                 "8–4 team in a brutal one. Read it next to Strength of Schedule."},
        {"name": "Win %", "key": "winPct", "dec": 3, "dir": "high",
         "def": "Share of games won.",
         "read": "0 to 1. Feeds the win-probability models as win_pct_diff between two teams."},
    ]),
    ("Scoring & Yardage", [
        {"name": "Points / Game", "key": "ppg", "dec": 1, "dir": "high",
         "def": "Average points scored per game.",
         "read": "Raw output — not schedule-adjusted, so pad it against Strength of Schedule. "
                 "Combined with the opponent's Points Allowed to project a game's total."},
        {"name": "Points Allowed", "key": "oppPpg", "dec": 1, "dir": "low",
         "def": "Average points surrendered per game.",
         "read": "Lower is better. A defense-first team can have a low SP+-beating profile here."},
        {"name": "Yards / Game", "key": "ypg", "dec": 0, "dir": "high",
         "def": "Average total offensive yards per game.",
         "read": "Volume, not efficiency — a fast-tempo team runs more plays and piles up yards "
                 "without necessarily being efficient. Cross-check with EPA and Success Rate."},
        {"name": "Yards Allowed", "key": "oppYpg", "dec": 0, "dir": "low",
         "def": "Average total yards surrendered per game.",
         "read": "Lower is better, same tempo caveat as Yards / Game."},
    ]),
    ("Advanced Efficiency", [
        {"name": "EPA / Play (Off)", "key": "epaOff", "dec": 3, "dir": "high",
         "def": "Expected Points Added per offensive play. Every game state (down, distance, "
                "field position) has an expected point value; EPA is how much a play changes it, "
                "averaged over the season.",
         "read": "Around zero is average; elite offenses live near +0.20. The most predictive "
                 "single efficiency number and the biggest driver of the game win-prob model."},
        {"name": "EPA / Play (Def)", "key": "epaDef", "dec": 3, "dir": "low",
         "def": "Expected Points Added allowed per defensive play.",
         "read": "Negative is good — it means the defense is taking expected points away from "
                 "offenses. On the profile radar this axis is inverted so 'more is better'."},
        {"name": "Net EPA / Play", "key": "netEpa", "dec": 3, "dir": "high",
         "def": "Offensive EPA/play minus defensive EPA/play allowed — one efficiency number for "
                "the whole team.",
         "read": "The cleanest one-line efficiency summary; strongly tracks SP+."},
        {"name": "Success Rate % (Off)", "key": "srOff", "dec": 0, "dir": "high",
         "def": "Share of plays that are 'successful' — 50%+ of needed yards on 1st down, 70%+ on "
                "2nd, 100% on 3rd/4th.",
         "read": "Measures consistency (staying on schedule) rather than explosiveness. ~45%+ is "
                 "strong. A team can have high EPA from a few huge plays but a mediocre "
                 "Success Rate — that's a boom-or-bust profile."},
        {"name": "Success Rate % (Def)", "key": "srDef", "dec": 0, "dir": "low",
         "def": "Share of opponent plays that were successful.",
         "read": "Lower is better. Shown on the efficiency split as the rate the defense allows."},
        {"name": "Explosiveness", "key": None, "dir": "high",
         "def": "The rate of explosive plays — snaps gaining 15+ yards (garbage time excluded).",
         "read": "The big-play dimension of an offense. On the radar it's a 0–100 percentile "
                 "versus FBS. High Success Rate + high Explosiveness is the ideal offense."},
    ]),
    ("Schedule & Talent", [
        {"name": "Strength of Schedule", "key": None, "dir": "rank",
         "def": "Rank by the average SP+ rating of the opponents a team actually played "
                "(1 = toughest slate). Computed from opponents faced because SP+'s own SoS field "
                "was empty for 2025.",
         "read": "Read every counting stat through this lens — gaudy scoring against a #120 "
                 "schedule means less than solid numbers against a #10 one. Feeds the win-prob "
                 "models as sos_diff."},
        {"name": "Recruiting Rank", "key": "recruitRank", "dec": 0, "dir": "rank",
         "def": "The team's 247Sports recruiting-class rank (1 = best incoming talent).",
         "read": "A proxy for raw talent on the roster. The recruiting model shows it explains "
                 "~37% of the variance in team rating — real signal, far from the whole story."},
    ]),
    ("Projection", [
        {"name": "2026 Projected Wins", "key": "proj2026", "dec": 1, "dir": "high",
         "def": "Expected wins next season from the preseason priors model, which forecasts games "
                "before any 2026 form exists using prior-year strength, returning talent and "
                "recruiting.",
         "read": "A preseason expectation, not a guarantee — read it as 'about this many wins if "
                 "the season played out as expected.' The gauge on the dashboard visualizes it."},
    ]),
    ("Team Profile Radar (0–100 percentiles vs FBS)", [
        {"name": "OFF", "key": None, "dir": "high",
         "def": "Offensive EPA/play, ranked as a percentile across FBS.",
         "read": "100 = best offense in the country, 50 = median."},
        {"name": "DEF", "key": None, "dir": "high",
         "def": "Defensive EPA/play allowed, inverted so a higher percentile = a better defense.",
         "read": "100 = stingiest defense in FBS."},
        {"name": "ST", "key": None, "dir": "high",
         "def": "Special-teams rating percentile (from SP+'s special-teams component).",
         "read": "Kicking, returns and field position, relative to FBS."},
        {"name": "EXP", "key": None, "dir": "high",
         "def": "Explosive-play-rate percentile (15+ yard plays).",
         "read": "The big-play axis of the profile."},
        {"name": "EFF", "key": None, "dir": "high",
         "def": "Offensive Success Rate percentile.",
         "read": "The stay-on-schedule / consistency axis."},
        {"name": "TAL", "key": None, "dir": "high",
         "def": "Talent percentile from recruiting rank (better rank = higher percentile).",
         "read": "Roster-talent axis; the recruiting model links this to on-field results."},
    ]),
]


def build_glossary(teams: list[dict]) -> dict:
    groups = []
    for gname, stats in GLOSSARY_DEFS:
        out_stats = []
        for s in stats:
            entry = {"name": s["name"], "def": s["def"], "read": s["read"], "dir": s["dir"]}
            if s.get("key"):
                entry["dist"] = _dist(teams, s["key"], s["dec"])
                entry["dec"] = s["dec"]
            out_stats.append(entry)
        groups.append({"name": gname, "stats": out_stats})
    return {"season": SEASON, "nTeams": len(teams), "groups": groups}


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


if __name__ == "__main__":
    build()
