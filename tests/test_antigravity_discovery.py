"""Unit tests for Antigravity process discovery, command line parsing, and security."""

from __future__ import annotations

import os

from ag_attention_bridge.antigravity.discovery import AntigravityDiscovery
from ag_attention_bridge.antigravity.models import AntigravityServer


def test_token_masking():
    """Verify CSRF tokens are always masked and never logged in plain text."""
    s1 = AntigravityServer(
        pid=100,
        workspace_id="ws1",
        https_port=4000,
        csrf_token="fc4fc481-1234-5678-90ab-cdef01234567",
    )
    assert s1.masked_csrf_token == "fc4f****4567"
    assert "1234-5678" not in s1.masked_csrf_token

    s_short = AntigravityServer(pid=101, workspace_id="ws2", https_port=4001, csrf_token="abcdef")
    assert s_short.masked_csrf_token == "****"

    s_empty = AntigravityServer(pid=102, workspace_id="ws3", https_port=4002, csrf_token="")
    assert s_empty.masked_csrf_token == "[EMPTY]"


def test_server_base_url():
    """Verify localhost HTTPS base URL formatting."""
    s = AntigravityServer(pid=1234, workspace_id="ws", https_port=40753, csrf_token="tok")
    assert s.base_url == "https://127.0.0.1:40753"


def test_parse_proc_cmdline(tmp_path, monkeypatch):
    """Test parsing cmdline arguments with null byte separators."""
    cmdline_content = (
        b"/path/to/language_server_linux_x64\x00"
        b"--workspace_id\x00file_home_user_project_demo\x00"
        b"--https_server_port\x0045678\x00"
        b"--csrf_token\x00secret-test-token-value\x00"
        b"--lsp_port\x0033445\x00"
        b"--extension_server_port\x0032211\x00"
    )

    proc_dir = tmp_path / "proc"
    pid_dir = proc_dir / "9999"
    pid_dir.mkdir(parents=True)
    cmdline_file = pid_dir / "cmdline"
    cmdline_file.write_bytes(cmdline_content)

    discovery = AntigravityDiscovery(proc_path=proc_dir)

    # Mock os.stat so PID ownership matches current user
    orig_stat = os.stat

    def mock_stat(path, *args, **kwargs):
        st = orig_stat(path, *args, **kwargs)
        # return same stat but ensure st_uid == current uid (or 1000 on Windows)
        uid = getattr(os, "getuid", lambda: 1000)()
        return os.stat_result(
            (
                st.st_mode,
                st.st_ino,
                st.st_dev,
                st.st_nlink,
                uid,
                st.st_gid,
                st.st_size,
                st.st_atime,
                st.st_mtime,
                st.st_ctime,
            )
        )

    monkeypatch.setattr(os, "stat", mock_stat)

    server = discovery.parse_pid_cmdline(9999)
    assert server is not None
    assert server.pid == 9999
    assert server.workspace_id == "file_home_user_project_demo"
    assert server.https_port == 45678
    assert server.csrf_token == "secret-test-token-value"
    assert server.lsp_port == 33445
    assert server.extension_server_port == 32211


def test_process_owner_security_validation(tmp_path, monkeypatch):
    """Verify processes owned by a different UID are strictly rejected."""
    proc_dir = tmp_path / "proc"
    pid_dir = proc_dir / "8888"
    pid_dir.mkdir(parents=True)
    (pid_dir / "cmdline").write_bytes(
        b"language_server_linux_x64\x00--workspace_id\x00ws1\x00--https_server_port\x0041111\x00--csrf_token\x00tok\x00"
    )

    discovery = AntigravityDiscovery(proc_path=proc_dir)

    # Force stat to report UID of 0 (root) while current user is normal user
    orig_stat = os.stat

    def mock_stat_other_user(path, *args, **kwargs):
        st = orig_stat(path, *args, **kwargs)
        other_uid = getattr(os, "getuid", lambda: 1000)() + 100
        return os.stat_result(
            (
                st.st_mode,
                st.st_ino,
                st.st_dev,
                st.st_nlink,
                other_uid,
                st.st_gid,
                st.st_size,
                st.st_atime,
                st.st_mtime,
                st.st_ctime,
            )
        )

    monkeypatch.setattr(os, "stat", mock_stat_other_user)

    # Security check must reject PID 8888
    server = discovery.parse_pid_cmdline(8888)
    assert server is None


def test_workspace_matching(tmp_path, monkeypatch):
    """Verify workspace path matches corresponding workspace_id."""
    discovery = AntigravityDiscovery()

    s1 = AntigravityServer(
        pid=1001,
        workspace_id="file_home_mashupsoat_development_ag_attention_bridge",
        https_port=40753,
        csrf_token="tok1",
        workspace_path="/home/mashupsoat/development/ag_attention_bridge",
    )
    s2 = AntigravityServer(
        pid=1002,
        workspace_id="file_home_mashupsoat_development_clones_other",
        https_port=40754,
        csrf_token="tok2",
        workspace_path="/home/mashupsoat/development/clones/other",
    )

    # Pre-populate cache
    discovery._cache = [s1, s2]
    monkeypatch.setattr(discovery, "discover_servers", lambda force=False: [s1, s2])

    matched1 = discovery.find_server_for_workspace(
        "/home/mashupsoat/development/ag_attention_bridge"
    )
    assert matched1 is not None
    assert matched1.pid == 1001

    matched2 = discovery.find_server_for_workspace("/home/mashupsoat/development/clones/other/")
    assert matched2 is not None
    assert matched2.pid == 1002

    no_match = discovery.find_server_for_workspace("/home/nonexistent/workspace")
    assert no_match is None


def test_cache_invalidation():
    """Verify cache invalidation on process termination."""
    discovery = AntigravityDiscovery()
    s = AntigravityServer(pid=999999, workspace_id="ws", https_port=4000, csrf_token="tok")
    discovery._server_cache = {s.pid: s}

    # PID 999999 is dead, so discover_servers without force still removes dead PIDs
    assert discovery.is_pid_alive(999999) is False
    servers = discovery.discover_servers(force_refresh=False)
    # The dead server must be pruned from cache
    assert not any(srv.pid == 999999 for srv in servers)
