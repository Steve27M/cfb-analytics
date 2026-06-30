#!/usr/bin/env python3
"""MCP server exposing safe, deterministic MLE operations.

The agent decides WHEN to call; these functions decide HOW it executes, with the
guardrails baked in: a SELECT-only query, a leakage check, dry-run-by-default training,
a content data hash for reproducibility, and per-segment slice metrics. None of these
can touch the sealed test set.

Run as an MCP server; register in .claude/settings.json mcpServers.
Wire the placeholders (read-only connection, table reader, model loader) to your stack.
"""
import hashlib
import json
import logging
import re
from typing import Any

from mcp.server.fastmcp import FastMCP

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("ml-tools")

mcp = FastMCP("ml-tools")

SEED = 42  # project-wide convention

# Columns that must never appear as features (target + post-outcome leakage).
# Keep in sync with .claude/hooks/guard.py FORBIDDEN_FEATURES.
FORBIDDEN_FEATURES = {
    "is_target", "target", "label", "y_true", "outcome",
    "resolved_at", "closed_at", "final_status",
}

# Substrings that flag a feature as predict-time-unavailable / post-outcome.
LEAKY_SUBSTRINGS = ("_future", "_post_", "resolved", "closed", "outcome", "_at_close")

_MUTATING = ("insert", "update", "delete", "drop", "merge", "alter", "truncate", "create")


@mcp.tool()
def query_readonly(sql: str, row_limit: int = 1000) -> dict[str, Any]:
    """Run a SELECT against the read replica (ANALYTICS_RO). Rejects any non-SELECT.

    Caps rows to protect against accidental full-table pulls. Exploration only --
    this tool cannot write, and the hook blocks prod writes independently.
    """
    stripped = sql.strip().rstrip(";")
    low = stripped.lower()
    if not low.startswith(("select", "with")):
        return {"error": "Only SELECT/WITH queries are permitted via this tool."}
    if any(re.search(rf"\b{kw}\b", low) for kw in _MUTATING):
        return {"error": "Mutating keyword detected; rejected."}

    safe_sql = f"SELECT * FROM ({stripped}) _q LIMIT {min(row_limit, 10_000)}"
    log.info("query_readonly rows<=%d", row_limit)
    try:
        # rows = analytics_ro.execute(safe_sql).fetchall()  # wire to your RO conn
        rows: list[dict] = []  # placeholder
        return {"rows": rows, "row_count": len(rows), "truncated": len(rows) >= row_limit}
    except Exception as e:  # surface, don't crash the agent loop
        log.exception("query failed")
        return {"error": f"Query failed: {e}"}


@mcp.tool()
def check_leakage(feature_columns: list[str]) -> dict[str, Any]:
    """Validate a proposed feature set against the leakage blocklist + heuristics.

    Call BEFORE training. Flags exact-match forbidden columns AND columns whose names
    suggest post-outcome / predict-time-unavailable data. (Designing ML Systems, ch. 5)
    """
    cols = [c.lower() for c in feature_columns]
    exact = sorted(set(cols) & FORBIDDEN_FEATURES)
    suspect = sorted({c for c in cols if any(s in c for s in LEAKY_SUBSTRINGS)} - set(exact))
    ok = not exact and not suspect
    log.info("check_leakage ok=%s exact=%s suspect=%s", ok, exact, suspect)
    return {
        "ok": ok,
        "forbidden": exact,
        "suspect": suspect,
        "message": "Clean."
        if ok
        else f"Remove leakage columns {exact}; review suspect columns {suspect}.",
    }


@mcp.tool()
def train(config_path: str, dry_run: bool = True) -> dict[str, Any]:
    """Launch a training run. Defaults to dry_run (validates config + split + leakage).

    A real run requires dry_run=False AND passing leakage + split checks first. The
    test split is never loaded here -- it stays sealed until src/eval.py.
    """
    log.info("train config=%s dry_run=%s seed=%d", config_path, dry_run, SEED)
    # 1. load+validate config  2. verify split is hash-based/seed=42 from splits.py
    # 3. run check_leakage on configured features  4. fit transforms on TRAIN only
    # 5. dry_run -> return plan; else kick off + log params/metrics/data_hash/git_sha to MLflow
    if dry_run:
        return {
            "status": "validated",
            "would_run": True,
            "seed": SEED,
            "note": "Set dry_run=False to execute. Test split untouched until eval.",
        }
    return {"status": "started", "run_id": "mlflow_run_xxx", "seed": SEED}


@mcp.tool()
def data_hash(table: str) -> dict[str, str]:
    """Return a content hash of a training table for reproducibility logging.

    Hash the CONTENT, not the path -- two refreshes at the same path differ.
    (Designing ML Systems, ch. 6; Building ML Pipelines, ch. 3)
    """
    # df = read(table); payload = df.to_csv(index=False).encode()  # canonical serialize
    payload = table.encode()  # placeholder
    return {"table": table, "sha256": hashlib.sha256(payload).hexdigest()[:16]}


@mcp.tool()
def slice_metrics(
    predictions_path: str,
    segment_columns: list[str],
    metric: str = "f1",
    min_support: int = 30,
) -> dict[str, Any]:
    """Compute the chosen metric per segment from a saved predictions file.

    Aggregate metrics hide subgroup failures (Designing ML Systems, ch. 6;
    ML Design Patterns, DP 30 Fairness Lens). Returns per-slice scores and flags the
    worst slices (>10% below overall) with enough support to be meaningful.
    """
    log.info("slice_metrics path=%s by=%s metric=%s", predictions_path, segment_columns, metric)
    try:
        # df = read_predictions(predictions_path)
        # overall = compute(metric, df.y_true, df.y_pred)
        # per_slice = {seg: compute(metric, g.y_true, g.y_pred) for seg, g in df.groupby(segment_columns) if len(g) >= min_support}
        overall: float = 0.0          # placeholder
        per_slice: dict[str, float] = {}  # placeholder
        flagged = [s for s, v in per_slice.items() if v < 0.9 * overall]
        return {
            "metric": metric,
            "overall": overall,
            "by_segment": per_slice,
            "flagged_slices": flagged,
            "min_support": min_support,
            "verdict": "review" if flagged else "ok",
        }
    except Exception as e:
        log.exception("slice_metrics failed")
        return {"error": f"slice_metrics failed: {e}"}


@mcp.tool()
def baseline_metrics(predictions_path: str, metric: str = "f1") -> dict[str, Any]:
    """Compute majority/zero-rule + uniform-random baselines for context.

    Never trust a model metric in isolation -- report it relative to baselines.
    (Designing ML Systems, ch. 6 Baselines; ML Design Patterns, DP 28 Heuristic Benchmark)
    """
    log.info("baseline_metrics path=%s metric=%s", predictions_path, metric)
    # df = read_predictions(predictions_path); majority = most_frequent(df.y_true)
    return {
        "metric": metric,
        "majority_class": None,   # placeholder
        "uniform_random": None,   # placeholder
        "note": "Report the model's metric as a delta over these baselines.",
    }


if __name__ == "__main__":
    mcp.run()
