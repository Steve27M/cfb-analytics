#!/usr/bin/env python3
"""PreToolUse hook: blocks data-science analysis hazards outright.

Wired via .claude/settings.json hooks config to fire before Bash/Edit/Write.
Exit code 2 = block and feed the reason back to the agent. Exit 0 = allow.
This is enforcement, not a request -- the model cannot bypass it.

The invariants enforced here trace to CLAUDE.md / PRINCIPLES.md:
  - raw data is read-only & immutable (LDS ch. 8-9)
  - the test/holdout split is sealed -- it must not enter modeling decisions
    (LDS ch. 16 & 18)
  - PII / secrets never land in committed notebooks, outputs, or code
    (operational guardrail)
  - committing un-stripped notebook outputs risks leaking embedded data/PII
"""
import json
import re
import sys

# Writes/edits aimed at the immutable source of record. data/raw is the record
# of what was collected; cleaning must produce a NEW artifact under interim.
# Path is normalized to forward slashes before matching (Windows-safe).
RAW_DATA_WRITE = re.compile(r"(^|/)data/raw/", re.IGNORECASE)

# The split definition + any obvious holdout/test artifact. The test set is set
# aside before modeling and must not "enter into any decision making". Editing
# it (re-splitting to chase a better score, peeking, tuning on it) is p-hacking.
SEALED_SPLIT = re.compile(
    r"(^|/)data/splits/"
    r"|(^|/)(holdout|test[_-]?set|x[_-]?test|y[_-]?test)\.(csv|parquet|pkl|npy|feather)",
    re.IGNORECASE,
)

# Shell-side destructive moves against raw/splits: rm/mv/cp clobbering the
# source, or a redirect ( > ) overwriting a raw/split file. Catches what the
# path-based checks above miss when the write happens via Bash.
SHELL_CLOBBER = re.compile(
    r"\b(rm|mv|cp|truncate|dd)\b[\s\S]*\bdata/(raw|splits)/"
    r"|>\s*[^\s|;&]*data/(raw|splits)/",
    re.IGNORECASE,
)

# git-committing notebooks that still carry executed outputs. Outputs can embed
# rendered rows (PII) and aren't reproducible -- strip them first (nbstripout).
GIT_COMMIT_NOTEBOOK = re.compile(
    r"\bgit\s+(commit|add)\b[\s\S]*\.ipynb", re.IGNORECASE
)

# Hardcoded secrets written into a file or command (literal key/token/password).
SECRET_LITERAL = re.compile(
    r"(?i)\b(password|passwd|secret|api[_-]?key|access[_-]?key|token|"
    r"aws_secret_access_key|client_secret)\b\s*[:=]\s*[\"']?[A-Za-z0-9/+=_\-]{8,}"
)

# Obvious PII column values being printed/logged in code being written. We block
# print/display/log of a literal row containing identifier fields.
PII_PRINT = re.compile(
    r"(?i)\b(print|display|log(?:ger)?\.\w+|logging\.\w+)\s*\([^)]*"
    r"\b(email|ssn|social_security|phone|first_name|last_name|full_name|"
    r"home_address|street_address|date_of_birth|dob|card_number|account_number)\b"
)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0  # don't block on malformed input; fail open for availability

    tool = payload.get("tool_name", "")
    text = ""          # the content/command to scan for hazardous patterns
    path = ""          # the target file path (Edit/Write), normalized
    if tool == "Bash":
        text = payload.get("tool_input", {}).get("command", "")
        path = text
    elif tool in ("Edit", "Write"):
        ti = payload.get("tool_input", {})
        path = ti.get("file_path", "") or ti.get("path", "")
        text = ti.get("new_string", "") or ti.get("content", "")
    else:
        return 0

    # Normalize Windows backslashes so path patterns match cross-platform.
    norm_path = path.replace("\\", "/")
    norm_text = text.replace("\\", "/")

    # (pattern, haystack, reason) -- most dangerous / most specific first.
    checks = (
        (RAW_DATA_WRITE, norm_path,
         "data/raw/** is read-only and immutable -- it is the record of what was "
         "collected. Write cleaned output to data/interim/ instead. (PRINCIPLES sec. 1-2)"),
        (SEALED_SPLIT, norm_path,
         "The test/holdout split is SEALED. It must not enter into any modeling "
         "decision -- editing/re-splitting it to chase a score is p-hacking. "
         "Tune with cross-validation on the training set. (PRINCIPLES sec. 5-6)"),
        (SHELL_CLOBBER, norm_text,
         "Refusing a shell op that overwrites/deletes data/raw or data/splits. "
         "Raw is immutable and the split is sealed. (PRINCIPLES sec. 1-2, 6)"),
        (GIT_COMMIT_NOTEBOOK, norm_text,
         "Committing a notebook -- strip outputs first (`uv run nbstripout`). "
         "Executed outputs can embed PII and aren't reproducible. (CLAUDE.md non-negotiable 10)"),
        (SECRET_LITERAL, norm_text,
         "Hardcoded secret detected. Use env vars / a secrets manager, never "
         "literals in code or notebooks. (CLAUDE.md non-negotiable 10)"),
        (PII_PRINT, norm_text,
         "Printing/logging raw PII columns is blocked. Mask or omit identifier "
         "fields; never surface raw PII. (CLAUDE.md non-negotiable 10)"),
    )

    for pattern, haystack, reason in checks:
        if pattern.search(haystack):
            # stderr is surfaced to the agent as the block reason.
            print(f"BLOCKED: {reason}", file=sys.stderr)
            return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
