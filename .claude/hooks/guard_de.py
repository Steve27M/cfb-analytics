#!/usr/bin/env python3
"""PreToolUse hook: blocks data-engineering hazards outright.

Wired via .claude/settings.json hooks config to fire before Bash/Edit/Write.
Exit code 2 = block and feed the reason back to the agent. Exit 0 = allow.
This is enforcement, not a request -- the model cannot bypass it.

The invariants enforced here trace to CLAUDE.md / PRINCIPLES.md:
  - never write/DDL against raw, source, or *_prod schemas (FDE ch. 10, ch. 7)
  - bronze/raw is immutable: no DROP/TRUNCATE of bronze/raw (FDE ch. 6)
  - non-idempotent bulk deletes (TRUNCATE / unfiltered DELETE) are unsafe to
    re-run (FDE ch. 7 -- idempotency)
  - secrets must not be written into code (FDE ch. 10)
"""
import json
import re
import sys

# DDL/DML aimed at a protected schema (raw / source / prod). Catches phrasing
# like "DROP TABLE raw.events", "INSERT INTO orders_prod", "ALTER ... source_".
PROTECTED_WRITE = re.compile(
    r"\b(drop|truncate|delete|update|insert|create|alter|merge|grant|revoke)\b"
    r"[\s\S]*?\b(raw|source|prod|production|bronze|\w+_prod|\w+_raw|\w+_source)\b",
    re.IGNORECASE,
)

# Switching the active schema/database to a prod target.
PROD_SCHEMA = re.compile(r"\bUSE\s+(SCHEMA|DATABASE)\s+\w*(PROD|RAW)", re.IGNORECASE)

# Non-idempotent destructive ops: TRUNCATE always, or DELETE with no WHERE.
# Re-running these is not safe -- they erase history that backfills rely on.
TRUNCATE = re.compile(r"\btruncate\s+table\b", re.IGNORECASE)
DELETE_NO_PREDICATE = re.compile(
    r"\bdelete\s+from\s+[\w.\"`]+\s*(;|$)", re.IGNORECASE
)

# dbt full-refresh against prod wipes and rebuilds incrementals -- gate it.
DBT_FULL_REFRESH_PROD = re.compile(
    r"dbt\s+(run|build)\b[\s\S]*--full-refresh[\s\S]*--target\s+prod"
    r"|dbt\s+(run|build)\b[\s\S]*--target\s+prod[\s\S]*--full-refresh",
    re.IGNORECASE,
)

# Hardcoded secrets being written into a file (key/token/password = literal).
SECRET_LITERAL = re.compile(
    r"(?i)\b(password|passwd|secret|api[_-]?key|access[_-]?key|token|"
    r"snowflake_password|aws_secret_access_key)\b\s*[:=]\s*[\"']?[A-Za-z0-9/+=_\-]{8,}"
)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0  # don't block on malformed input; fail open for availability

    tool = payload.get("tool_name", "")
    text = ""
    if tool == "Bash":
        text = payload.get("tool_input", {}).get("command", "")
    elif tool in ("Edit", "Write"):
        ti = payload.get("tool_input", {})
        text = ti.get("new_string", "") or ti.get("content", "")
    else:
        return 0

    # Order matters: most specific / most dangerous first.
    checks = (
        (PROTECTED_WRITE,
         "DDL/DML against a raw/source/prod/bronze schema is blocked. "
         "Bronze is immutable; never write to source or prod. "
         "Route through a reviewed migration / dbt model on silver/gold."),
        (PROD_SCHEMA,
         "Switching to a prod/raw schema is blocked; use a read-only target."),
        (DBT_FULL_REFRESH_PROD,
         "dbt --full-refresh against prod rebuilds incrementals destructively. "
         "Use --target dev, or get explicit sign-off for a prod full-refresh."),
        (TRUNCATE,
         "TRUNCATE is not idempotent and erases history backfills depend on. "
         "Use an idempotent merge/incremental write with a partition predicate."),
        (DELETE_NO_PREDICATE,
         "DELETE without a WHERE predicate is a non-idempotent full wipe. "
         "Add a partition/key predicate so the op is safe to re-run."),
        (SECRET_LITERAL,
         "Hardcoded secret detected. Use env vars / a secrets manager, never "
         "literals in code (least privilege, no secrets in source)."),
    )

    for pattern, reason in checks:
        if pattern.search(text):
            # stderr is surfaced to the agent as the block reason.
            print(f"BLOCKED: {reason}", file=sys.stderr)
            return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
