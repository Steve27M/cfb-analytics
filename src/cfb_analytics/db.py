"""Read-only DuckDB access for Python (parity models + dashboard). Least privilege:
exploration and reads never open the warehouse read/write."""
from __future__ import annotations

import duckdb
import pandas as pd

from .config import DUCKDB_PATH


def read_only_conn() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(DUCKDB_PATH), read_only=True)


def query(sql: str) -> pd.DataFrame:
    con = read_only_conn()
    try:
        return con.execute(sql).fetch_df()
    finally:
        con.close()
