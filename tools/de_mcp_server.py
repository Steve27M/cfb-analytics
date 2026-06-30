#!/usr/bin/env python3
"""MCP server exposing safe, deterministic data-engineering operations.

The agent decides WHEN to call; these functions decide HOW it executes, with
guardrails baked in: read-only queries, row caps, no writes to source/prod,
PII redaction in profiles. Run as an MCP server; register in
.claude/settings.json mcpServers.

Wire the placeholder engine calls to your real READ-ONLY DuckDB/Snowflake
connection. Nothing here may ever open a writable connection.
"""
import logging
import re
from typing import Any

from mcp.server.fastmcp import FastMCP

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("de-tools")

mcp = FastMCP("de-tools")

ROW_CAP = 10_000
MUTATING = ("insert", "update", "delete", "drop", "merge", "truncate",
            "alter", "create", "grant", "revoke")

# Schemas this server refuses to read from a writable angle / refuses to target.
PROTECTED_SCHEMAS = re.compile(r"\b(\w+_prod|\w+_raw|production|source)\b", re.IGNORECASE)

# Column-name patterns treated as PII; values are redacted in any profile/sample.
PII_COLUMNS = re.compile(
    r"(?i)\b(email|ssn|social_security|phone|first_name|last_name|full_name|"
    r"address|dob|date_of_birth|card_number|account_number|ip_address)\b"
)


def _redact(col: str, value: Any) -> Any:
    """Never surface raw PII values; return a masked marker instead. (FDE ch. 10)"""
    return "<redacted-pii>" if PII_COLUMNS.search(col) else value


@mcp.tool()
def query_readonly(sql: str, row_limit: int = 1000) -> dict[str, Any]:
    """Run a SELECT against the read-only connection. Rejects any non-SELECT.

    Caps rows to guard against accidental full-table pulls. PII columns in the
    result are redacted.
    """
    stripped = sql.strip().rstrip(";")
    low = stripped.lower()
    if not low.startswith(("select", "with")):
        return {"error": "Only SELECT/WITH queries are permitted via this tool."}
    if any(re.search(rf"\b{kw}\b", low) for kw in MUTATING):
        return {"error": "Mutating keyword detected; rejected (read-only tool)."}

    capped = min(row_limit, ROW_CAP)
    safe_sql = f"SELECT * FROM ({stripped}) _q LIMIT {capped}"
    log.info("query_readonly rows<=%d", capped)
    try:
        # rows = ro_conn.execute(safe_sql).fetch_arrow_table().to_pylist()  # wire up
        rows: list[dict] = []  # placeholder
        rows = [{k: _redact(k, v) for k, v in r.items()} for r in rows]
        return {"rows": rows, "row_count": len(rows), "truncated": len(rows) >= capped}
    except Exception as e:  # surface, don't crash the agent loop
        log.exception("query failed")
        return {"error": f"Query failed: {e}"}


@mcp.tool()
def run_dq_checks(model: str) -> dict[str, Any]:
    """Run the model's data-quality tests (not_null/unique/accepted_values/...).

    Returns a per-test pass/fail summary. A model with no tests is itself a
    failure -- you can't trust an untested model. (DQF ch. 3)
    """
    log.info("run_dq_checks model=%s", model)
    # subprocess: `dbt test --select <model> --target dev --store-failures`
    # parse run_results.json; return structured results.
    results: list[dict] = []  # placeholder: [{"test": "...", "status": "pass|fail", "failures": 0}]
    has_grain_test = any(t["test"].startswith(("unique_", "not_null_")) for t in results)
    failed = [t for t in results if t.get("status") == "fail"]
    return {
        "model": model,
        "tests_run": len(results),
        "has_grain_key_tests": has_grain_test,
        "failed": failed,
        "ok": bool(results) and not failed and has_grain_test,
        "message": ("Clean." if (results and not failed and has_grain_test)
                    else "Missing grain-key tests or failing checks -- NO-GO."),
    }


@mcp.tool()
def check_freshness(source_or_model: str, max_lag_minutes: int = 60) -> dict[str, Any]:
    """Check whether a source/served table is fresh within its SLA. (DQF ch. 4/5)

    Returns the observed lag and whether it breaches max_lag_minutes (the SLO).
    """
    log.info("check_freshness target=%s max_lag=%dm", source_or_model, max_lag_minutes)
    # `dbt source freshness` or MAX(loaded_at) vs now() on the read-only conn.
    observed_lag_minutes = None  # placeholder
    if observed_lag_minutes is None:
        return {"target": source_or_model, "ok": None,
                "message": "Wire up loaded_at/source freshness query."}
    ok = observed_lag_minutes <= max_lag_minutes
    return {"target": source_or_model, "lag_minutes": observed_lag_minutes,
            "sla_minutes": max_lag_minutes, "ok": ok,
            "message": "Fresh." if ok else "STALE -- breaches freshness SLO."}


@mcp.tool()
def check_schema_contract(model: str) -> dict[str, Any]:
    """Compare a model's actual output columns/types to its declared .yml contract.

    Drift not captured by a versioned contract change is a blocker. (DQF ch. 4;
    schema pillar). Returns added/removed/retyped columns.
    """
    log.info("check_schema_contract model=%s", model)
    declared: dict[str, str] = {}  # from models/**/<model>.yml
    actual: dict[str, str] = {}    # from `dbt compile` + information_schema
    added = sorted(set(actual) - set(declared))
    removed = sorted(set(declared) - set(actual))
    retyped = sorted(c for c in set(declared) & set(actual) if declared[c] != actual[c])
    ok = not (added or removed or retyped)
    return {"model": model, "added": added, "removed": removed, "retyped": retyped,
            "ok": ok,
            "message": "Contract holds." if ok else
                       "Schema drift -- update the versioned contract or fix the model."}


@mcp.tool()
def profile_table(table: str, row_limit: int = 1000) -> dict[str, Any]:
    """Lightweight profile: row count, per-column null rate, distinct counts.

    Supports the volume + distribution pillars. PII columns are profiled by
    null rate only -- never by value. (DQF ch. 4; FDE ch. 10)
    """
    log.info("profile_table table=%s", table)
    if PROTECTED_SCHEMAS.search(table) and table.lower().split(".")[0].endswith("_prod"):
        # reading prod is allowed read-only, but warn it must be the RO role
        log.warning("profiling a prod table -- confirm read-only role")
    columns: list[dict] = []  # [{"column": "...", "null_rate": 0.0, "distinct": 0}]
    columns = [{**c, "sampled_value": _redact(c.get("column", ""), c.get("sampled_value"))}
               for c in columns]
    return {"table": table, "row_count": None, "columns": columns,
            "note": "Wire to read-only conn; row_count feeds the volume check."}


@mcp.tool()
def dry_run_model(model: str) -> dict[str, Any]:
    """Compile + plan a model WITHOUT writing. Always safe. (mirrors dbt compile)

    Use before any real materialization. Returns compiled SQL + the planned
    materialization (table/incremental) and unique_key if declared.
    """
    log.info("dry_run_model model=%s", model)
    # `dbt compile --select <model>`; read target/compiled/.../<model>.sql + config
    return {"model": model, "compiled_sql": "", "materialization": None,
            "unique_key": None, "would_write": False,
            "note": "Dry run only. Set up dbt compile; inspect plan before --target dev run."}


if __name__ == "__main__":
    mcp.run()
