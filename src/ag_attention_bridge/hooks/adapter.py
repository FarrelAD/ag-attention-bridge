"""Lightweight Antigravity Hook Adapter and Observation Engine.

Executes within milliseconds (<15ms) using Python standard library only (no Qt).
Captures raw hook payloads, records microsecond-precision observation logs,
and returns valid Antigravity hook responses on stdout.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    import fcntl
except ImportError:
    fcntl = None  # type: ignore[assignment]

from ag_attention_bridge.config import (
    GLOBAL_EVENTS_LOG_PATH,
    get_local_log_path,
    get_xdg_runtime_dir,
    get_xdg_state_dir,
    log_bridge_diagnostic,
)
from ag_attention_bridge.ipc.client import IpcClient
from ag_attention_bridge.ipc.protocol import IpcMessage, MessageType


def detect_event_type(payload: dict[str, Any], hint: str | None = None) -> str:
    """Determine the hook event type from CLI hint or payload structure."""
    if hint:
        return hint

    if "toolCall" in payload:
        return "PreToolUse"
    if "terminationReason" in payload:
        return "Stop"
    if "invocationNum" in payload:
        return "Invocation"
    if "stepIdx" in payload and "toolCall" not in payload:
        return "PostToolUse"

    return "Unknown"


def format_observation_record(
    event_type: str,
    raw_payload: dict[str, Any],
    response: dict[str, Any],
) -> dict[str, Any]:
    """Build a structured observation record with microsecond timestamp."""
    now = datetime.now(UTC).isoformat()
    return {
        "timestamp": now,
        "pid": os.getpid(),
        "event_type": event_type,
        "conversation_id": raw_payload.get("conversationId"),
        "workspace_paths": raw_payload.get("workspacePaths", []),
        "transcript_path": raw_payload.get("transcriptPath"),
        "model_name": raw_payload.get("modelName"),
        "payload": raw_payload,
        "response": response,
    }


def write_observation_log(record: dict[str, Any]) -> None:
    """Append the observation record to both global and workspace-local log files."""
    line = json.dumps(record, separators=(",", ":")) + "\n"

    # 1. Global state log
    try:
        get_xdg_state_dir()
        with open(GLOBAL_EVENTS_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception as e:
        sys.stderr.write(f"[ag-hook-adapter] Error writing global log: {e}\n")

    # 2. Local workspace log (.agents/logs/events.jsonl)
    try:
        workspace_paths = record.get("workspace_paths") or []
        primary_workspace = workspace_paths[0] if workspace_paths else None
        local_path = get_local_log_path(primary_workspace)
        if local_path:
            with open(local_path, "a", encoding="utf-8") as f:
                f.write(line)
    except Exception as e:
        sys.stderr.write(f"[ag-hook-adapter] Error writing local log: {e}\n")


def generate_default_response(
    event_type: str, payload: dict[str, Any], reason_suffix: str = ""
) -> dict[str, Any]:
    """Generate default compliant Antigravity hook response."""
    if event_type == "PreToolUse":
        tool_name = payload.get("toolCall", {}).get("name", "")
        suffix = f" ({reason_suffix})" if reason_suffix else ""
        if tool_name in ("ask_question", "ask_permission") or not SYNTHETIC_FALLBACK_ENABLED:
            return {
                "decision": "allow",
                "reason": "Ag Attention Bridge observation hook; native interaction will resolve externally.",
            }
        return {
            "decision": "ask",
            "reason": f"Ag Attention Bridge: {tool_name}{suffix}",
        }

    # PostToolUse, PreInvocation, PostInvocation, Stop
    return {}


def ensure_daemon_running(client: IpcClient, timeout: float = 3.0) -> bool:
    """If daemon is not running, spawn it safely in the background and wait for socket."""
    if client.is_available():
        return True

    if os.environ.get("AG_ATTENTION_NO_AUTOSTART") == "1":
        return False

    # Prevent concurrent hook adapters from racing to spawn multiple daemons
    spawn_lock_path = get_xdg_runtime_dir() / "ag-spawn.lock"
    lock_fd = None
    should_spawn = False
    if fcntl is not None:
        try:
            lock_fd = os.open(str(spawn_lock_path), os.O_CREAT | os.O_RDWR, 0o600)
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)  # type: ignore[attr-defined]
            should_spawn = True
        except (BlockingIOError, OSError):
            # Another process is currently spawning the daemon! Just wait for socket.
            should_spawn = False
    else:
        should_spawn = True

    if should_spawn:
        repo_root = Path(__file__).resolve().parent.parent.parent.parent
        venv_bin = repo_root / ".venv" / "bin" / "ag-attention-bridge"
        local_bin = Path.home() / ".local" / "bin" / "ag-attention-bridge"

        cmd: list[str] = []
        if venv_bin.exists() and os.access(venv_bin, os.X_OK):
            cmd = [str(venv_bin)]
        elif local_bin.exists() and os.access(local_bin, os.X_OK):
            cmd = [str(local_bin)]
        else:
            cmd = [sys.executable, "-m", "ag_attention_bridge.app"]

        try:
            sys.stderr.write(f"[ag-hook-adapter] Auto-starting daemon: {' '.join(cmd)}\n")
            subprocess.Popen(
                cmd,
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
            )
        except Exception as e:
            sys.stderr.write(f"[ag-hook-adapter] Failed to auto-start daemon: {e}\n")

    # Wait for socket to become available
    start_time = time.perf_counter()
    while time.perf_counter() - start_time < timeout:
        if client.is_available():
            if lock_fd is not None:
                try:
                    if fcntl is not None:
                        fcntl.flock(lock_fd, fcntl.LOCK_UN)  # type: ignore[attr-defined]
                    os.close(lock_fd)
                except Exception:
                    pass
            return True
        time.sleep(0.05)

    if lock_fd is not None:
        try:
            if fcntl is not None:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)  # type: ignore[attr-defined]
            os.close(lock_fd)
        except Exception:
            pass

    return False


SYNTHETIC_FALLBACK_ENABLED = os.environ.get("AG_ATTENTION_SYNTHETIC_FALLBACK") == "1"


def handle_hook(
    raw_input: str,
    event_hint: str | None = None,
    ipc_client: IpcClient | None = None,
    auto_start: bool = True,
) -> tuple[dict[str, Any], int]:
    """Core hook handler logic: parse stdin, auto-start daemon if needed, route via IPC, log observation."""
    if not raw_input.strip():
        sys.stderr.write("[ag-hook-adapter] Warning: Empty stdin received\n")
        return {}, 0

    try:
        payload = json.loads(raw_input)
    except Exception as e:
        sys.stderr.write(f"[ag-hook-adapter] Error parsing JSON payload: {e}\n")
        return {}, 0

    event_type = detect_event_type(payload, event_hint)
    client = ipc_client if ipc_client is not None else IpcClient()
    conv_id = payload.get("conversationId", "")

    # Attempt to auto-start daemon on decision-requiring or invocation events
    if auto_start and event_type in ("PreToolUse", "PreInvocation", "PostInvocation"):
        ensure_daemon_running(client)

    response: dict[str, Any] = {}

    if event_type == "PreToolUse":
        tool_call = payload.get("toolCall", {})
        tool_name = tool_call.get("name", "")

        short_conv = conv_id[:8] if conv_id else "unknown"
        sys.stderr.write(f"[HOOK_RECEIVED] conversationId={short_conv} tool={tool_name}\n")

        is_observation_tool = tool_name in ("ask_question", "ask_permission") or not tool_name

        if not SYNTHETIC_FALLBACK_ENABLED and is_observation_tool:
            # Native Antigravity Interaction Flow (Primary):
            # 1. Notify Ag Attention Bridge daemon with conversation/cascade context.
            # 2. Return decision: allow so Language Server executes native tool and enters WAITING.
            if client.is_available():
                notify_payload = dict(payload)
                notify_payload["wait_for_response"] = False
                msg = IpcMessage(
                    type=MessageType.SUBMIT_REQUEST,
                    conversation_id=conv_id,
                    payload=notify_payload,
                )
                try:
                    client.send_and_wait(msg, timeout=2.0)
                except Exception as e:
                    sys.stderr.write(f"[ag-hook-adapter] Non-fatal notification error: {e}\n")

            response = {
                "decision": "allow",
                "reason": "Ag Attention Bridge observation hook; native interaction will resolve externally.",
            }
            log_bridge_diagnostic(
                conversation_id=conv_id,
                hook_event="PreToolUse",
                tool_name=tool_name,
                ipc_state="native_trigger_notified",
                hook_output=response,
                exit_code=0,
            )
            record = format_observation_record(event_type, payload, response)
            write_observation_log(record)
            return response, 0

        # Legacy Synthetic Fallback Path (enabled ONLY when AG_ATTENTION_SYNTHETIC_FALLBACK=1)
        if not SYNTHETIC_FALLBACK_ENABLED:
            return generate_default_response(event_type, payload), 0

        if not client.is_available():
            response = generate_default_response(event_type, payload, "Fallback: daemon offline")
        else:
            notify_payload = dict(payload)
            notify_payload["wait_for_response"] = True
            msg = IpcMessage(
                type=MessageType.SUBMIT_REQUEST,
                conversation_id=conv_id,
                payload=notify_payload,
            )
            ipc_resp = client.send_and_wait(
                msg, timeout=float(os.environ.get("AG_ATTENTION_TIMEOUT", "3600.0"))
            )
            if ipc_resp and ipc_resp.get("status") == "ok":
                data = ipc_resp.get("data", {})
                if "decision" in data:
                    valid_keys = {"decision", "reason", "permissionOverrides", "overwrite"}
                    response = {k: v for k, v in data.items() if k in valid_keys}
                else:
                    response = generate_default_response(event_type, payload, "Daemon acknowledged")
            else:
                sys.stderr.write(
                    "[ag-hook-adapter] Daemon response timed out; falling back to IDE\n"
                )
                response = generate_default_response(
                    event_type, payload, "Fallback: daemon timeout"
                )

        log_bridge_diagnostic(
            conversation_id=conv_id,
            hook_event="PreToolUse",
            tool_name=tool_name,
            ipc_state="completed",
            hook_output=response,
            exit_code=0,
        )

    elif event_type == "PreInvocation":
        if not SYNTHETIC_FALLBACK_ENABLED:
            # Native interaction: do NOT inject synthetic userMessage turns
            response = {}
        elif client.is_available():
            msg = IpcMessage(
                type=MessageType.GET_PENDING_INJECTION,
                conversation_id=conv_id,
                payload=payload,
            )
            ipc_resp = client.send_and_wait(msg, timeout=10.0)
            if ipc_resp and ipc_resp.get("status") == "ok":
                data = ipc_resp.get("data", {})
                if data.get("has_injection") and "injectSteps" in data:
                    response = {"injectSteps": data["injectSteps"]}
                    log_bridge_diagnostic(
                        conversation_id=conv_id,
                        hook_event="PreInvocation",
                        ipc_state="injectSteps_emitted",
                        hook_output=response,
                        exit_code=0,
                    )
                else:
                    response = {}
            else:
                response = {}
        else:
            response = {}

    elif event_type == "Stop":
        if not SYNTHETIC_FALLBACK_ENABLED:
            response = {}
        elif client.is_available():
            msg = IpcMessage(
                type=MessageType.CHECK_STOP,
                conversation_id=conv_id,
                payload=payload,
            )
            ipc_resp = client.send_and_wait(msg, timeout=10.0)
            if ipc_resp and ipc_resp.get("status") == "ok":
                data = ipc_resp.get("data", {})
                if data.get("decision") == "continue":
                    response = {
                        "decision": "continue",
                        "reason": data.get(
                            "reason",
                            "An external user response from Ag Attention Bridge is pending. Continue execution so it can be injected.",
                        ),
                    }
                    log_bridge_diagnostic(
                        conversation_id=conv_id,
                        hook_event="Stop",
                        ipc_state="continued",
                        hook_output=response,
                        exit_code=0,
                    )
                else:
                    response = {}
            else:
                response = {}
        else:
            response = {}

    elif event_type == "PostInvocation":
        if client.is_available():
            notify_payload = dict(payload)
            msg = IpcMessage(
                type=MessageType.CHECK_WAITING,
                conversation_id=conv_id,
                payload=notify_payload,
            )
            client.send_fire_and_forget(msg)
        response = {}

    else:
        # Non-blocking lifecycle notifications (PostToolUse, etc.)
        if client.is_available():
            notify_msg = IpcMessage(
                type=MessageType.NOTIFY_EVENT,
                conversation_id=conv_id,
                payload=payload,
            )
            client.send_fire_and_forget(notify_msg)
        response = generate_default_response(event_type, payload)

    record = format_observation_record(event_type, payload, response)
    write_observation_log(record)

    return response, 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ag Attention Bridge Hook Adapter")
    parser.add_argument(
        "--event",
        type=str,
        default=None,
        help="Explicit hook event type hint (PreToolUse, PreInvocation, PostInvocation, Stop)",
    )
    args = parser.parse_args(argv)

    try:
        raw_input = sys.stdin.read()
    except Exception as e:
        sys.stderr.write(f"[ag-hook-adapter] Error reading stdin: {e}\n")
        sys.stdout.write("{}\n")
        return 0

    response, code = handle_hook(raw_input, args.event)

    # CRITICAL: sys.stdout must ONLY contain valid JSON.
    sys.stdout.write(json.dumps(response) + "\n")
    sys.stdout.flush()
    return code


if __name__ == "__main__":
    sys.exit(main())
