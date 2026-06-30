#!/usr/bin/env bash
# Full local check: lint/type (Python), dbt build + source freshness.
# Run from repo root:  ./scripts/check.sh
set -euo pipefail

echo "== ruff =="
uv run ruff check .
echo "== mypy =="
uv run mypy src
echo "== dbt build =="
uv run dbt build --project-dir transform --profiles-dir transform
echo "== dbt source freshness =="
uv run dbt source freshness --project-dir transform --profiles-dir transform
echo "All checks passed."
