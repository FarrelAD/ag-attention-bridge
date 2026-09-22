"""Appearance and styling configuration modal for Ag Attention Bridge."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from ag_attention_bridge.settings import (
    DEFAULT_ACCENT_COLORS,
    SUPPORTED_THEMES,
    AppearanceSettings,
    load_settings,
    save_settings,
)
from ag_attention_bridge.ui.theme import apply_theme


class AppearanceSettingsDialog(QDialog):
    """Preferences modal to customize theme preset, accent color, dialog size, and font scale."""

    settings_applied = Signal(object)  # Emits new AppearanceSettings

    def __init__(
        self,
        current_settings: AppearanceSettings | None = None,
        on_applied: Callable[[AppearanceSettings], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.settings = current_settings or load_settings()
        self._on_applied = on_applied

        self._setup_window()
        self._setup_ui()
        self._load_values()
        apply_theme(self, self.settings)

    def _setup_window(self) -> None:
        self.setWindowTitle("Appearance Settings — Ag Attention Bridge")
        self.setObjectName("AppearanceSettingsModal")
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setFixedWidth(460)

    def _setup_ui(self) -> None:
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(16, 16, 16, 16)
        outer_layout.setSpacing(14)

        # Title
        title_box = QVBoxLayout()
        title_box.setSpacing(4)
        lbl_title = QLabel("Appearance Settings", self)
        lbl_title.setObjectName("HeaderTitle")
        lbl_desc = QLabel("Customize the visual appearance, color palette, and sizing.", self)
        lbl_desc.setObjectName("HeaderSubtitle")
        title_box.addWidget(lbl_title)
        title_box.addWidget(lbl_desc)
        outer_layout.addLayout(title_box)

        # Form Container
        form_frame = QFrame(self)
        form_frame.setObjectName("ContextFrame")
        form_layout = QVBoxLayout(form_frame)
        form_layout.setContentsMargins(14, 14, 14, 14)
        form_layout.setSpacing(14)

        # 1. Theme Preset
        row_theme = QVBoxLayout()
        row_theme.setSpacing(6)
        lbl_theme = QLabel("Theme Preset", form_frame)
        lbl_theme.setStyleSheet("font-weight: 600; font-size: 13px;")
        self.combo_theme = QComboBox(form_frame)
        for theme in SUPPORTED_THEMES:
            label = {
                "midnight": "Midnight (Default Dark Slate)",
                "oled_black": "OLED Pure Black (High Contrast)",
                "nord": "Nord (Nordic Frost Palette)",
                "light": "Light (Clean Light Mode)",
            }.get(theme, theme.title())
            self.combo_theme.addItem(label, theme)
        self.combo_theme.currentIndexChanged.connect(self._on_preview_change)
        row_theme.addWidget(lbl_theme)
        row_theme.addWidget(self.combo_theme)
        form_layout.addLayout(row_theme)

        # 2. Accent Color
        row_accent = QVBoxLayout()
        row_accent.setSpacing(6)
        lbl_accent = QLabel("Accent Color", form_frame)
        lbl_accent.setStyleSheet("font-weight: 600; font-size: 13px;")
        row_accent.addWidget(lbl_accent)

        colors_layout = QHBoxLayout()
        colors_layout.setSpacing(8)
        self.accent_buttons: dict[str, QPushButton] = {}
        for name, hex_code in DEFAULT_ACCENT_COLORS.items():
            btn = QPushButton(name, form_frame)
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(
                f"QPushButton {{ background-color: #1e293b; color: {hex_code}; border: 1.5px solid {hex_code}; "
                f"border-radius: 6px; padding: 4px 8px; font-size: 11px; font-weight: bold; }}"
                f"QPushButton:checked {{ background-color: {hex_code}; color: #ffffff; }}"
            )
            btn.clicked.connect(lambda _, h=hex_code: self._set_accent_color(h))
            colors_layout.addWidget(btn)
            self.accent_buttons[hex_code] = btn
        row_accent.addLayout(colors_layout)
        form_layout.addLayout(row_accent)

        # 3. Dialog Width
        row_width = QVBoxLayout()
        row_width.setSpacing(6)
        self.lbl_width_val = QLabel(f"Dialog Width: {self.settings.dialog_width}px", form_frame)
        self.lbl_width_val.setStyleSheet("font-weight: 600; font-size: 13px;")
        self.slider_width = QSlider(Qt.Orientation.Horizontal, form_frame)
        self.slider_width.setRange(560, 960)
        self.slider_width.setSingleStep(20)
        self.slider_width.setValue(self.settings.dialog_width)
        self.slider_width.valueChanged.connect(self._on_width_changed)
        row_width.addWidget(self.lbl_width_val)
        row_width.addWidget(self.slider_width)
        form_layout.addLayout(row_width)

        # 4. Font Scale
        row_scale = QVBoxLayout()
        row_scale.setSpacing(6)
        lbl_scale = QLabel("Font & UI Scale", form_frame)
        lbl_scale.setStyleSheet("font-weight: 600; font-size: 13px;")
        self.combo_scale = QComboBox(form_frame)
        self.combo_scale.addItem("Compact (90%)", 0.90)
        self.combo_scale.addItem("Standard (100%)", 1.0)
        self.combo_scale.addItem("Comfortable (115%)", 1.15)
        self.combo_scale.addItem("Large / HiDPI (130%)", 1.30)
        self.combo_scale.currentIndexChanged.connect(self._on_preview_change)
        row_scale.addWidget(lbl_scale)
        row_scale.addWidget(self.combo_scale)
        form_layout.addLayout(row_scale)

        outer_layout.addWidget(form_frame)

        # Actions Footer
        actions_layout = QHBoxLayout()
        actions_layout.setSpacing(10)

        self.btn_reset = QPushButton("Reset Defaults", self)
        self.btn_reset.setObjectName("BtnDismiss")
        self.btn_reset.clicked.connect(self._reset_defaults)
        actions_layout.addWidget(self.btn_reset)

        actions_layout.addStretch()

        self.btn_cancel = QPushButton("Close", self)
        self.btn_cancel.setObjectName("BtnDismiss")
        self.btn_cancel.clicked.connect(self.reject)
        actions_layout.addWidget(self.btn_cancel)

        self.btn_save = QPushButton("Save & Apply", self)
        self.btn_save.setObjectName("BtnSubmit")
        self.btn_save.clicked.connect(self._save_and_apply)
        actions_layout.addWidget(self.btn_save)

        outer_layout.addLayout(actions_layout)

    def _load_values(self) -> None:
        idx = self.combo_theme.findData(self.settings.theme_preset)
        if idx >= 0:
            self.combo_theme.setCurrentIndex(idx)

        self._update_accent_buttons(self.settings.accent_color)
        self.slider_width.setValue(self.settings.dialog_width)

        for i in range(self.combo_scale.count()):
            if abs(self.combo_scale.itemData(i) - self.settings.font_scale) < 0.05:
                self.combo_scale.setCurrentIndex(i)
                break

    def _update_accent_buttons(self, selected_hex: str) -> None:
        for hex_code, btn in self.accent_buttons.items():
            btn.setChecked(hex_code.lower() == selected_hex.lower())

    def _set_accent_color(self, hex_code: str) -> None:
        self.settings.accent_color = hex_code
        self._update_accent_buttons(hex_code)
        self._on_preview_change()

    def _on_width_changed(self, val: int) -> None:
        self.lbl_width_val.setText(f"Dialog Width: {val}px")
        self.settings.dialog_width = val

    def _on_preview_change(self) -> None:
        theme = self.combo_theme.currentData()
        if theme:
            self.settings.theme_preset = theme
        scale = self.combo_scale.currentData()
        if scale:
            self.settings.font_scale = scale
        apply_theme(self, self.settings)

    def _reset_defaults(self) -> None:
        self.settings = AppearanceSettings()
        self._load_values()
        self._on_preview_change()

    def _save_and_apply(self) -> None:
        theme = self.combo_theme.currentData()
        if theme:
            self.settings.theme_preset = theme
        scale = self.combo_scale.currentData()
        if scale:
            self.settings.font_scale = scale
        self.settings.dialog_width = self.slider_width.value()
        self.settings.validate_and_clamp()

        save_settings(self.settings)
        apply_theme(self, self.settings)

        self.settings_applied.emit(self.settings)
        if self._on_applied:
            self._on_applied(self.settings)
        self.accept()
