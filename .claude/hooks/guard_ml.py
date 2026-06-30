#!/usr/bin/env python3
"""PreToolUse hook: blocks the catastrophic, irreversible ML mistakes outright.

Wired via .claude/settings.json hooks config to fire before Bash/Edit/Write.
Exit code 2 = block and feed the reason back to the agent (via stderr).
Exit 0 = allow. This is enforcement, not a suggestion -- the model cannot bypass it.

We block, regardless of phrasing, the four mistakes that silently destroy a project's
validity (and which a model is most likely to make when trying to be "helpful"):

  1. Touching the sealed TEST split        -> data snooping / invalid generalization
                                              (Hands-On ML ch.2; Designing ML Systems ch.6)
  2. Writing/DDL against a prod/raw schema  -> destroys source-of-truth data
  3. Adding a known leakage column          -> target/post-outcome leakage
                                              (Designing ML Systems ch.5)
  4. fit_transform on a non-train split     -> fits preprocessing on val/test (leakage)
                                              (Designing ML Systems ch.5; Hands-On ML ch.2)

Tune the sets/patterns below to your project before relying on this hook.
"""
import json
import re
import sys

# --- Project-specific knobs -------------------------------------------------
# Paths / table names that hold the SEALED test set. Only src/eval.py should
# read these, and only at final evaluation. The hook blocks all other access.
TEST_ARTIFACTS = re.compile(
    r"(data/test/|/test_split|\btest_set\b|\bX_test\b|\by_test\b|\.test\.parquet)",
    re.IGNORECASE,
)
# Columns that must never appear as model features (target + post-outcome).
FORBIDDEN_FEATURES = {
    "is_target", "target", "label", "y_true", "outcome",
    "resolved_at", "closed_at", "final_status",  # post-outcome timestamps/state
}
# --------------------------------------------------------------------------

# Write/DDL/DML against a prod- or raw-looking schema, regardless of phrasing.
PROD_WRITE = re.compile(
    r"\b(drop|truncate|delete|update|insert|create|alter|merge)\b.*"
    r"\b(prod|production|raw|\w+_prod)\b",
    re.IGNORECASE | re.DOTALL,
)
PROD_SCHEMA = re.compile(r"\bUSE\s+(SCHEMA|DATABASE)\s+\w*PROD", re.IGNORECASE)
# fit_transform / fit() applied to a test or validation split -> leakage.
FIT_ON_HOLDOUT = re.compile(
    r"\.fit(_transform)?\s*\(\s*[^)]*\b(X_test|y_test|X_val|X_valid|test_|val_)",
    re.IGNORECASE,
)


def _feature_leakage(text: str) -> set[str]:
    """Return forbidden columns that appear as quoted string literals in the text.

    Heuristic: catches feature lists like FEATURES = ["...","resolved_at"].
    Cheap and high-signal; the MCP check_leakage tool is the thorough check.
    """
    quoted = set(re.findall(r"""['"]([A-Za-z0-9_]+)['"]""", text))
    return {c.lower() for c in quoted} & FORBIDDEN_FEATURES


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0  # don't block on malformed input; fail open for availability

    tool = payload.get("tool_name", "")
    ti = payload.get("tool_input", {}) or {}

    if tool == "Bash":
        text = ti.get("command", "")
        target_path = ""
    elif tool in ("Edit", "Write"):
        text = ti.get("new_string", "") or ti.get("content", "")
        target_path = ti.get("file_path", "") or ""
    else:
        return 0

    # 1. Sealed test set: block any write to a test artifact path, and block any
    #    command/code that reads or mutates the test split outside src/eval.py.
    if TEST_ARTIFACTS.search(target_path) and "eval.py" not in target_path:
        return _block(
            "The TEST split is sealed. Only src/eval.py may touch it, once, at final "
            "eval. Use the validation split or cross-validation for everything else."
        )
    if TEST_ARTIFACTS.search(text) and "eval.py" not in target_path:
        return _block(
            "Reference to the sealed TEST split detected outside eval. Tune on "
            "validation/CV only; the test set is touched exactly once."
        )

    # 2. Prod/raw writes.
    if PROD_WRITE.search(text):
        return _block(
            "Write/DDL against a prod/raw schema is blocked. Route through a reviewed "
            "migration; exploration is read-only via ANALYTICS_RO."
        )
    if PROD_SCHEMA.search(text):
        return _block("Switching to a prod schema is blocked; use ANALYTICS_RO.")

    # 3. Known leakage columns added as features.
    leaks = _feature_leakage(text)
    if leaks:
        return _block(
            f"Leakage columns referenced as features: {sorted(leaks)}. These derive "
            "from the target or post-outcome data and must not be features."
        )

    # 4. Fitting preprocessing on a holdout split.
    if FIT_ON_HOLDOUT.search(text):
        return _block(
            "fit()/fit_transform() on a test/validation split leaks. Fit transforms on "
            "TRAIN only, then .transform() the holdout splits."
        )

    return 0


def _block(reason: str) -> int:
    # stderr is surfaced to the agent as the block reason.
    print(f"BLOCKED: {reason}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
