#!/usr/bin/env bash
set -e

# Resolve canonical script path and repository root
SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

# Select python interpreter: prefer .venv if present
if [ -x "$REPO_ROOT/.venv/bin/python3" ]; then
    PYTHON_BIN="$REPO_ROOT/.venv/bin/python3"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3)"
else
    echo "[hook-adapter.sh] Error: python3 not found" >&2
    echo "{}"
    exit 0
fi

# Ensure src is on PYTHONPATH
export PYTHONPATH="$REPO_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

# Execute adapter passing stdin and arguments
exec "$PYTHON_BIN" -m ag_attention_bridge.hooks.adapter "$@"
