"""System tray icon and badge rendering for Ag Attention Bridge."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QPointF, QRectF, Qt, QUrl
from PySide6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QDesktopServices,
    QFont,
    QIcon,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from ag_attention_bridge.config import GLOBAL_EVENTS_LOG_PATH, get_xdg_state_dir

ASSET_ICON_PATH = Path(__file__).parent / "assets" / "icon.svg"


def render_base_icon(size: int = 64) -> QPixmap:
    """Render base application icon using SVG asset or procedural fallback."""
    if ASSET_ICON_PATH.exists():
        icon = QIcon(str(ASSET_ICON_PATH))
        pixmap = icon.pixmap(size, size)
        if not pixmap.isNull():
            return pixmap

    # Procedural fallback
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Dark rounded background
    painter.setBrush(QBrush(QColor("#0f172a")))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(QRectF(4, 4, size - 8, size - 8), 14, 14)

    # Bridge arch
    pen = QPen(QColor("#38bdf8"), 4.5)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawArc(QRectF(16, 20, size - 32, size - 32), 0, 180 * 16)

    # Attention point
    painter.setBrush(QBrush(QColor("#f59e0b")))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(QPointF(size / 2, 22), 3.5, 3.5)

    painter.end()
    return pixmap


def create_badged_icon(count: int = 0, size: int = 64) -> QIcon:
    """Generate a QIcon with an optional numeric badge in the top-right corner."""
    pixmap = render_base_icon(size)

    if count > 0:
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        badge_text = "99+" if count > 99 else str(count)

        # Calculate badge dimensions
        font_size = 11 if len(badge_text) <= 2 else 9
        font = QFont("sans-serif", font_size, QFont.Weight.Bold)
        painter.setFont(font)

        badge_w = 22 if len(badge_text) <= 2 else 28
        badge_h = 22
        badge_x = size - badge_w - 2
        badge_y = 2

        badge_rect = QRectF(badge_x, badge_y, badge_w, badge_h)

        # Badge shadow/border for dark/light contrast
        painter.setBrush(QBrush(QColor(0, 0, 0, 180)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(badge_rect.adjusted(-1, -1, 1, 1), 11, 11)

        # Badge pill (vibrant attention red/coral)
        painter.setBrush(QBrush(QColor("#ef4444")))
        painter.setPen(QPen(QColor("#ffffff"), 1.5))
        painter.drawRoundedRect(badge_rect, 11, 11)

        # Badge text
        painter.setPen(QColor("#ffffff"))
        painter.drawText(
            badge_rect,
            int(Qt.AlignmentFlag.AlignCenter),
            badge_text,
        )

        painter.end()

    return QIcon(pixmap)


class AttentionTrayIcon(QSystemTrayIcon):
    """System tray icon manager for Ag Attention Bridge."""

    def __init__(
        self,
        on_open_pending: Callable[[], None] | None = None,
        on_toggle_current: Callable[[], None] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._pending_count = 0
        self._on_open_pending = on_open_pending
        self._on_toggle_current = on_toggle_current

        self._menu = QMenu()
        self._setup_menu()
        self.setContextMenu(self._menu)

        self.update_badge(0)

        self.activated.connect(self._on_activated)

    def _setup_menu(self) -> None:
        self.action_pending = QAction("Open Pending Requests (0)", self)
        self.action_pending.triggered.connect(self._handle_open_pending)
        self._menu.addAction(self.action_pending)

        self.action_toggle = QAction("Show/Hide Current Request", self)
        self.action_toggle.triggered.connect(self._handle_toggle_current)
        self._menu.addAction(self.action_toggle)

        self._menu.addSeparator()

        self.action_logs = QAction("Open Logs", self)
        self.action_logs.triggered.connect(self._open_logs)
        self._menu.addAction(self.action_logs)

        self._menu.addSeparator()

        self.action_quit = QAction("Quit Ag Attention Bridge", self)
        self.action_quit.triggered.connect(self._quit)
        self._menu.addAction(self.action_quit)

    def update_badge(self, count: int) -> None:
        """Update the icon with the given pending request count."""
        self._pending_count = max(0, count)
        self.setIcon(create_badged_icon(self._pending_count))

        if self._pending_count > 0:
            tip = f"Ag Attention Bridge ({self._pending_count} pending)"
        else:
            tip = "Ag Attention Bridge (Idle)"
        self.setToolTip(tip)

        if hasattr(self, "action_pending"):
            self.action_pending.setText(
                f"Open Pending Requests ({self._pending_count})"
            )

    @property
    def pending_count(self) -> int:
        return self._pending_count

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:  # Left click
            if self._on_open_pending:
                self._on_open_pending()
            elif self._on_toggle_current:
                self._on_toggle_current()

    def _handle_open_pending(self) -> None:
        if self._on_open_pending:
            self._on_open_pending()

    def _handle_toggle_current(self) -> None:
        if self._on_toggle_current:
            self._on_toggle_current()

    def _open_logs(self) -> None:
        state_dir = get_xdg_state_dir()
        if GLOBAL_EVENTS_LOG_PATH.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(GLOBAL_EVENTS_LOG_PATH)))
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(state_dir)))

    def _quit(self) -> None:
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app:
            app.quit()
