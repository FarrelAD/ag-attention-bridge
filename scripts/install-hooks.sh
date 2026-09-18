#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "=== Installing Ag Attention Bridge Globally for Antigravity ==="

# 1. Ensure ~/.local/bin exists
mkdir -p "$HOME/.local/bin"

# 2. Symlink binaries to ~/.local/bin
echo "- Installing executables to $HOME/.local/bin..."
ln -sfn "$REPO_ROOT/scripts/hook-adapter.sh" "$HOME/.local/bin/ag-hook-adapter"
chmod +x "$HOME/.local/bin/ag-hook-adapter"

# Create launcher wrapper for ag-attention-bridge
cat > "$HOME/.local/bin/ag-attention-bridge" <<EOF
#!/usr/bin/env bash
if [ -x "$REPO_ROOT/.venv/bin/python3" ]; then
    exec "$REPO_ROOT/.venv/bin/python3" -m ag_attention_bridge.app "\$@"
else
    exec python3 -m ag_attention_bridge.app "\$@"
fi
EOF
chmod +x "$HOME/.local/bin/ag-attention-bridge"

echo "  -> ag-hook-adapter installed"
echo "  -> ag-attention-bridge installed"

# 3. Configure ~/.gemini/config/hooks.json
CONFIG_DIR="$HOME/.gemini/config"
HOOKS_FILE="$CONFIG_DIR/hooks.json"
mkdir -p "$CONFIG_DIR"

if [ -f "$HOOKS_FILE" ]; then
    cp "$HOOKS_FILE" "$HOOKS_FILE.bak"
    echo "- Backed up existing hooks.json to hooks.json.bak"
fi

# Merge configuration safely using python
"$REPO_ROOT/.venv/bin/python3" - <<EOF
import json
from pathlib import Path

hooks_path = Path("$HOOKS_FILE")
config = {}
if hooks_path.exists():
    try:
        config = json.loads(hooks_path.read_text(encoding="utf-8"))
    except Exception:
        config = {}

config["ag-attention-bridge"] = {
    "PreToolUse": [
        {
            "matcher": "ask_question|ask_permission",
            "hooks": [
                {
                    "type": "command",
                    "command": "$HOME/.local/bin/ag-hook-adapter --event PreToolUse",
                    "timeout": 30
                }
            ]
        }
    ],
    "PreInvocation": [
        {
            "type": "command",
            "command": "$HOME/.local/bin/ag-hook-adapter --event PreInvocation",
            "timeout": 15
        }
    ],
    "PostInvocation": [
        {
            "type": "command",
            "command": "$HOME/.local/bin/ag-hook-adapter --event PostInvocation",
            "timeout": 15
        }
    ],
    "Stop": [
        {
            "type": "command",
            "command": "$HOME/.local/bin/ag-hook-adapter --event Stop",
            "timeout": 15
        }
    ]
}


hooks_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
print("- Successfully updated $HOOKS_FILE")
EOF

# 4. Restart daemon in background with updated code
echo "- Restarting Ag Attention Bridge daemon in background..."
pkill -f "ag-attention-bridge" || true
pkill -f "ag_attention_bridge" || true
sleep 0.5
nohup "$HOME/.local/bin/ag-attention-bridge" >/dev/null 2>&1 &

echo ""
echo "=== Ag Attention Bridge Global Installation Complete! ==="
echo "Global Hooks File: $HOOKS_FILE"
echo "Installed Commands: $HOME/.local/bin/ag-hook-adapter, $HOME/.local/bin/ag-attention-bridge"
echo "System Tray: Activated on KDE Plasma panel"
echo "Lifecycle: Auto-Start on hook call & Auto-Shutdown when Antigravity exits."
