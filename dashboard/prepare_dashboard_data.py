"""Pre-render step (Python): read the DuckDB warehouse and write the dashboard's data CSVs.

The dashboard is rendered by R/knitr; R has no DuckDB binary on this R build, so — exactly as the
polyglot contract dictates — Python owns warehouse access and hands R flat files. This script is
wired as the Quarto `pre-render` hook AND is runnable standalone. Writes to data/dashboard/.

Outputs:
  dq_layer_counts.csv  row counts per modelled table, by medallion layer
  dq_freshness.csv     latest bronze load timestamp + row count per source
  dq_tests.csv         dbt test pass/fail/warn tally (parsed from target/run_results.json)
  team_efficiency.csv  per-team-season offensive/defensive/net EPA + win rate leaderboard
"""
from __future__ import annotations

import json

from cfb_analytics.config import REPO_ROOT
from cfb_analytics.db import read_only_conn

OUT_DIR = REPO_ROOT / "data" / "dashboard"
RUN_RESULTS = REPO_ROOT / "transform" / "target" / "run_results.json"


def _dq_layer_counts(con) -> None:
    rows = con.execute("""
        select table_schema as layer, table_name,
               case table_schema when 'staging' then 1 when 'silver' then 2
                                 when 'gold' then 3 when 'snapshots' then 4 else 5 end as ord
        from information_schema.tables
        where table_schema in ('staging', 'silver', 'gold', 'snapshots')
        order by ord, table_name
    """).fetchall()
    out = []
    for layer, table, ord_ in rows:
        n = con.execute(f'select count(*) from "{layer}"."{table}"').fetchone()[0]
        out.append((layer, table, n, ord_))
    import pandas as pd
    pd.DataFrame(out, columns=["layer", "table_name", "row_count", "ord"]).to_csv(
        OUT_DIR / "dq_layer_counts.csv", index=False)


def _dq_freshness(con) -> None:
    df = con.execute("""
        select table_name as source, max(fetched_at) as last_loaded, sum(rows) as rows
        from bronze.ingest_log group by table_name order by table_name
    """).fetch_df()
    df.to_csv(OUT_DIR / "dq_freshness.csv", index=False)


def _dq_tests() -> None:
    import pandas as pd
    if not RUN_RESULTS.exists():
        pd.DataFrame([{"status": "unknown", "n": 0}]).to_csv(OUT_DIR / "dq_tests.csv", index=False)
        return
    data = json.loads(RUN_RESULTS.read_text())
    tally: dict[str, int] = {}
    for r in data.get("results", []):
        # only count data tests, not model builds
        if r.get("unique_id", "").startswith("test."):
            tally[r["status"]] = tally.get(r["status"], 0) + 1
    rows = [{"status": k, "n": v} for k, v in sorted(tally.items())] or [{"status": "none", "n": 0}]
    pd.DataFrame(rows).to_csv(OUT_DIR / "dq_tests.csv", index=False)


def _team_efficiency(con) -> None:
    df = con.execute("""
        select
            season,
            team,
            count(*)                            as games,
            avg(case when won then 1.0 else 0.0 end) as win_pct,
            avg(net_epa_per_play)               as net_epa,
            avg(offensive_epa_per_play)         as off_epa,
            avg(defensive_epa_per_play)         as def_epa
        from gold.mart_team_efficiency
        group by season, team
        having count(*) >= 8
        order by season desc, net_epa desc
    """).fetch_df()
    df.to_csv(OUT_DIR / "team_efficiency.csv", index=False)


def prepare() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    con = read_only_conn()
    try:
        _dq_layer_counts(con)
        _dq_freshness(con)
        _team_efficiency(con)
    finally:
        con.close()
    _dq_tests()
    print(f"  dashboard data -> {OUT_DIR}")


if __name__ == "__main__":
    prepare()
