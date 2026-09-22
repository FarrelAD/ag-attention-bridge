"""Lightweight Unix Domain Socket IPC client for hook adapter."""

from __future__ import annotations

import os
import socket
import sys
from pathlib import Path
from typing import Any

from ag_attention_bridge.config import SOCKET_PATH
from ag_attention_bridge.ipc.protocol import (
    IpcMessage,
    decode_payload,
    encode_payload,
)

# Cross-platform fallback for AF_UNIX when running under non-POSIX
AF_UNIX = getattr(socket, "AF_UNIX", socket.AF_INET)

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32

    GENERIC_READ = 0x80000000
    GENERIC_WRITE = 0x40000000
    OPEN_EXISTING = 3
    INVALID_HANDLE_VALUE = -1
    FILE_ATTRIBUTE_NORMAL = 0x80


def _to_pipe_path(name_or_path: str) -> str:
    """Normalize socket name or path to Windows Named Pipe path matching QLocalServer."""
    clean = str(name_or_path).replace("/", "\\")
    if clean.startswith("\\\\.\\pipe\\"):
        return clean
    return f"\\\\.\\pipe\\{clean}"


class IpcClient:
    """Client for synchronous communication with Ag Attention Bridge daemon."""

    def __init__(self, socket_path: str | Path = SOCKET_PATH) -> None:
        self.socket_path = str(socket_path)
        if IS_WINDOWS:
            self.pipe_path = _to_pipe_path(self.socket_path)
        else:
            self.pipe_path = ""

    def is_available(self) -> bool:
        """Check if daemon socket/pipe is present and accepting connections."""
        if IS_WINDOWS:
            # WaitNamedPipeW returns TRUE (non-zero) if an instance is available
            timeout_ms = 200
            res = kernel32.WaitNamedPipeW(self.pipe_path, timeout_ms)
            return bool(res)

        if not os.path.exists(self.socket_path):
            return False

        sock = socket.socket(AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.settimeout(0.2)
            sock.connect(self.socket_path)
            return True
        except OSError:
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
        wire_data = encode_payload(message)

        if IS_WINDOWS:
            timeout_ms = int(timeout * 1000)
            if not kernel32.WaitNamedPipeW(self.pipe_path, min(timeout_ms, 2000)):
                return None

            handle = kernel32.CreateFileW(
                self.pipe_path,
                GENERIC_READ | GENERIC_WRITE,
                0,
                None,
                OPEN_EXISTING,
                FILE_ATTRIBUTE_NORMAL,
                None,
            )
            if handle == INVALID_HANDLE_VALUE or handle == 0:
                return None

            try:
                # Write payload
                bytes_written = wintypes.DWORD(0)
                write_res = kernel32.WriteFile(
                    handle,
                    wire_data,
                    len(wire_data),
                    ctypes.byref(bytes_written),
                    None,
                )
                if not write_res:
                    return None

                # Read response loop
                buffer = bytearray()
                read_buf = ctypes.create_string_buffer(4096)
                bytes_read = wintypes.DWORD(0)
                while True:
                    ok = kernel32.ReadFile(
                        handle,
                        read_buf,
                        4096,
                        ctypes.byref(bytes_read),
                        None,
                    )
                    if not ok or bytes_read.value == 0:
                        break
                    buffer.extend(read_buf.raw[: bytes_read.value])
                    if b"\n" in buffer:
                        line = buffer.split(b"\n", 1)[0]
                        return decode_payload(line)

                if buffer:
                    return decode_payload(buffer)
                return None
            except Exception as e:
                sys.stderr.write(f"[ag-ipc-client] Pipe communication error: {e}\n")
                return None
            finally:
                kernel32.CloseHandle(handle)

        # POSIX implementation via AF_UNIX
        if not os.path.exists(self.socket_path):
            return None

        sock = socket.socket(AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.settimeout(timeout)
            sock.connect(self.socket_path)
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
        except TimeoutError:
            sys.stderr.write(f"[ag-ipc-client] Request timed out after {timeout}s\n")
            return None
        except OSError as e:
            sys.stderr.write(f"[ag-ipc-client] Connection error: {e}\n")
            return None
        finally:
            try:
                sock.close()
            except Exception:
                pass

    def send_fire_and_forget(self, message: IpcMessage | dict[str, Any]) -> bool:
        """Send a one-way notification to daemon without waiting for answer."""
        wire_data = encode_payload(message)

        if IS_WINDOWS:
            if not kernel32.WaitNamedPipeW(self.pipe_path, 500):
                return False

            handle = kernel32.CreateFileW(
                self.pipe_path,
                GENERIC_READ | GENERIC_WRITE,
                0,
                None,
                OPEN_EXISTING,
                FILE_ATTRIBUTE_NORMAL,
                None,
            )
            if handle == INVALID_HANDLE_VALUE or handle == 0:
                return False

            try:
                bytes_written = wintypes.DWORD(0)
                res = kernel32.WriteFile(
                    handle,
                    wire_data,
                    len(wire_data),
                    ctypes.byref(bytes_written),
                    None,
                )
                return bool(res)
            except Exception:
                return False
            finally:
                kernel32.CloseHandle(handle)

        if not os.path.exists(self.socket_path):
            return False

        sock = socket.socket(AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.settimeout(1.0)
            sock.connect(self.socket_path)
            sock.sendall(wire_data)
            return True
        except Exception:
            return False
        finally:
            try:
                sock.close()
            except Exception:
                pass
