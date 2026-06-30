"""M1 (Eager & Erickson, Ch.2) — metric stability / reliability, Python parity of stability.R.

Same feed, thresholds, and statistics as the R implementation so the dashboard can show the two
languages agree. Reads data/gold/player_rushing.csv; writes data/results/metrics__stability__py.csv.
"""
from __future__ import annotations

import pandas as pd

from cfb_analytics.config import REPO_ROOT

GOLD = REPO_ROOT / "data" / "gold"
RESULTS = REPO_ROOT / "data" / "results"
MIN_SPLIT_ATTEMPTS = 40
MIN_YOY_ATTEMPTS = 50


def spearman_brown(r: float) -> float:
    return (2 * r) / (1 + r)


def main() -> None:
    pr = pd.read_csv(GOLD / "player_rushing.csv")
    rows = []

    # (a) split-half reliability per season
    for s in sorted(pr["season"].unique()):
        d = pr[(pr.season == s)
               & (pr.attempts_odd >= MIN_SPLIT_ATTEMPTS)
               & (pr.attempts_even >= MIN_SPLIT_ATTEMPTS)].dropna(
            subset=["ypc_odd_plays", "ypc_even_plays"])
        if len(d) >= 10:
            r = d["ypc_odd_plays"].corr(d["ypc_even_plays"])
            rows.append(dict(model="stability", metric="split_half_r_ypc",
                             basis=str(s), n=len(d), value=r))
            rows.append(dict(model="stability", metric="split_half_reliability_ypc",
                             basis=str(s), n=len(d), value=spearman_brown(r)))

    # (b) year-over-year stability
    wide = (pr[pr.rush_attempts >= MIN_YOY_ATTEMPTS]
            .pivot_table(index="rusher_player_name", columns="season",
                         values="yards_per_carry"))
    if {2023, 2024}.issubset(wide.columns):
        d = wide.dropna(subset=[2023, 2024])
        if len(d) >= 10:
            r = d[2023].corr(d[2024])
            rows.append(dict(model="stability", metric="year_over_year_r_ypc",
                             basis="2023-2024", n=len(d), value=r))

    out = pd.DataFrame(rows)
    out["language"] = "py"
    RESULTS.mkdir(parents=True, exist_ok=True)
    out.to_csv(RESULTS / "metrics__stability__py.csv", index=False)
    print(f"[stability/py] wrote {len(out)} reliability metrics")
    print(out.to_string(index=False))


if __name__ == "__main__":
    main()
