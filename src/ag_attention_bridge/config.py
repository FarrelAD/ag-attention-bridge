"""Configuration and paths for Ag Attention Bridge."""

from __future__ import annotations

import os
from datetime import UTC
from pathlib import Path


def get_xdg_runtime_dir() -> Path:
    """Return runtime directory, defaulting to %LOCALAPPDATA% on Windows or /tmp on POSIX."""
    xdg_runtime = os.environ.get("XDG_RUNTIME_DIR")
    if xdg_runtime:
        return Path(xdg_runtime)
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        path = base / "ag-attention-bridge" / "run"
    else:
        uid = os.getuid() if hasattr(os, "getuid") else 1000
        path = Path(f"/tmp/ag-bridge-{uid}")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def get_xdg_state_dir() -> Path:
    """Return state directory (%LOCALAPPDATA% on Windows, ~/.local/state on POSIX)."""
    xdg_state = os.environ.get("XDG_STATE_HOME")
    if xdg_state:
        base = Path(xdg_state)
    elif os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path.home() / ".local" / "state"
    path = base / "ag-attention-bridge"
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


# On Windows, QLocalServer uses Named Pipe "ag-attention-bridge".
# On POSIX, QLocalServer uses a filesystem socket path.
SOCKET_PATH = (
    Path("ag-attention-bridge")
    if os.name == "nt"
    else get_xdg_runtime_dir() / "ag-attention-bridge.sock"
)
GLOBAL_EVENTS_LOG_PATH = get_xdg_state_dir() / "events.jsonl"
BRIDGE_LOG_PATH = get_xdg_state_dir() / "bridge.log"

# Explicit fallback disabled by default; set AG_ATTENTION_SYNTHETIC_FALLBACK=1 to enable
SYNTHETIC_FALLBACK_ENABLED: bool = os.environ.get("AG_ATTENTION_SYNTHETIC_FALLBACK") == "1"


def get_local_log_path(workspace_path: str | Path | None = None) -> Path | None:
    """Return workspace-relative log path (.agents/logs/events.jsonl) if found."""
    if workspace_path:
        root = Path(workspace_path)
    else:
        root = Path.cwd()

    agents_dir = root / ".agents"
    if agents_dir.exists():
        logs_dir = agents_dir / "logs"
        logs_dir.mkdir(mode=0o755, parents=True, exist_ok=True)
        return logs_dir / "events.jsonl"

    return None


def log_bridge_diagnostic(
    request_id: str | None = None,
    conversation_id: str | None = None,
    hook_event: str | None = None,
    tool_name: str | None = None,
    request_state: str | None = None,
    ui_action: str | None = None,
    ipc_state: str | None = None,
    hook_output: str | dict | None = None,
    exit_code: int | None = None,
) -> None:
    """Log structured diagnostic line for Phase 11 tracking."""
    import json
    import sys
    from datetime import datetime

    ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    req_str = f"[{request_id}]" if request_id else "[-]"
    conv_str = f"[{conversation_id[:8]}...]" if conversation_id else "[-]"

    parts = [ts, req_str, conv_str]
    if hook_event:
        parts.append(f"event={hook_event}")
    if tool_name:
        parts.append(f"tool={tool_name}")
    if request_state:
        parts.append(f"state={request_state}")
    if ui_action:
        parts.append(f"ui={ui_action}")
    if ipc_state:
        parts.append(f"ipc={ipc_state}")
    if hook_output is not None:
        out_str = json.dumps(hook_output) if isinstance(hook_output, dict) else str(hook_output)
        parts.append(f"output={out_str}")
    if exit_code is not None:
        parts.append(f"exit={exit_code}")

    line = " ".join(parts) + "\n"

    try:
        get_xdg_state_dir()
        with open(BRIDGE_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass

    sys.stderr.write(f"[ag-bridge] {line}")


def log_native_diagnostic(
    event: str,
    conversation_id: str | None = None,
    trajectory_id: str | None = None,
    step_index: int | None = None,
    interaction_type: str | None = None,
    selected_option_ids: list[str] | None = None,
    http_status: int | None = None,
    extra: str | None = None,
) -> None:
    """Log structured diagnostic line for native interaction lifecycle."""
    import sys
    from datetime import datetime

    ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    conv_short = conversation_id[:8] if conversation_id else "unknown"
    traj_short = trajectory_id[:8] if trajectory_id else "unknown"

    parts = [f"[{event}]", f"conv={conv_short}", f"traj={traj_short}"]
    if step_index is not None:
        parts.append(f"step={step_index}")
    if interaction_type:
        parts.append(f"type={interaction_type}")
    if selected_option_ids is not None:
        parts.append(f"options={selected_option_ids}")
    if http_status is not None:
        parts.append(f"status={http_status}")
    if extra:
        parts.append(f"extra={extra}")

    line = " ".join(parts)

    try:
        get_xdg_state_dir()
        with open(BRIDGE_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"{ts} {line}\n")
    except Exception:
        pass

    sys.stderr.write(f"[ag-native] {ts} {line}\n")
