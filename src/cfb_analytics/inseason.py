"""Apply the in-season update model to the live season.

Two halves, deliberately split by what they need:

  freeze_model(season, label)   LOCAL, needs the warehouse. Seals the fitted model into
                                predictions/<season>/<label>/: coefficients (from the parity-gated
                                R fit), every team's preseason strength, and a manifest. Done once
                                per model version; the directory is immutable after commit.

  snapshot(season, label)       ANYWHERE (CI). Needs only the sealed model directory, the frozen
                                schedule (the original preseason version's game list) and the
                                season's settled scores (one CFBD /games call). Re-rates every team
                                from the results so far and writes an immutable, timestamped
                                snapshot under <label>/snapshots/ — but only when new results have
                                settled since the previous snapshot, so quiet days add nothing.

The scoreboard (dashboard/build_forecast.py) scores every snapshot forward-only from its own
generated_at, and composes the "live" series: for each game, the latest snapshot that predates
its kickoff. That is exactly what a reader following the season would have seen.

Results never reach the model raw: cfb_analytics.results reconciles CFBD's live listing against
the frozen schedule (orientation by team, live kickoff, re-keyed ids) and validates it; a hard
failure quarantines the results and snapshot() refuses to seal. The sealed snapshot is checked
again before it is written (records add up, projections bounded by the record, ratings finite).

    uv run python -m cfb_analytics.inseason freeze 2026 v2-inseason
    uv run python -m cfb_analytics.inseason snapshot 2026
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from . import registry
from .config import REPO_ROOT
from .results import fetch_games, reconcile, validate

GOLD_DIR = REPO_ROOT / "data" / "gold"
RESULTS_DIR = REPO_ROOT / "data" / "results"
PREDICTIONS_DIR = registry.PREDICTIONS_DIR
MODEL = "inseason_winprob"
DEFAULT_LABEL = "v2-inseason"
SCHEDULE_VERSION = registry.SCHEDULE_VERSION
PRIOR_TERMS = {"prior_sp_diff": "prior_sp", "prior_net_epa_diff": "prior_net_epa",
               "prior_win_pct_diff": "prior_win_pct"}


# --------------------------------------------------------------------------- shared math
def preseason_strength(tp: pd.DataFrame, priors_coef: pd.DataFrame) -> pd.DataFrame:
    """Per-team preseason strength: the priors model's linear predictor (logit scale), centered
    within season. tp = team_priors feed rows; priors_coef = priors_winprob coefficients."""
    b = dict(zip(priors_coef.term, priors_coef.estimate, strict=True))
    out = tp.copy()
    out["strength"] = sum(b[t] * out[c] for t, c in PRIOR_TERMS.items())
    out["strength"] -= out.groupby("season").strength.transform("mean")
    return out[["season", "team", "strength"]]


def ridge_ratings(played: pd.DataFrame, strength: pd.Series, k: float, gamma: float,
                  home_adv: float) -> pd.Series:
    """Posterior team ratings (points) given the games played so far.

    Solves min sum_g (margin_g - home_adv*home_ind_g - (r_h - r_a))^2 + k*sum_T (r_T - gamma*s_T)^2
    in closed form. strength: Series of preseason strength indexed by team; played needs
    home_team, away_team, home_margin, home_ind (+1 home team hosts, -1 away team hosts, 0
    neutral). With no games the ratings ARE the prior."""
    teams = strength.index.to_list()
    idx = {t: i for i, t in enumerate(teams)}
    prior = gamma * strength.to_numpy(float)
    if len(played) == 0:
        return pd.Series(prior, index=teams)
    n, T = len(played), len(teams)
    X = np.zeros((n, T))
    hi = played.home_team.map(idx).to_numpy()
    ai = played.away_team.map(idx).to_numpy()
    X[np.arange(n), hi] = 1.0
    X[np.arange(n), ai] = -1.0
    y = (played.home_margin.to_numpy(float) - home_adv * played.home_ind.to_numpy(float)
         - (prior[hi] - prior[ai]))
    delta = np.linalg.solve(X.T @ X + k * np.eye(T), X.T @ y)
    return pd.Series(prior + delta, index=teams)


# --------------------------------------------------------------------------- CFBD results
def settled_games(season: int) -> pd.DataFrame:
    """CFBD's current listing for the season (see results.fetch_games)."""
    return fetch_games(season)


def align_results(sched: pd.DataFrame, results: pd.DataFrame) -> pd.DataFrame:
    """Results in the frozen schedule's orientation (results.reconcile without the drift report)."""
    return reconcile(sched, results)[0]


# --------------------------------------------------------------------------- helpers
def _sha256(path: Path) -> str:
    return registry.sha256_text(path)


def _write_json(path: Path, obj: dict) -> None:
    path.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8", newline="\n")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _git_sha() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True,
                              text=True, check=True).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def _rel(p: Path) -> str:
    try:
        return str(p.relative_to(REPO_ROOT))
    except ValueError:            # a registry outside the repo (tests)
        return str(p)


def _model_dir(season: int, label: str) -> Path:
    return PREDICTIONS_DIR / str(season) / label


def load_model(season: int, label: str = DEFAULT_LABEL) -> dict:
    d = _model_dir(season, label)
    manifest = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    coef = pd.read_csv(d / "coef__inseason__r.csv")
    b = dict(zip(coef.term, coef.estimate, strict=True))
    strength = pd.read_csv(d / "team_prior_strength.csv").set_index("team").strength
    return {"dir": d, "manifest": manifest, "coef": b, "strength": strength}


def load_schedule(season: int) -> pd.DataFrame:
    """The frozen game list every snapshot predicts: the original preseason version's games."""
    return registry.load_schedule(season)


def results_hash(settled: pd.DataFrame) -> str:
    rows = sorted(f"{int(r.game_id)}:{int(r.home_points)}:{int(r.away_points)}"
                  for r in settled.itertuples())
    return hashlib.sha256("\n".join(rows).encode()).hexdigest()


# --------------------------------------------------------------------------- freeze
def freeze_model(season: int, label: str = DEFAULT_LABEL) -> Path:
    """Seal the fitted in-season model for <season> into the registry (immutable)."""
    dst = _model_dir(season, label)
    if dst.exists():
        raise SystemExit(f"refusing to overwrite existing registry version: {dst}\n"
                         "Registry versions are immutable — pick a new label.")
    coef_src = RESULTS_DIR / "coef__inseason__r.csv"
    metrics_src = RESULTS_DIR / "metrics__inseason__r.csv"
    priors_src = RESULTS_DIR / "coef__priors__r.csv"
    tp_src = GOLD_DIR / "team_priors.csv"
    for p in (coef_src, metrics_src, priors_src, tp_src):
        if not p.exists():
            raise SystemExit(f"missing {p} — run the export, R models and parity steps first")
    schedule = load_schedule(season)

    tp = pd.read_csv(tp_src)
    tp = tp[tp.season == season]
    strength = preseason_strength(tp, pd.read_csv(priors_src)).set_index("team").strength
    missing = sorted((set(schedule.home_team) | set(schedule.away_team)) - set(strength.index))
    if missing:
        raise SystemExit(f"schedule teams without priors: {missing}")
    coef = pd.read_csv(coef_src)
    b = dict(zip(coef.term, coef.estimate, strict=True))
    metrics = pd.read_csv(metrics_src)
    m = dict(zip(metrics.metric, metrics.value, strict=True))

    dst.mkdir(parents=True)
    coef.to_csv(dst / "coef__inseason__r.csv", index=False, lineterminator="\n")
    ts = (strength.rename("strength").reset_index()
          .assign(prior_rating=lambda d: b["gamma"] * d.strength)
          .sort_values("prior_rating", ascending=False))
    ts["prior_rank"] = range(1, len(ts) + 1)
    ts.to_csv(dst / "team_prior_strength.csv", index=False, lineterminator="\n")

    files = {
        "coef__inseason__r.csv": {
            "sha256": _sha256(dst / "coef__inseason__r.csv"), "rows": len(coef),
            "grain": "fitted terms: (Intercept), pred_margin, ridge_k, gamma, home_adv"},
        "team_prior_strength.csv": {
            "sha256": _sha256(dst / "team_prior_strength.csv"), "rows": len(ts),
            "grain": "one row per team: preseason strength (logit, centered), "
                     "prior_rating (points = gamma x strength), prior_rank"},
    }
    manifest = {
        "version": label,
        "label": "In-season updated forecast",
        "kind": "series",
        "season": season,
        "season_type": "regular",
        "model": MODEL,
        "model_language": "r (python parity-gated, rtol 1e-4)",
        "generated_at": _now(),
        "frozen_at": datetime.now(UTC).date().isoformat(),
        "source_commit": _git_sha(),
        "method": ("Bayesian ridge on scoring margins: every team starts at its preseason strength "
                   "(the priors model's linear predictor, converted to points by gamma) and moves "
                   "toward its season-to-date opponent-adjusted margins; ridge_k is how many games "
                   "of evidence the preseason prior is worth. Win probability = "
                   "logistic(intercept + slope x predicted margin)."),
        "train_seasons": [season - 2],
        "holdout_season": season - 1,
        "holdout_metrics": {k: round(float(m[k]), 4) for k in
                            ("brier", "brier_priors", "brier_naive", "accuracy", "accuracy_priors",
                             "auc", "log_loss", "brier_from_game4", "brier_priors_from_game4",
                             "n_test") if k in m},
        "hyperparameters": {k: float(b[k]) for k in ("ridge_k", "gamma", "home_adv")},
        "coefficients": {"(Intercept)": float(b["(Intercept)"]),
                         "pred_margin": float(b["pred_margin"])},
        "priors_season": season - 1,
        "schedule_from": SCHEDULE_VERSION,
        "scope": ("the frozen preseason game list (FBS-vs-FBS regular season); only games between "
                  "two rated teams count as evidence, so FCS results never move a rating"),
        "snapshot_policy": ("snapshots/<UTC timestamp>/ is written by the scoreboard refresh only "
                            "when new results have settled since the previous snapshot; each "
                            "snapshot is immutable and is scored forward-only from its own "
                            "generated_at. The live series takes, for every game, the latest "
                            "snapshot that predates its kickoff."),
        "immutable": True,
        "hash_rule": registry.HASH_RULE,
        "files": files,
    }
    _write_json(dst / "manifest.json", manifest)
    print(f"  frozen model -> {_rel(dst)} (k={b['ridge_k']:g}, gamma="
          f"{b['gamma']:.2f}, home_adv={b['home_adv']:.2f}; holdout Brier {m['brier']:.4f} vs "
          f"priors-only {m['brier_priors']:.4f})")
    return dst


# --------------------------------------------------------------------------- snapshot guard
def check_snapshot(sched: pd.DataFrame, teams: pd.DataFrame, played: pd.DataFrame) -> None:
    """Invariants a snapshot must satisfy before it is sealed; raises SystemExit otherwise.
    These catch a wrong model input or a code regression, not a modelling choice."""
    problems: list[str] = []
    if not np.isfinite(teams.rating.to_numpy(float)).all():
        problems.append("non-finite rating")
    if not np.isfinite(sched.home_win_prob.to_numpy(float)).all() or not (
            (sched.home_win_prob > 0) & (sched.home_win_prob < 1)).all():
        problems.append("home_win_prob outside (0, 1)")
    if (teams.wins + teams.losses + teams.remaining != teams.games).any():
        problems.append("wins + losses + remaining != games")
    lo = teams.projected_wins < teams.wins - 1e-9
    hi = teams.projected_wins > teams.wins + teams.remaining + 1e-9
    if (lo | hi).any():
        problems.append("projected_wins outside [wins, wins + remaining] for "
                        + ", ".join(teams.team[lo | hi]))
    # the record the table shows must be the record the evidence implies
    w_from_games = pd.concat([played.home_team[played.home_margin > 0],
                              played.away_team[played.home_margin < 0]]).value_counts()
    l_from_games = pd.concat([played.away_team[played.home_margin > 0],
                              played.home_team[played.home_margin < 0]]).value_counts()
    t = teams.set_index("team")
    if not (t.wins.eq(w_from_games.reindex(t.index).fillna(0).astype(int)).all()
            and t.losses.eq(l_from_games.reindex(t.index).fillna(0).astype(int)).all()):
        problems.append("team wins/losses disagree with the settled games")
    if (played.home_margin == 0).any():
        problems.append("a settled game with a zero margin reached the model")
    if problems:
        raise SystemExit("snapshot failed its own checks — nothing sealed: " + "; ".join(problems))


# --------------------------------------------------------------------------- snapshot
def snapshot(season: int, label: str = DEFAULT_LABEL, results: pd.DataFrame | None = None,
             force: bool = False) -> Path | None:
    """Re-rate every team from the results so far and seal a timestamped snapshot.
    Returns the new snapshot dir, or None when nothing new has settled (no write)."""
    model = load_model(season, label)
    b, strength = model["coef"], model["strength"]
    raw = fetch_games(season) if results is None else results
    # frozen orientation, results aligned by team; home_ind is -1 where CFBD flipped the host
    sched, drift = reconcile(load_schedule(season), raw)
    report = validate(sched, raw)
    if not report["ok"]:
        print("  snapshot: results quarantined — refusing to seal a snapshot on them")
        return None
    played = sched[sched.settled].copy()
    played["home_margin"] = played.home_points - played.away_points

    snap_root = model["dir"] / "snapshots"
    rhash = results_hash(played)
    previous = sorted(p for p in snap_root.iterdir() if p.is_dir()) if snap_root.exists() else []
    if previous and not force:
        last = json.loads((previous[-1] / "manifest.json").read_text(encoding="utf-8"))
        if last.get("results_hash") == rhash:
            print(f"  snapshot: no new results since {previous[-1].name} — nothing to seal")
            return None

    ratings = ridge_ratings(played, strength, b["ridge_k"], b["gamma"], b["home_adv"])
    pm = (sched.home_team.map(ratings) - sched.away_team.map(ratings)
          + b["home_adv"] * sched.home_ind)
    sched["pred_margin"] = pm.round(2)
    sched["home_win_prob"] = 1.0 / (1.0 + np.exp(-(b["(Intercept)"] + b["pred_margin"] * pm)))
    sched["favored_team"] = np.where(sched.home_win_prob >= 0.5, sched.home_team, sched.away_team)
    sched["favored_win_prob"] = np.where(sched.home_win_prob >= 0.5, sched.home_win_prob,
                                         1 - sched.home_win_prob)
    sched["forecast_season"] = season

    # team projection: actual record so far + expected wins over the remaining schedule
    home_won = sched.home_points > sched.away_points
    rows = []
    for team in strength.index:
        is_home, is_away = sched.home_team == team, sched.away_team == team
        mine = sched[is_home | is_away]
        done = mine[mine.settled]
        wins = int(((done.home_team == team) & home_won[done.index]).sum()
                   + ((done.away_team == team) & ~home_won[done.index]).sum())
        losses = len(done) - wins
        left = mine[~mine.settled]
        exp_left = float(np.where(left.home_team == team, left.home_win_prob,
                                  1 - left.home_win_prob).sum())
        rows.append({"team": team, "games": len(mine), "wins": wins, "losses": losses,
                     "remaining": len(left), "projected_wins": round(wins + exp_left, 3),
                     "projected_losses": round(losses + len(left) - exp_left, 3),
                     "rating": round(float(ratings[team]), 2),
                     "prior_rating": round(float(b["gamma"] * strength[team]), 2)})
    teams = pd.DataFrame(rows).sort_values("projected_wins", ascending=False).reset_index(drop=True)
    teams["projected_rank"] = teams.index + 1
    teams["rating_rank"] = teams.rating.rank(ascending=False, method="min").astype(int)

    check_snapshot(sched, teams, played)   # raises before anything is written

    now = datetime.now(UTC)
    dst = snap_root / now.strftime("%Y-%m-%dT%H-%MZ")
    if dst.exists():
        raise SystemExit(f"snapshot already exists for this minute: {dst}")
    dst.mkdir(parents=True)
    games_out = sched[["game_id", "week", "start_date", "neutral_site", "home_team", "away_team",
                       "pred_margin", "home_win_prob", "favored_team", "favored_win_prob",
                       "forecast_season"]]
    games_out.to_csv(dst / f"forecast_{season}.csv", index=False, lineterminator="\n")
    teams.to_csv(dst / f"forecast_{season}_teams.csv", index=False, lineterminator="\n")
    files = {f.name: {"sha256": _sha256(f), "rows": sum(1 for _ in open(f, encoding="utf-8")) - 1}
             for f in (dst / f"forecast_{season}.csv", dst / f"forecast_{season}_teams.csv")}
    manifest = {
        "version": label, "snapshot": dst.name, "season": season, "model": MODEL,
        "generated_at": now.isoformat(timespec="seconds"),
        "source_commit": _git_sha(),
        "results_hash": rhash,
        "n_settled": int(len(played)), "n_games": int(len(sched)),
        "through_week": int(played.week.max()) if len(played) else 0,
        "immutable": True,
        "scoring_rule": ("a game counts toward this snapshot's accuracy only if generated_at "
                         "precedes kickoff"),
        "results_validation": {"ok": True, "checked_at": report["checked_at"],
                               "hard_checks": [c["id"] for c in report["checks"]
                                               if c["severity"] == "hard"]},
        "schedule_drift": {k: len(v) for k, v in drift.items() if isinstance(v, list)},
        "hash_rule": registry.HASH_RULE,
        "files": files,
    }
    _write_json(dst / "manifest.json", manifest)
    top = teams.sort_values("rating", ascending=False).iloc[0]
    print(f"  snapshot -> {_rel(dst)}: {len(played)}/{len(sched)} results in; "
          f"top rating {top.team} ({top.rating:+.1f})")
    return dst


if __name__ == "__main__":
    argv = sys.argv[1:]
    if not argv or argv[0] not in {"freeze", "snapshot"}:
        raise SystemExit(__doc__)
    yr = int(argv[1]) if len(argv) > 1 else 2026
    if argv[0] == "freeze":
        freeze_model(yr, argv[2] if len(argv) > 2 else DEFAULT_LABEL)
    else:
        snapshot(yr, argv[2] if len(argv) > 2 else DEFAULT_LABEL, force="--force" in argv)
