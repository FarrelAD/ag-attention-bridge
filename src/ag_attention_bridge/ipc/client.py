"""Lightweight Unix Domain Socket IPC client for hook adapter."""

from __future__ import annotations

import os
from pathlib import Path
import socket
import sys
import time
from typing import Any

from ag_attention_bridge.config import SOCKET_PATH
from ag_attention_bridge.ipc.protocol import (
    IpcMessage,
    IpcResponse,
    decode_payload,
    encode_payload,
)


class IpcClient:
    """Client for synchronous communication with Ag Attention Bridge daemon."""

    def __init__(self, socket_path: str | Path = SOCKET_PATH) -> None:
        self.socket_path = str(socket_path)

    def is_available(self) -> bool:
        """Check if daemon socket is present and accepting connections."""
        if not os.path.exists(self.socket_path):
            return False

        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.settimeout(0.2)
            sock.connect(self.socket_path)
            return True
        except (socket.error, OSError):
            return False
        finally:
            try:
                sock.close()
            except Exception:
                pass

    def send_and_wait(
        self,
        message: IpcMessage | dict[str, Any],
        timeout: float = 300.0,
    ) -> dict[str, Any] | None:
        """Send a message to the daemon and block until response received or timeout.

        Returns decoded response dictionary, or None if daemon unavailable or timeout.
        """
        if not os.path.exists(self.socket_path):
            return None

        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.settimeout(timeout)
            sock.connect(self.socket_path)

            wire_data = encode_payload(message)
            sock.sendall(wire_data)

            # Read response line
            buffer = bytearray()
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                buffer.extend(chunk)
                if b"\n" in buffer:
                    line = buffer.split(b"\n", 1)[0]
                    return decode_payload(line)

            if buffer:
                return decode_payload(buffer)

            return None
        except socket.timeout:
            sys.stderr.write(f"[ag-ipc-client] Request timed out after {timeout}s\n")
            return None
        except (socket.error, OSError) as e:
            sys.stderr.write(f"[ag-ipc-client] Connection error: {e}\n")
            return None
        finally:
            try:
                sock.close()
            except Exception:
                pass

    def send_fire_and_forget(self, message: IpcMessage | dict[str, Any]) -> bool:
        """Send a one-way notification to daemon without waiting for answer."""
        if not os.path.exists(self.socket_path):
            return False

        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.settimeout(1.0)
            sock.connect(self.socket_path)
            sock.sendall(encode_payload(message))
            return True
        except Exception:
            return False
        finally:
            try:
                sock.close()
            except Exception:
                pass
