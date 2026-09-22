"""Process watcher for monitoring Antigravity IDE lifecycle."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

logger = logging.getLogger("ag_attention_bridge.watcher")


def is_antigravity_running(process_name: str = "antigravity") -> bool:
    """Check if any Antigravity IDE/CLI process is currently running."""
    import sys

    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        TH32CS_SNAPPROCESS = 0x00000002

        class PROCESSENTRY32W(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_void_p),
                ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD),
                ("szExeFile", ctypes.c_wchar * 260),
            ]

        kernel32 = ctypes.windll.kernel32
        snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if snapshot == -1 or snapshot == 0:
            return True  # Fail-safe

        try:
            entry = PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
            success = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
            search_term = process_name.lower()
            targets = (
                (search_term, "antigravity", "agy", "language_server")
                if search_term == "antigravity"
                else (search_term,)
            )
            while success:
                exe = entry.szExeFile.lower()
                if any(t in exe for t in targets):
                    return True
                success = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
            return False
        finally:
            kernel32.CloseHandle(snapshot)

    proc_root = Path("/proc")
    if not proc_root.exists():
        return True  # Fail-safe: if /proc not accessible, assume running

    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            # Check comm first (fastest)
            comm_file = entry / "comm"
            if comm_file.exists():
                comm = comm_file.read_text(encoding="utf-8", errors="ignore").strip()
                if process_name in comm or "agy" in comm:
                    return True

            # Check cmdline as fallback
            cmdline_file = entry / "cmdline"
            if cmdline_file.exists():
                cmdline = (
                    cmdline_file.read_bytes()
                    .replace(b"\x00", b" ")
                    .decode("utf-8", errors="ignore")
                )
                if process_name in cmdline or "agy" in cmdline:
                    return True
        except (PermissionError, FileNotFoundError, ProcessLookupError):
            continue

    return False


class AntigravityProcessWatcher(QObject):
    """Monitors running Antigravity processes and signals when IDE terminates."""

    antigravity_exited = Signal()

    def __init__(
        self,
        check_interval_ms: int = 10000,
        max_missing_count: int = 2,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.check_interval_ms = check_interval_ms
        self.max_missing_count = max_missing_count
        self._missing_streak = 0

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._check_process)

    def start(self) -> None:
        """Start the periodic process monitor."""
        self._missing_streak = 0
        self._timer.start(self.check_interval_ms)
        logger.info(
            "Antigravity process watcher started (interval: %dms, threshold: %d ticks)",
            self.check_interval_ms,
            self.max_missing_count,
        )

    def stop(self) -> None:
        """Stop the periodic process monitor."""
        self._timer.stop()

    def _check_process(self) -> None:
        running = is_antigravity_running()
        if running:
            if self._missing_streak > 0:
                logger.debug("Antigravity process re-detected. Resetting streak.")
            self._missing_streak = 0
        else:
            self._missing_streak += 1
            logger.info(
                "Antigravity process not detected (streak %d/%d)",
                self._missing_streak,
                self.max_missing_count,
            )
            if self._missing_streak >= self.max_missing_count:
                logger.info("Antigravity IDE confirmed terminated. Triggering auto-shutdown.")
                self._timer.stop()
                self.antigravity_exited.emit()
