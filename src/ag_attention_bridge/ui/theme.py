"""Premium visual styling and dynamic QSS stylesheets for Ag Attention Bridge."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ag_attention_bridge.settings import AppearanceSettings


@dataclass
class ThemePalette:
    """Color palette tokens for application theming."""

    name: str
    bg_window: str
    bg_card: str
    bg_card_nested: str
    bg_card_hover: str
    border: str
    border_focus: str
    border_active: str
    text_primary: str
    text_secondary: str
    text_muted: str
    success_bg: str = "#10b981"
    success_hover: str = "#059669"
    danger_bg: str = "#f43f5e"
    danger_hover: str = "#e11d48"
    btn_secondary_bg: str = "#1e293b"
    btn_secondary_hover: str = "#334155"
    btn_secondary_border: str = "#475569"
    monospace_bg: str = "#030712"
    option_checked_bg: str = "#1e3a5f"


# Preset Palettes
PALETTE_MIDNIGHT = ThemePalette(
    name="midnight",
    bg_window="#090d16",
    bg_card="#0f172a",
    bg_card_nested="#1e293b",
    bg_card_hover="#243247",
    border="#334155",
    border_focus="#38bdf8",
    border_active="#60a5fa",
    text_primary="#f8fafc",
    text_secondary="#94a3b8",
    text_muted="#64748b",
    btn_secondary_bg="#1e293b",
    btn_secondary_hover="#334155",
    btn_secondary_border="#475569",
    monospace_bg="#030712",
    option_checked_bg="#1e3a5f",
)

PALETTE_OLED_BLACK = ThemePalette(
    name="oled_black",
    bg_window="#000000",
    bg_card="#0a0a0a",
    bg_card_nested="#141414",
    bg_card_hover="#222222",
    border="#27272a",
    border_focus="#38bdf8",
    border_active="#60a5fa",
    text_primary="#ffffff",
    text_secondary="#a1a1aa",
    text_muted="#71717a",
    btn_secondary_bg="#18181b",
    btn_secondary_hover="#27272a",
    btn_secondary_border="#3f3f46",
    monospace_bg="#09090b",
    option_checked_bg="#18283d",
)

PALETTE_NORD = ThemePalette(
    name="nord",
    bg_window="#242933",
    bg_card="#2e3440",
    bg_card_nested="#3b4252",
    bg_card_hover="#434c5e",
    border="#4c566a",
    border_focus="#88c0d0",
    border_active="#81a1c1",
    text_primary="#eceff4",
    text_secondary="#d8dee9",
    text_muted="#e5e9f0",
    success_bg="#a3be8c",
    success_hover="#8fbcbb",
    danger_bg="#bf616a",
    danger_hover="#d08770",
    btn_secondary_bg="#3b4252",
    btn_secondary_hover="#434c5e",
    btn_secondary_border="#4c566a",
    monospace_bg="#1e222a",
    option_checked_bg="#384d63",
)

PALETTE_LIGHT = ThemePalette(
    name="light",
    bg_window="#f8fafc",
    bg_card="#ffffff",
    bg_card_nested="#f1f5f9",
    bg_card_hover="#e2e8f0",
    border="#cbd5e1",
    border_focus="#0284c7",
    border_active="#0ea5e9",
    text_primary="#0f172a",
    text_secondary="#475569",
    text_muted="#64748b",
    btn_secondary_bg="#f1f5f9",
    btn_secondary_hover="#e2e8f0",
    btn_secondary_border="#cbd5e1",
    monospace_bg="#f1f5f9",
    option_checked_bg="#e0f2fe",
)

THEME_PALETTES: dict[str, ThemePalette] = {
    "midnight": PALETTE_MIDNIGHT,
    "oled_black": PALETTE_OLED_BLACK,
    "nord": PALETTE_NORD,
    "light": PALETTE_LIGHT,
}

# Backward compatible module-level color constants for static references
COLOR_BG_WINDOW = PALETTE_MIDNIGHT.bg_window
COLOR_BG_CARD = PALETTE_MIDNIGHT.bg_card
COLOR_BG_CARD_NESTED = PALETTE_MIDNIGHT.bg_card_nested
COLOR_BG_CARD_HOVER = PALETTE_MIDNIGHT.bg_card_hover
COLOR_BORDER = PALETTE_MIDNIGHT.border
COLOR_BORDER_FOCUS = PALETTE_MIDNIGHT.border_focus
COLOR_BORDER_ACTIVE = PALETTE_MIDNIGHT.border_active
COLOR_TEXT_PRIMARY = PALETTE_MIDNIGHT.text_primary
COLOR_TEXT_SECONDARY = PALETTE_MIDNIGHT.text_secondary
COLOR_TEXT_MUTED = PALETTE_MIDNIGHT.text_muted
COLOR_ACCENT_PRIMARY = "#38bdf8"
COLOR_ACCENT_HOVER = "#0ea5e9"
COLOR_ACCENT_TEXT = "#0c4a6e"
COLOR_SUCCESS_BG = PALETTE_MIDNIGHT.success_bg
COLOR_SUCCESS_HOVER = PALETTE_MIDNIGHT.success_hover
COLOR_DANGER_BG = PALETTE_MIDNIGHT.danger_bg
COLOR_DANGER_HOVER = PALETTE_MIDNIGHT.danger_hover
COLOR_BTN_SECONDARY_BG = PALETTE_MIDNIGHT.btn_secondary_bg
COLOR_BTN_SECONDARY_HOVER = PALETTE_MIDNIGHT.btn_secondary_hover
COLOR_BTN_SECONDARY_BORDER = PALETTE_MIDNIGHT.btn_secondary_border


def get_palette(theme_name: str) -> ThemePalette:
    """Return ThemePalette matching name or default midnight."""
    return THEME_PALETTES.get(theme_name.lower(), PALETTE_MIDNIGHT)


def generate_stylesheet(settings: AppearanceSettings | None = None) -> str:
    """Generate complete QSS stylesheet dynamically from appearance settings."""
    from ag_attention_bridge.settings import AppearanceSettings

    if settings is None:
        settings = AppearanceSettings()

    palette = get_palette(settings.theme_preset)
    scale = settings.font_scale
    accent = settings.accent_color

    # Font size calculations
    def s(px: int) -> str:
        return f"{max(8, int(round(px * scale)))}px"

    return f"""
QDialog {{
    background-color: transparent;
}}

QFrame#ModalContainer {{
    background-color: {palette.bg_window};
    color: {palette.text_primary};
    border: 1.5px solid {palette.border};
    border-radius: 14px;
}}

QWidget#CentralContainer {{
    background-color: {palette.bg_window};
}}

/* Header */
QFrame#HeaderFrame {{
    background-color: {palette.bg_card};
    border-bottom: 1px solid {palette.border};
    border-top-left-radius: 13px;
    border-top-right-radius: 13px;
}}

QLabel#HeaderTitle {{
    font-size: {s(15)};
    font-weight: bold;
    color: {palette.text_primary};
}}

QLabel#HeaderSubtitle {{
    font-size: {s(12)};
    color: {palette.text_secondary};
}}

QLabel#BadgeCount {{
    background-color: {palette.bg_card_nested};
    color: {accent};
    border: 1px solid {palette.border};
    border-radius: 10px;
    padding: 2px 8px;
    font-size: {s(11)};
    font-weight: bold;
}}

QLabel#ProjectBadge {{
    background-color: {palette.bg_card_nested};
    color: {accent};
    border: 1px solid {palette.border};
    border-radius: 6px;
    padding: 2px 8px;
    font-size: {s(11)};
    font-weight: 600;
}}

/* Context Section */
QFrame#ContextFrame {{
    background-color: {palette.bg_card};
    border: 1px solid {palette.border};
    border-radius: 8px;
    margin: 4px 0px;
}}

QLabel#ContextHeading {{
    font-size: {s(10)};
    font-weight: bold;
    color: {accent};
    letter-spacing: 0.5px;
}}

QLabel#ContextBody {{
    font-size: {s(12)};
    color: {palette.text_secondary};
    line-height: 1.4;
}}

/* Content Scroll Area */
QScrollArea {{
    background: transparent;
    border: none;
}}

QScrollArea > QWidget > QWidget {{
    background: transparent;
}}

QScrollBar:vertical {{
    background: {palette.bg_window};
    width: 8px;
    border-radius: 4px;
}}

QScrollBar::handle:vertical {{
    background: {palette.border};
    min-height: 24px;
    border-radius: 4px;
}}

QScrollBar::handle:vertical:hover {{
    background: {palette.text_muted};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}

/* Question Section */
QLabel#QuestionTitle {{
    font-size: {s(16)};
    font-weight: bold;
    color: {palette.text_primary};
}}

/* Option Cards (Radio & Checkbox) */
QRadioButton, QCheckBox {{
    background-color: {palette.bg_card_nested};
    color: {palette.text_primary};
    border: 1px solid {palette.border};
    border-radius: 8px;
    padding: 10px 14px;
    font-size: {s(13)};
    spacing: 10px;
}}

QRadioButton:hover, QCheckBox:hover {{
    background-color: {palette.bg_card_hover};
    border: 1px solid {palette.border_active};
}}

QRadioButton:checked, QCheckBox:checked {{
    background-color: {palette.option_checked_bg};
    border: 1.5px solid {accent};
    color: {palette.text_primary};
    font-weight: 500;
}}

QRadioButton::indicator {{
    width: 16px;
    height: 16px;
    border-radius: 8px;
    border: 2px solid {palette.text_muted};
    background: transparent;
}}

QRadioButton::indicator:checked {{
    border: 2px solid {accent};
    background: {accent};
}}

QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 2px solid {palette.text_muted};
    background: transparent;
}}

QCheckBox::indicator:checked {{
    border: 2px solid {accent};
    background: {accent};
}}

/* Custom Write-In Input */
QLineEdit, QTextEdit, QSpinBox, QComboBox {{
    background-color: {palette.bg_card_nested};
    color: {palette.text_primary};
    border: 1px solid {palette.border};
    border-radius: 8px;
    padding: 8px 12px;
    font-size: {s(13)};
}}

QLineEdit:focus, QTextEdit:focus, QSpinBox:focus, QComboBox:focus {{
    border: 1.5px solid {accent};
    background-color: {palette.bg_card};
}}

QComboBox::drop-down {{
    border: none;
    padding-right: 8px;
}}

QComboBox QAbstractItemView {{
    background-color: {palette.bg_card};
    color: {palette.text_primary};
    selection-background-color: {palette.bg_card_hover};
    selection-color: {palette.text_primary};
    border: 1px solid {palette.border};
    border-radius: 6px;
}}

/* Permission View */
QLabel#PermissionActionBadge {{
    background-color: #3b1822;
    color: #fda4af;
    border: 1px solid #9f1239;
    border-radius: 6px;
    padding: 3px 8px;
    max-height: 24px;
    font-size: {s(11)};
    font-weight: bold;
}}

QFrame#MonospaceTargetBox {{
    background-color: {palette.monospace_bg};
    border: 1px solid {palette.border};
    border-radius: 8px;
    padding: 8px 12px;
}}

QLabel#MonospaceTargetText {{
    font-family: 'JetBrains Mono', 'Fira Code', 'DejaVu Sans Mono', monospace;
    font-size: {s(12)};
    color: {accent};
}}

QLabel#ReasonText {{
    font-size: {s(13)};
    color: {palette.text_secondary};
}}

/* Footer & Buttons */
QFrame#FooterFrame {{
    background-color: {palette.bg_card};
    border-top: 1px solid {palette.border};
    border-bottom-left-radius: 13px;
    border-bottom-right-radius: 13px;
}}

QFrame#FooterFrame QPushButton {{
    padding: 6px 11px;
    font-size: {s(12)};
    font-weight: 600;
    border-radius: 7px;
    min-height: 22px;
}}

QPushButton {{
    font-size: {s(13)};
    font-weight: 600;
    border-radius: 8px;
    padding: 8px 18px;
    min-height: 20px;
}}

QPushButton#BtnSubmit, QPushButton#BtnAllow {{
    background-color: {palette.success_bg};
    color: #ffffff;
    border: none;
}}

QPushButton#BtnSubmit:hover, QPushButton#BtnAllow:hover {{
    background-color: {palette.success_hover};
}}

QPushButton#BtnSubmit:focus, QPushButton#BtnAllow:focus {{
    outline: none;
    border: 2px solid #a7f3d0;
}}

QPushButton#BtnDeny {{
    background-color: {palette.danger_bg};
    color: #ffffff;
    border: none;
}}

QPushButton#BtnDeny:hover {{
    background-color: {palette.danger_hover};
}}

QPushButton#BtnAllowConversation, QPushButton#BtnAllowGlobal {{
    background-color: {palette.btn_secondary_bg};
    color: {accent};
    border: 1px solid {palette.border};
}}

QPushButton#BtnAllowConversation:hover, QPushButton#BtnAllowGlobal:hover {{
    background-color: {palette.bg_card_hover};
    color: #ffffff;
}}

QPushButton#BtnAllowConversation:focus, QPushButton#BtnAllowGlobal:focus {{
    outline: none;
    border: 2px solid {accent};
}}

QPushButton#BtnDismiss {{
    background-color: {palette.btn_secondary_bg};
    color: {palette.text_secondary};
    border: 1px solid {palette.btn_secondary_border};
}}

QPushButton#BtnDismiss:hover {{
    background-color: {palette.btn_secondary_hover};
    color: {palette.text_primary};
}}

QPushButton#HeaderCloseBtn, QPushButton#HeaderSettingsBtn {{
    background: transparent;
    color: {palette.text_muted};
    font-size: {s(14)};
    border: none;
    padding: 4px;
    border-radius: 6px;
}}

QPushButton#HeaderCloseBtn:hover, QPushButton#HeaderSettingsBtn:hover {{
    background-color: {palette.bg_card_nested};
    color: {palette.text_primary};
}}
"""


MAIN_STYLESHEET = generate_stylesheet()


def apply_theme(widget, settings: AppearanceSettings | None = None) -> None:
    """Apply the application theme stylesheet to a QWidget or QApplication."""
    stylesheet = generate_stylesheet(settings)
    widget.setStyleSheet(stylesheet)
