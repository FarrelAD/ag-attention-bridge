#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "=== Uninstalling Ag Attention Bridge from Global Antigravity ==="

# 1. Remove symlinks in ~/.local/bin
rm -f "$HOME/.local/bin/ag-hook-adapter"
rm -f "$HOME/.local/bin/ag-attention-bridge"
echo "- Removed binaries from $HOME/.local/bin"

# 2. Remove configuration from ~/.gemini/config/hooks.json
HOOKS_FILE="$HOME/.gemini/config/hooks.json"
if [ -f "$HOOKS_FILE" ]; then
    "$REPO_ROOT/.venv/bin/python3" - <<EOF
import json
from pathlib import Path

hooks_path = Path("$HOOKS_FILE")
try:
    config = json.loads(hooks_path.read_text(encoding="utf-8"))
    if "ag-attention-bridge" in config:
        del config["ag-attention-bridge"]
        if config:
            hooks_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        else:
            hooks_path.unlink()
        print("- Removed ag-attention-bridge from $HOOKS_FILE")
    else:
        print("- ag-attention-bridge not found in $HOOKS_FILE")
except Exception as e:
    print(f"- Warning: could not parse $HOOKS_FILE: {e}")
EOF
fi

echo "=== Ag Attention Bridge Uninstallation Complete ==="
