#!/bin/bash
set -euo pipefail

# Only run in Claude Code cloud sessions.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR"

# Harmony requires Python >=3.12; use a project venv so the default
# interpreter is left alone. Re-running is idempotent.
if [ ! -x .venv/bin/python ]; then
  python3.12 -m venv .venv
fi

.venv/bin/python -m pip install --quiet --upgrade pip
.venv/bin/python -m pip install --quiet -e ".[dev]"

# Put the venv first on PATH for the session (pytest, python, alembic).
echo "export VIRTUAL_ENV=\"$CLAUDE_PROJECT_DIR/.venv\"" >> "$CLAUDE_ENV_FILE"
echo "export PATH=\"$CLAUDE_PROJECT_DIR/.venv/bin:\$PATH\"" >> "$CLAUDE_ENV_FILE"
