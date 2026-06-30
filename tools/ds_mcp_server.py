#!/usr/bin/env python3
"""MCP server exposing safe, deterministic data-science / analysis operations.

The agent decides WHEN to call; these functions decide HOW it executes, with
guardrails baked in: read-only loads (no writes to raw), PII redaction in
profiles, an always-on multiple-comparison reminder on significance tests, and
chart linting that flags misleading encodings. Run as an MCP server; register in
.claude/settings.json mcpServers.

Wire the placeholder load/compute calls to your real data access. Nothing here
may ever open a writable handle to data/raw or the sealed split.
"""
import logging
import re
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("ds-tools")

mcp = FastMCP("ds-tools")

SEED = 42  # project-wide determinism convention

# Paths this server refuses to read in a way that could mutate, and refuses to
# treat as writable. Raw is immutable; the split is sealed (LDS ch. 8-9, 16, 18).
PROTECTED_PATH = re.compile(r"(^|/)data/(raw|splits)/", re.IGNORECASE)

# Column-name patterns treated as PII; values are redacted in any profile/sample.
PII_COLUMNS = re.compile(
    r"(?i)\b(email|ssn|social_security|phone|first_name|last_name|full_name|"
    r"home_address|street_address|dob|date_of_birth|card_number|account_number|"
    r"ip_address)\b"
)

# Feature-name tells that a column may leak the target or post-outcome info.
LEAKY_NAME = re.compile(
    r"(?i)(target|label|outcome|_actual\b|is_fraud|churned|will_|future_|"
    r"_next_|post_|after_|_resolved|repaid|defaulted)"
)


def _redact(col: str, value: Any) -> Any:
    """Never surface raw PII values; return a masked marker instead."""
    return "<redacted-pii>" if PII_COLUMNS.search(col) else value


@mcp.tool()
def load_readonly(path: str, n_rows: int = 1000) -> dict[str, Any]:
    """Load the head of a tabular file READ-ONLY. Refuses any write target.

    Refuses to load from data/raw or data/splits via a writable angle, and never
    returns raw PII values. Use this instead of opening files directly so the
    immutability + sealed-split invariants hold. (PRINCIPLES sec. 1-2, 6)
    """
    p = path.replace("\\", "/")
    # Reading raw read-only is fine, but we make the read-only contract explicit
    # and never expose a write path. Mutating opens are simply not implemented.
    log.info("load_readonly path=%s n_rows=%d (read-only)", p, n_rows)
    if not Path(path).exists():
        return {"error": f"Path not found: {path}"}
    # df = pd.read_parquet(path) ... .head(n_rows)   # wire to your loader (mode='r')
    rows: list[dict] = []  # placeholder
    rows = [{k: _redact(k, v) for k, v in r.items()} for r in rows]
    return {"path": p, "mode": "read-only", "rows": rows, "row_count": len(rows),
            "note": "Wire to a read-only loader; PII columns are redacted in output."}


@mcp.tool()
def profile_dataframe(path: str) -> dict[str, Any]:
    """Profile a table: per-column dtype, null rate, range, and cardinality.

    Supports the data-quality checks (granularity, scope, measurement quality).
    PII columns are profiled by null rate / cardinality only -- never by value.
    (PRINCIPLES sec. 2; LDS ch. 9 "Quality Checks")
    """
    log.info("profile_dataframe path=%s", path)
    # df = read_readonly(path)
    columns: list[dict] = []  # [{"column","dtype","null_rate","min","max","n_unique"}]
    columns = [
        {**c, "min": _redact(c.get("column", ""), c.get("min")),
         "max": _redact(c.get("column", ""), c.get("max"))}
        for c in columns
    ]
    return {
        "path": path,
        "row_count": None,
        "columns": columns,
        "note": ("Wire to read-only conn. Confirm granularity (what is ONE row?), "
                 "in-range values, and sane null rates before any analysis."),
    }


@mcp.tool()
def check_sampling_bias(
    path: str, column: str, expected_distribution: dict[str, float] | None = None
) -> dict[str, Any]:
    """Compare a column's observed distribution to a known/target distribution.

    Surfaces coverage / selection bias: if the sample's mix diverges from the
    target population's, conclusions about the population are suspect.
    (PRINCIPLES sec. 3; LDS ch. 2 "Types of Bias")
    """
    log.info("check_sampling_bias path=%s column=%s", path, column)
    observed: dict[str, float] = {}  # value -> proportion in the sample
    if expected_distribution is None:
        return {"column": column, "observed": observed,
                "note": ("Provide expected_distribution (target population mix) to "
                         "score divergence. Without a reference you can only report "
                         "the observed mix, not the bias.")}
    # max abs difference in proportions as a simple, transparent divergence score.
    keys = set(observed) | set(expected_distribution)
    max_gap = max((abs(observed.get(k, 0.0) - expected_distribution.get(k, 0.0))
                   for k in keys), default=0.0)
    biased = max_gap > 0.05  # transparent threshold; tune per project
    return {"column": column, "observed": observed, "expected": expected_distribution,
            "max_abs_gap": max_gap, "likely_biased": biased,
            "message": ("Sample mix matches target." if not biased else
                        "Sample diverges from target population -- coverage/selection "
                        "bias likely; caveat any population-level conclusion.")}


@mcp.tool()
def run_significance_test(
    test: str,
    p_value: float,
    n_comparisons: int = 1,
    confidence_interval: list[float] | None = None,
    n: int | None = None,
) -> dict[str, Any]:
    """Evaluate a significance result HONESTLY -- never on p alone.

    Applies a Bonferroni correction when n_comparisons > 1, requires a confidence
    interval to call anything a finding, and flags small-n results that should use
    the t-distribution. `p < 0.05` by itself is NOT a finding.
    (PRINCIPLES sec. 5; EMDS ch. 3; DSH ch. 19.4 "Multiple Hypothesis Testing")
    """
    log.info("run_significance_test test=%s p=%.4g k=%d", test, p_value, n_comparisons)
    # Bonferroni: divide alpha by the number of comparisons (or scale p up).
    corrected_alpha = 0.05 / max(n_comparisons, 1)
    significant_after_correction = p_value < corrected_alpha
    warnings = []
    if n_comparisons > 1:
        warnings.append(
            f"{n_comparisons} comparisons: alpha corrected to {corrected_alpha:.4g} "
            "(Bonferroni). Report the correction.")
    if confidence_interval is None:
        warnings.append(
            "No confidence interval supplied. A point estimate without an interval "
            "is not a finding -- report the CI/uncertainty.")
    if n is not None and n < 31:
        warnings.append(
            f"n={n} < 31: use the t-distribution, not z, for the interval.")
    return {
        "test": test,
        "p_value": p_value,
        "corrected_alpha": corrected_alpha,
        "significant_after_correction": significant_after_correction,
        "confidence_interval": confidence_interval,
        "warnings": warnings,
        "verdict": ("Reportable IF a CI is given and the hypothesis was pre-framed."
                    if significant_after_correction and confidence_interval
                    else "NOT a finding on this evidence -- see warnings."),
    }


@mcp.tool()
def check_leakage(feature_cols: list[str], target: str) -> dict[str, Any]:
    """Flag features that may leak the target or post-outcome information.

    Heuristic name-based screen: any feature equal to the target, or named like a
    label/outcome/future/post-event field, is suspect. Empirical leakage (a feature
    suspiciously predictive of the target) still needs an ablation -- this is the
    cheap first pass. (PRINCIPLES sec. 6; LDS ch. 16)
    """
    log.info("check_leakage target=%s n_features=%d", target, len(feature_cols))
    suspects = []
    for col in feature_cols:
        if col == target:
            suspects.append({"feature": col, "reason": "feature IS the target"})
        elif LEAKY_NAME.search(col):
            suspects.append({"feature": col,
                             "reason": "name suggests label/outcome/future/post-event info"})
    return {
        "target": target,
        "n_features": len(feature_cols),
        "suspects": suspects,
        "ok": not suspects,
        "message": ("No obvious leakage by name -- still fit transforms on TRAIN "
                    "only, dedupe before splitting, split time-data by time, and "
                    "ablate any feature that looks too predictive."
                    if not suspects else
                    "Potential leakage -- review/remove the flagged features before "
                    "trusting any score."),
    }


@mcp.tool()
def render_chart_lint(spec: dict[str, Any]) -> dict[str, Any]:
    """Lint a chart spec for misleading encodings before it ships.

    Flags: non-zero baseline on bar/area charts, truncated/dual axes, size encoded
    by radius/diameter instead of area, missing axis labels, hue-only encoding.
    (PRINCIPLES sec. 8; VT ch. 1; CWD ch. 3 & 5)

    `spec` keys (all optional): chart_type, y_axis_min, dual_axis (bool),
    size_encoding ("area"|"radius"|"diameter"), axes_labeled (bool),
    color_encoding ("hue_only"|...), is_3d (bool).
    """
    log.info("render_chart_lint chart_type=%s", spec.get("chart_type"))
    issues: list[str] = []
    ctype = str(spec.get("chart_type", "")).lower()

    if ctype in ("bar", "column", "histogram", "area") and spec.get("y_axis_min") not in (0, 0.0, None):
        issues.append("Bar/area baseline is not zero -- truncated axis exaggerates "
                      "differences. Start the value axis at zero.")
    if spec.get("dual_axis"):
        issues.append("Dual axes mix scales and mislead; split into two charts or "
                      "justify and align the scales explicitly.")
    if str(spec.get("size_encoding", "")).lower() in ("radius", "diameter"):
        issues.append("Size encoded by radius/diameter, not area -- doubling the "
                      "diameter quadruples the area. Encode by area.")
    if spec.get("axes_labeled") is False:
        issues.append("Unlabeled axes -- 'without labels your axes are just there "
                      "for decoration'. Label them.")
    if str(spec.get("color_encoding", "")).lower() == "hue_only":
        issues.append("Encoding by hue alone is not colorblind-safe -- double-encode "
                      "(position/shape/label) or use an accessible palette.")
    if spec.get("is_3d"):
        issues.append("3-D on 2-D data distorts comparison -- drop the third dimension.")

    return {"chart_type": ctype or None, "issues": issues, "ok": not issues,
            "message": "Chart encodes honestly." if not issues else
                       "Misleading encoding(s) -- fix before sharing."}


if __name__ == "__main__":
    mcp.run()
