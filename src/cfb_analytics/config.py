"""Central config: paths and run parameters, sourced from env (.env) with safe defaults."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Repo root = two levels up from this file (src/cfb_analytics/config.py).
REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env")

DUCKDB_PATH = REPO_ROOT / os.getenv("CFB_DUCKDB_PATH", "data/cfb.duckdb")
TRANSFORM_DIR = REPO_ROOT / "transform"
ARTIFACTS_DIR = REPO_ROOT / "artifacts"


def seasons() -> list[int]:
    raw = os.getenv("CFB_SEASONS", "2023,2024")
    return [int(s) for s in raw.split(",") if s.strip()]


def has_api_key() -> bool:
    return bool(os.getenv("CFBD_API_KEY"))
