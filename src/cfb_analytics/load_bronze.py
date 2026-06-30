"""Load the R-written bronze CSVs (data/bronze/*.csv[.gz]) into DuckDB bronze.* tables.

This is the Python side of the polyglot contract: R writes flat files, Python lands them in the
warehouse (and re-encodes to DuckDB's columnar format). Bronze stays effectively immutable — it
is rebuilt deterministically from the season-partitioned CSV files, which are themselves
append-only. Season files are unioned by name into one table per source.
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

import duckdb

from .config import DUCKDB_PATH, REPO_ROOT

BRONZE_DIR = REPO_ROOT / "data" / "bronze"
_SEASON_RE = re.compile(r"^(?P<name>.+?)__\d{4}\.csv(?:\.gz)?$")

# Per-table column-type overrides: read_csv_auto infers `id_play` (an 18-digit play id)
# as DOUBLE, whose 53-bit mantissa can't hold the value exactly — distinct plays collapse
# onto the same float (e.g. 254k 2023 plays -> only 102k distinct doubles), destroying the
# natural play key. Force BIGINT so the key survives. Keep this list minimal/explicit.
_TYPE_OVERRIDES: dict[str, dict[str, str]] = {
    "plays": {"id_play": "BIGINT"},
}


def _group_files() -> dict[str, list[Path]]:
    """Map base table name -> list of season files (e.g. 'plays' -> [plays__2023.csv.gz, ...])."""
    groups: dict[str, list[Path]] = defaultdict(list)
    for f in sorted(BRONZE_DIR.glob("*.csv*")):
        m = _SEASON_RE.match(f.name)
        if m:
            groups[m.group("name")].append(f)
        elif f.name == "_ingest_log.csv":
            groups["ingest_log"].append(f)
    return groups


def load() -> None:
    if not BRONZE_DIR.exists():
        raise SystemExit(f"no bronze dir: {BRONZE_DIR} (run ingestion first)")
    groups = _group_files()
    if not groups:
        raise SystemExit(f"no bronze CSVs found in {BRONZE_DIR}")

    DUCKDB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DUCKDB_PATH))
    try:
        con.execute("CREATE SCHEMA IF NOT EXISTS bronze")
        for name, files in groups.items():
            paths = [str(p).replace("\\", "/") for p in files]
            file_list = "[" + ", ".join(f"'{p}'" for p in paths) + "]"
            # sample_size=-1: scan all rows so wide/ sparse columns (mostly-NULL player names)
            # are typed correctly. union_by_name: tolerate column drift across seasons.
            override = _TYPE_OVERRIDES.get(name)
            types_clause = ""
            if override:
                cols = ", ".join(f"'{c}': '{t}'" for c, t in override.items())
                types_clause = f", types={{{cols}}}"
            con.execute(
                f"CREATE OR REPLACE TABLE bronze.{name} AS "
                f"SELECT * FROM read_csv_auto({file_list}, union_by_name=true, "
                f"sample_size=-1{types_clause})"
            )
            row = con.execute(f"SELECT count(*) FROM bronze.{name}").fetchone()
            n = row[0] if row else 0
            print(f"  bronze.{name:12s} <- {len(files)} file(s)  {n:,} rows")
    finally:
        con.close()


if __name__ == "__main__":
    load()
