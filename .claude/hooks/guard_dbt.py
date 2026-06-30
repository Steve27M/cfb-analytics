#!/usr/bin/env python3
"""PreToolUse hook: blocks dangerous dbt / SQL actions outright.

Wired via .claude/settings.json hooks config to fire before Bash/Edit/Write.
Exit code 2 = block and feed the reason back to the agent. Exit 0 = allow.
This is enforcement, not a request -- the model cannot bypass it.

The hazards here are analytics-engineering-specific:
  - a --full-refresh against a prod target rewrites a prod table from scratch
  - DDL/DML against raw or source schemas violates bronze immutability (MED ch.3)
  - a model that SELECTs a raw table directly breaks the DAG (must go via source()/ref())
  - SELECT * in a mart leaks schema churn into BI and is banned by CLAUDE.md
  - secrets pasted into a model/macro
"""
import json
import re
import sys

# Names of prod-like dbt targets, matched against an explicit --target/-t flag.
# Set these to match your profiles.yml.
PROD_TARGETS = {"prod", "production", "prd"}

# --- Bash command hazards -------------------------------------------------

FULL_REFRESH = re.compile(r"\bdbt\s+(run|build)\b.*--full-refresh", re.IGNORECASE)
TARGET_FLAG = re.compile(r"(?:--target|-t)[=\s]+([A-Za-z0-9_]+)", re.IGNORECASE)

# DROP/DML aimed at a raw/source/prod schema, however phrased.
RAW_WRITE = re.compile(
    r"\b(drop|truncate|delete|update|insert|create|alter|merge|grant|revoke)\b"
    r"[^;]*\b(raw|raw_\w+|source|sources|landing|bronze|prod|production|\w+_prod)\b",
    re.IGNORECASE | re.DOTALL,
)

# --- File-content hazards (Edit/Write of a .sql model) --------------------

# A model in models/ selecting straight from a raw/landing/source schema instead
# of source()/ref(). dbt refs render as {{ ... }}, so a bare schema.table after
# FROM/JOIN is the smell.
RAW_IN_MODEL = re.compile(
    r"\b(from|join)\s+(?!\{\{)"               # FROM/JOIN not followed by a Jinja ref
    r"[`\"']?(raw|landing|source|sources|bronze|prod|production)[`\"']?\s*\.",
    re.IGNORECASE,
)
# SELECT * outside an import CTE. Allowed form is `select * from {{ ref(...) }}`
# or `{{ source(...) }}` (import CTEs). Anything else is a banned star.
STAR_OK = re.compile(r"select\s+\*\s+from\s+\{\{\s*(ref|source)\s*\(", re.IGNORECASE)
STAR_ANY = re.compile(r"select\s+\*", re.IGNORECASE)

SECRET = re.compile(
    r"(password|secret|api[_-]?key|access[_-]?key|private[_-]?key|token)\s*[:=]\s*"
    r"['\"][^'\"]{8,}['\"]",
    re.IGNORECASE,
)


def _block(reason: str) -> int:
    # stderr is surfaced to the agent as the block reason.
    print(f"BLOCKED: {reason}", file=sys.stderr)
    return 2


def check_bash(cmd: str) -> int:
    # --full-refresh against a prod target rewrites prod data.
    if FULL_REFRESH.search(cmd):
        m = TARGET_FLAG.search(cmd)
        target = m.group(1).lower() if m else ""
        # Block when target is explicitly prod, OR when no target is given and a
        # prod default could be in effect -- fail safe, make the agent be explicit.
        if target in PROD_TARGETS or target == "":
            return _block(
                "--full-refresh against a prod (or unspecified) target is blocked. "
                "Re-run with an explicit non-prod --target, or use an incremental "
                "build. Full-refresh on prod rewrites the table from scratch."
            )
    if RAW_WRITE.search(cmd):
        return _block(
            "DDL/DML against a raw/source/prod schema is blocked. Bronze/raw is "
            "immutable (Building Medallion Architectures, ch.3); route changes "
            "through a reviewed dbt model + migration instead."
        )
    return 0


def check_file(path: str, content: str) -> int:
    norm = "/" + path.replace("\\", "/").lstrip("/")  # normalize so segment match works for relative paths
    is_model = "/models/" in norm and norm.endswith(".sql")
    is_mart = "/marts/" in norm

    if SECRET.search(content):
        return _block("A hardcoded secret/credential was detected. Use env vars / "
                      "the warehouse's secret store, never inline.")

    if is_model and RAW_IN_MODEL.search(content):
        return _block(
            "This model selects directly from a raw/source/prod schema. Use "
            "{{ source(...) }} in a staging model and {{ ref(...) }} downstream "
            "so dbt builds the DAG (AE with SQL and dbt, ch.2)."
        )

    if is_mart:
        # Find every SELECT * and ensure each is an allowed import-CTE form.
        for m in STAR_ANY.finditer(content):
            window = content[m.start():m.start() + 80]
            if not STAR_OK.match(window.strip()):
                return _block(
                    "SELECT * found in a mart. Marts must enumerate columns "
                    "explicitly (CLAUDE.md non-negotiable); `*` is allowed only in "
                    "import CTEs `select * from {{ ref(...) }}`."
                )
    return 0


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0  # don't block on malformed input; fail open for availability

    tool = payload.get("tool_name", "")
    ti = payload.get("tool_input", {})

    if tool == "Bash":
        return check_bash(ti.get("command", ""))
    if tool in ("Edit", "Write"):
        path = ti.get("file_path", "") or ti.get("path", "")
        content = ti.get("new_string", "") or ti.get("content", "")
        return check_file(path, content)
    return 0


if __name__ == "__main__":
    sys.exit(main())
