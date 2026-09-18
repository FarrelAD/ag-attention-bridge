"""Discovery module for dynamically finding Antigravity Language Server processes."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from ag_attention_bridge.antigravity.errors import ServerNotFoundError
from ag_attention_bridge.antigravity.models import AntigravityServer

logger = logging.getLogger("ag_attention_bridge.antigravity.discovery")


def workspace_id_to_path(workspace_id: str) -> str | None:
    """Convert a file_ prefix workspace_id to an absolute path if applicable."""
    if workspace_id.startswith("file_"):
        # e.g. file_home_mashupsoat_development_ag_attention_bridge
        stripped = workspace_id[len("file_"):]
        candidate = "/" + stripped.replace("_", "/")
        # Also try direct replacement of first segments if path exists
        if os.path.exists(candidate):
            return candidate
        # Fallback: check with hyphens (e.g. ag-attention-bridge)
        hyphen_candidate = candidate.replace("/ag/attention/bridge", "/ag-attention-bridge")
        if os.path.exists(hyphen_candidate):
            return hyphen_candidate
        return candidate
    return None


def path_to_workspace_id_prefix(path_str: str | Path) -> str:
    """Generate expected workspace_id prefix for a filesystem path."""
    clean = str(Path(path_str).resolve()).lstrip("/").replace("/", "_").replace("-", "_")
    return f"file_{clean}"


def parse_cmdline_args(cmdline_bytes: bytes) -> dict[str, str]:
    """Parse null-byte delimited cmdline arguments into a dictionary."""
    tokens = [t.decode("utf-8", errors="replace") for t in cmdline_bytes.split(b"\0") if t]
    args: dict[str, str] = {}
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok.startswith("--"):
            key = tok[2:]
            if i + 1 < len(tokens) and not tokens[i + 1].startswith("--"):
                args[key] = tokens[i + 1]
                i += 2
            else:
                args[key] = "true"
                i += 1
        else:
            i += 1
    return args


class AntigravityDiscovery:
    """Discovers and caches running Antigravity Language Server instances."""

    def __init__(self, proc_dir: str | Path = "/proc", proc_path: str | Path | None = None) -> None:
        self.proc_dir = Path(proc_path if proc_path is not None else proc_dir)
        self._server_cache: dict[int, AntigravityServer] = {}

    def is_pid_alive(self, pid: int) -> bool:
        """Check if process is still running and owned by current user."""
        try:
            os.kill(pid, 0)
            return True
        except (ProcessLookupError, PermissionError):
            return False

    def invalidate_cache(self) -> None:
        """Clear the cached servers."""
        self._server_cache.clear()

    def parse_pid_cmdline(self, pid: int) -> AntigravityServer | None:
        """Parse language server metadata for a given PID from proc filesystem."""
        proc_path = self.proc_dir / str(pid)
        try:
            # Security: Validate process owner is current user
            stat_info = proc_path.stat()
            if stat_info.st_uid != os.getuid():
                logger.debug("Rejecting PID %d: Process owner UID %d does not match current UID %d", pid, stat_info.st_uid, os.getuid())
                return None

            cmdline_path = proc_path / "cmdline"
            with open(cmdline_path, "rb") as f:
                cmdline_data = f.read()

            if b"language_server_linux_x64" not in cmdline_data:
                return None

            args = parse_cmdline_args(cmdline_data)

            # Language servers must have csrf_token; workspace_id defaults to 'global' if omitted
            csrf_token = args.get("csrf_token")
            if not csrf_token:
                return None

            workspace_id = args.get("workspace_id", "global")

            https_port_str = args.get("https_server_port")
            if https_port_str:
                try:
                    https_port = int(https_port_str)
                except ValueError:
                    https_port = None
            else:
                https_port = self._find_https_port_for_pid(pid, csrf_token)

            if not https_port:
                return None

            lsp_port = int(args["lsp_port"]) if "lsp_port" in args and args["lsp_port"].isdigit() else None
            ext_port = int(args["extension_server_port"]) if "extension_server_port" in args and args["extension_server_port"].isdigit() else None
            ws_path = workspace_id_to_path(workspace_id)

            server = AntigravityServer(
                pid=pid,
                workspace_id=workspace_id,
                https_port=https_port,
                csrf_token=csrf_token,
                lsp_port=lsp_port,
                extension_server_port=ext_port,
                workspace_path=ws_path,
            )
            return server
        except (FileNotFoundError, ProcessLookupError, PermissionError, ValueError, OSError) as e:
            logger.debug("Failed reading cmdline for PID %d: %s", pid, e)
            return None

    def _find_https_port_for_pid(self, pid: int, csrf_token: str) -> int | None:
        """Discover dynamic HTTPS ConnectRPC listening port from /proc/net/tcp."""
        import ssl
        import urllib.request

        proc_fd_dir = self.proc_dir / str(pid) / "fd"
        if not proc_fd_dir.exists():
            return None

        socket_inodes = set()
        try:
            for fd_entry in proc_fd_dir.iterdir():
                try:
                    target = os.readlink(str(fd_entry))
                    if target.startswith("socket:["):
                        socket_inodes.add(int(target[8:-1]))
                except (OSError, ValueError):
                    pass
        except (OSError, PermissionError):
            return None

        if not socket_inodes:
            return None

        candidate_ports = []
        for net_file_name in ("tcp", "tcp6"):
            net_path = Path("/proc/net") / net_file_name
            if not net_path.exists():
                continue
            try:
                with open(net_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()[1:]
                for line in lines:
                    parts = line.strip().split()
                    if len(parts) >= 10:
                        local_addr = parts[1]
                        st = parts[3]
                        inode = int(parts[9])
                        if st == "0A" and inode in socket_inodes:  # 0A is TCP_LISTEN
                            port_hex = local_addr.split(":")[1]
                            candidate_ports.append(int(port_hex, 16))
            except (OSError, ValueError):
                pass

        if not candidate_ports:
            return None

        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        for port in candidate_ports:
            url = f"https://127.0.0.1:{port}/exa.language_server_pb.LanguageServerService/Heartbeat"
            req = urllib.request.Request(
                url,
                data=b"{}",
                headers={"Content-Type": "application/json", "x-codeium-csrf-token": csrf_token},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, context=ctx, timeout=0.3) as resp:
                    if resp.status == 200:
                        return port
            except Exception:
                continue

        return None

    def discover_servers(self, force_refresh: bool = False) -> list[AntigravityServer]:
        """Scan /proc for running language_server_linux_x64 processes owned by user."""
        if not force_refresh and self._server_cache:
            # Validate existing cache
            valid_servers = [s for s in self._server_cache.values() if self.is_pid_alive(s.pid)]
            if len(valid_servers) == len(self._server_cache):
                return valid_servers
            self._server_cache = {s.pid: s for s in valid_servers}

        servers: list[AntigravityServer] = []

        if not self.proc_dir.exists():
            return servers

        try:
            pids = [
                int(p.name) for p in self.proc_dir.iterdir()
                if p.is_dir() and p.name.isdigit()
            ]
        except (PermissionError, OSError):
            return servers

        for pid in pids:
            server = self.parse_pid_cmdline(pid)
            if server:
                servers.append(server)
                self._server_cache[pid] = server
                logger.debug("Discovered Antigravity Server: PID %d, Port %d, Token %s", pid, server.https_port, server.masked_csrf_token)

        return servers

    def find_server_for_workspace(self, workspace_path: str | Path) -> AntigravityServer | None:
        """Find the language server responsible for a specific workspace directory."""
        clean_path = str(Path(workspace_path).resolve())
        expected_prefix = path_to_workspace_id_prefix(clean_path)

        servers = self.discover_servers()
        for server in servers:
            # Check direct path match
            if server.workspace_path and os.path.realpath(server.workspace_path) == clean_path:
                return server
            # Check workspace_id prefix match
            if server.workspace_id.startswith(expected_prefix) or expected_prefix.startswith(server.workspace_id):
                return server
            # Check name fuzzy match
            if Path(clean_path).name.replace("-", "_") in server.workspace_id:
                return server

        # If only one workspace server is active, return it as the default
        if len(servers) == 1:
            return servers[0]

        return None
