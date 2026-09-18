"""Premium visual styling and QSS stylesheets for Ag Attention Bridge."""

from __future__ import annotations

# Theme color tokens
COLOR_BG_WINDOW = "#090d16"
COLOR_BG_CARD = "#0f172a"
COLOR_BG_CARD_NESTED = "#1e293b"
COLOR_BG_CARD_HOVER = "#243247"
COLOR_BORDER = "#334155"
COLOR_BORDER_FOCUS = "#38bdf8"
COLOR_BORDER_ACTIVE = "#60a5fa"

COLOR_TEXT_PRIMARY = "#f8fafc"
COLOR_TEXT_SECONDARY = "#94a3b8"
COLOR_TEXT_MUTED = "#64748b"

COLOR_ACCENT_PRIMARY = "#38bdf8"
COLOR_ACCENT_HOVER = "#0ea5e9"
COLOR_ACCENT_TEXT = "#0c4a6e"

COLOR_SUCCESS_BG = "#10b981"
COLOR_SUCCESS_HOVER = "#059669"
COLOR_DANGER_BG = "#f43f5e"
COLOR_DANGER_HOVER = "#e11d48"

COLOR_BTN_SECONDARY_BG = "#1e293b"
COLOR_BTN_SECONDARY_HOVER = "#334155"
COLOR_BTN_SECONDARY_BORDER = "#475569"


MAIN_STYLESHEET = f"""
QDialog {{
    background-color: transparent;
}}

QFrame#ModalContainer {{
    background-color: {COLOR_BG_WINDOW};
    color: {COLOR_TEXT_PRIMARY};
    border: 1.5px solid {COLOR_BORDER};
    border-radius: 14px;
}}

QWidget#CentralContainer {{
    background-color: {COLOR_BG_WINDOW};
}}

/* Header */
QFrame#HeaderFrame {{
    background-color: {COLOR_BG_CARD};
    border-bottom: 1px solid {COLOR_BORDER};
    border-top-left-radius: 13px;
    border-top-right-radius: 13px;
}}

QLabel#HeaderTitle {{
    font-size: 15px;
    font-weight: bold;
    color: {COLOR_TEXT_PRIMARY};
}}

QLabel#HeaderSubtitle {{
    font-size: 12px;
    color: {COLOR_TEXT_SECONDARY};
}}

QLabel#BadgeCount {{
    background-color: {COLOR_BG_CARD_NESTED};
    color: {COLOR_ACCENT_PRIMARY};
    border: 1px solid {COLOR_BORDER};
    border-radius: 10px;
    padding: 2px 8px;
    font-size: 11px;
    font-weight: bold;
}}

QLabel#ProjectBadge {{
    background-color: {COLOR_BG_CARD_NESTED};
    color: {COLOR_ACCENT_PRIMARY};
    border: 1px solid {COLOR_BORDER};
    border-radius: 6px;
    padding: 2px 8px;
    font-size: 11px;
    font-weight: 600;
}}

/* Context Section */
QFrame#ContextFrame {{
    background-color: {COLOR_BG_CARD};
    border: 1px solid {COLOR_BORDER};
    border-radius: 8px;
    margin: 4px 0px;
}}

QLabel#ContextHeading {{
    font-size: 10px;
    font-weight: bold;
    color: {COLOR_ACCENT_PRIMARY};
    letter-spacing: 0.5px;
}}

QLabel#ContextBody {{
    font-size: 12px;
    color: {COLOR_TEXT_SECONDARY};
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
    background: {COLOR_BG_WINDOW};
    width: 8px;
    border-radius: 4px;
}}

QScrollBar::handle:vertical {{
    background: {COLOR_BORDER};
    min-height: 24px;
    border-radius: 4px;
}}

QScrollBar::handle:vertical:hover {{
    background: {COLOR_TEXT_MUTED};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}

/* Question Section */
QLabel#QuestionTitle {{
    font-size: 16px;
    font-weight: bold;
    color: {COLOR_TEXT_PRIMARY};
}}

/* Option Cards (Radio & Checkbox) */
QRadioButton, QCheckBox {{
    background-color: {COLOR_BG_CARD_NESTED};
    color: {COLOR_TEXT_PRIMARY};
    border: 1px solid {COLOR_BORDER};
    border-radius: 8px;
    padding: 10px 14px;
    font-size: 13px;
    spacing: 10px;
}}

QRadioButton:hover, QCheckBox:hover {{
    background-color: {COLOR_BG_CARD_HOVER};
    border: 1px solid {COLOR_BORDER_ACTIVE};
}}

QRadioButton:checked, QCheckBox:checked {{
    background-color: #1e3a5f;
    border: 1.5px solid {COLOR_ACCENT_PRIMARY};
    color: #ffffff;
    font-weight: 500;
}}

QRadioButton::indicator {{
    width: 16px;
    height: 16px;
    border-radius: 8px;
    border: 2px solid {COLOR_TEXT_MUTED};
    background: transparent;
}}

QRadioButton::indicator:checked {{
    border: 2px solid {COLOR_ACCENT_PRIMARY};
    background: {COLOR_ACCENT_PRIMARY};
}}

QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 2px solid {COLOR_TEXT_MUTED};
    background: transparent;
}}

QCheckBox::indicator:checked {{
    border: 2px solid {COLOR_ACCENT_PRIMARY};
    background: {COLOR_ACCENT_PRIMARY};
}}

/* Custom Write-In Input */
QLineEdit, QTextEdit {{
    background-color: {COLOR_BG_CARD_NESTED};
    color: {COLOR_TEXT_PRIMARY};
    border: 1px solid {COLOR_BORDER};
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 13px;
}}

QLineEdit:focus, QTextEdit:focus {{
    border: 1.5px solid {COLOR_BORDER_FOCUS};
    background-color: {COLOR_BG_CARD};
}}

/* Permission View */
QLabel#PermissionActionBadge {{
    background-color: #3b1822;
    color: #fda4af;
    border: 1px solid #9f1239;
    border-radius: 6px;
    padding: 3px 8px;
    font-size: 11px;
    font-weight: bold;
}}

QFrame#MonospaceTargetBox {{
    background-color: #030712;
    border: 1px solid {COLOR_BORDER};
    border-radius: 8px;
    padding: 8px 12px;
}}

QLabel#MonospaceTargetText {{
    font-family: 'JetBrains Mono', 'Fira Code', 'DejaVu Sans Mono', monospace;
    font-size: 12px;
    color: #38bdf8;
}}

QLabel#ReasonText {{
    font-size: 13px;
    color: {COLOR_TEXT_SECONDARY};
}}

/* Footer & Buttons */
QFrame#FooterFrame {{
    background-color: {COLOR_BG_CARD};
    border-top: 1px solid {COLOR_BORDER};
    border-bottom-left-radius: 13px;
    border-bottom-right-radius: 13px;
}}

QPushButton {{
    font-size: 13px;
    font-weight: 600;
    border-radius: 8px;
    padding: 8px 18px;
    min-height: 20px;
}}

QPushButton#BtnSubmit, QPushButton#BtnAllow {{
    background-color: {COLOR_SUCCESS_BG};
    color: #ffffff;
    border: none;
}}

QPushButton#BtnSubmit:hover, QPushButton#BtnAllow:hover {{
    background-color: {COLOR_SUCCESS_HOVER};
}}

QPushButton#BtnSubmit:focus, QPushButton#BtnAllow:focus {{
    outline: none;
    border: 2px solid #a7f3d0;
}}

QPushButton#BtnDeny {{
    background-color: {COLOR_DANGER_BG};
    color: #ffffff;
    border: none;
}}

QPushButton#BtnDeny:hover {{
    background-color: {COLOR_DANGER_HOVER};
}}

QPushButton#BtnDismiss {{
    background-color: {COLOR_BTN_SECONDARY_BG};
    color: {COLOR_TEXT_SECONDARY};
    border: 1px solid {COLOR_BTN_SECONDARY_BORDER};
}}

QPushButton#BtnDismiss:hover {{
    background-color: {COLOR_BTN_SECONDARY_HOVER};
    color: {COLOR_TEXT_PRIMARY};
}}

QPushButton#HeaderCloseBtn {{
    background: transparent;
    color: {COLOR_TEXT_MUTED};
    font-size: 14px;
    border: none;
    padding: 4px;
    border-radius: 6px;
}}

QPushButton#HeaderCloseBtn:hover {{
    background-color: {COLOR_BG_CARD_NESTED};
    color: {COLOR_TEXT_PRIMARY};
}}
"""


def apply_theme(widget) -> None:
    """Apply the application theme stylesheet to a QWidget or QApplication."""
    widget.setStyleSheet(MAIN_STYLESHEET)
