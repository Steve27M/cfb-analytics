#!/usr/bin/env python3
"""MCP server exposing safe, deterministic analytics-engineering operations.

The agent decides WHEN to call; these functions decide HOW it executes, with
guardrails baked in (read-only SQL only, coverage/grain checks, lint, test runs).
Run as an MCP server; register in .claude/settings.json mcpServers.

Wire the warehouse calls (DuckDB / Snowflake / BigQuery) to a READ-ONLY connection.
The dbt-invoking tools shell out to the dbt CLI -- they never write to prod.
"""
import json
import logging
import re
import subprocess
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("dbt-tools")

mcp = FastMCP("dbt-tools")

MODELS_DIR = Path("models")
MUTATING = ("insert", "update", "delete", "drop", "merge", "truncate",
            "alter", "create", "grant", "revoke")
# Schemas a read tool must never touch even via SELECT side effects.
RAW_SCHEMAS = re.compile(r"\b(raw|landing|source|sources|bronze)\b", re.IGNORECASE)


@mcp.tool()
def query_readonly(sql: str, row_limit: int = 1000) -> dict[str, Any]:
    """Run a SELECT against the warehouse read replica. Rejects any non-SELECT.

    Caps rows to protect against accidental full-table pulls. Use for exploration;
    NOT for building models -- models go through dbt.
    """
    stripped = sql.strip().rstrip(";")
    if not stripped.lower().startswith(("select", "with")):
        return {"error": "Only SELECT/WITH queries are permitted via this tool."}
    if any(kw in stripped.lower() for kw in MUTATING):
        return {"error": "Mutating keyword detected; rejected."}

    safe_sql = f"SELECT * FROM ({stripped}) _q LIMIT {min(row_limit, 10_000)}"
    log.info("query_readonly rows<=%d", row_limit)
    try:
        # rows = duckdb_ro.execute(safe_sql).fetchall()  # wire to your RO conn
        rows: list[dict] = []  # placeholder
        return {"rows": rows, "row_count": len(rows), "truncated": len(rows) >= row_limit}
    except Exception as e:  # surface, don't crash the agent loop
        log.exception("query failed")
        return {"error": f"Query failed: {e}"}


@mcp.tool()
def run_dbt_tests(select: str = "state:modified+") -> dict[str, Any]:
    """Run `dbt test` for a selection. Never full-refreshes; never targets prod here.

    Returns pass/fail counts and failing test names.
    """
    cmd = ["dbt", "test", "--select", select, "--target", "dev"]
    log.info("run_dbt_tests %s", " ".join(cmd))
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
        return {
            "returncode": proc.returncode,
            "passed": proc.returncode == 0,
            "stdout_tail": proc.stdout[-4000:],
            "stderr_tail": proc.stderr[-2000:],
        }
    except subprocess.TimeoutExpired:
        return {"error": "dbt test timed out (900s)."}
    except FileNotFoundError:
        return {"error": "dbt CLI not found on PATH."}


@mcp.tool()
def check_model_has_tests_and_docs(model_name: str) -> dict[str, Any]:
    """Verify a model has a YAML description AND at least one key test.

    Parses the layer YAML next to the model. A model with no description or no
    not_null/unique/relationships test on a column fails (AE with SQL and dbt, ch.4).
    """
    found = list(MODELS_DIR.rglob(f"{model_name}.sql"))
    if not found:
        return {"model": model_name, "ok": False, "reason": "Model .sql not found."}
    yml_text = "".join(p.read_text(encoding="utf-8", errors="ignore")
                       for p in found[0].parent.glob("*.yml"))
    has_block = re.search(rf"name:\s*{re.escape(model_name)}\b", yml_text) is not None
    has_desc = has_block and "description:" in yml_text
    has_test = bool(re.search(r"\b(not_null|unique|relationships|accepted_values)\b", yml_text))
    ok = has_block and has_desc and has_test
    return {
        "model": model_name, "ok": ok,
        "has_yaml_entry": has_block, "has_description": has_desc, "has_key_test": has_test,
        "message": "Documented + tested." if ok
        else "Add a description and a not_null/unique/relationships test on the key.",
    }


@mcp.tool()
def check_grain_declared(model_name: str) -> dict[str, Any]:
    """Confirm the model declares its grain (header comment or YAML description).

    A fact/dim with no declared grain is a defect (FDE ch.8; MED ch.3). Looks for a
    line mentioning grain / 'one row per' in the .sql header or the YAML description.
    """
    found = list(MODELS_DIR.rglob(f"{model_name}.sql"))
    if not found:
        return {"model": model_name, "ok": False, "reason": "Model .sql not found."}
    sql = found[0].read_text(encoding="utf-8", errors="ignore")
    yml = "".join(p.read_text(encoding="utf-8", errors="ignore")
                  for p in found[0].parent.glob("*.yml"))
    pat = re.compile(r"grain|one row per|granularity", re.IGNORECASE)
    in_sql = bool(pat.search(sql[:600]))   # header region
    in_yml = bool(pat.search(yml))
    ok = in_sql or in_yml
    return {"model": model_name, "ok": ok, "declared_in_sql_header": in_sql,
            "declared_in_yaml": in_yml,
            "message": "Grain declared." if ok
            else "Declare the grain in a header comment and the YAML description."}


@mcp.tool()
def lint_sql(path: str = "models/") -> dict[str, Any]:
    """Run SQLFluff lint on a path. Returns violation count and a sample."""
    cmd = ["sqlfluff", "lint", path, "--format", "json"]
    log.info("lint_sql %s", path)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        try:
            results = json.loads(proc.stdout or "[]")
            violations = sum(len(f.get("violations", [])) for f in results)
        except json.JSONDecodeError:
            violations, results = -1, []
        return {"clean": violations == 0, "violation_count": violations,
                "sample": results[:5]}
    except FileNotFoundError:
        return {"error": "sqlfluff not found on PATH."}
    except subprocess.TimeoutExpired:
        return {"error": "sqlfluff timed out."}


@mcp.tool()
def list_uncovered_models() -> dict[str, Any]:
    """List models missing docs or a key test. Use as a merge gate.

    Walks every models/**/*.sql and runs the docs+tests check (AE ch.4).
    """
    uncovered = []
    for sql in MODELS_DIR.rglob("*.sql"):
        name = sql.stem
        res = check_model_has_tests_and_docs(name)
        if not res.get("ok"):
            uncovered.append({"model": name, "reason": res.get("message")})
    return {"uncovered_count": len(uncovered), "uncovered": uncovered,
            "ok": not uncovered}


if __name__ == "__main__":
    mcp.run()
