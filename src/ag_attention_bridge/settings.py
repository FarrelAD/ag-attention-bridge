"""User appearance settings and configuration persistence."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ag_attention_bridge.config import SETTINGS_PATH

logger = logging.getLogger("ag_attention_bridge.settings")

# Preset names
THEME_MIDNIGHT = "midnight"
THEME_OLED_BLACK = "oled_black"
THEME_NORD = "nord"
THEME_LIGHT = "light"

SUPPORTED_THEMES = [
    THEME_MIDNIGHT,
    THEME_OLED_BLACK,
    THEME_NORD,
    THEME_LIGHT,
]

DEFAULT_ACCENT_COLORS = {
    "Sky Blue": "#38bdf8",
    "Emerald": "#10b981",
    "Amber": "#f59e0b",
    "Violet": "#a855f7",
    "Rose": "#f43f5e",
}


@dataclass
class AppearanceSettings:
    """User-customizable appearance configuration."""

    theme_preset: str = THEME_MIDNIGHT
    accent_color: str = "#38bdf8"
    font_scale: float = 1.0  # 0.9 (Compact), 1.0 (Standard), 1.15 (Large), 1.3 (Extra Large)
    dialog_width: int = 720  # Clamped 560..960
    window_opacity: float = 1.0  # 0.85 .. 1.0
    enable_animations: bool = True

    def validate_and_clamp(self) -> AppearanceSettings:
        """Validate and clamp numeric bounds."""
        if self.theme_preset not in SUPPORTED_THEMES:
            self.theme_preset = THEME_MIDNIGHT

        if not (self.accent_color.startswith("#") and len(self.accent_color) in (4, 7)):
            self.accent_color = "#38bdf8"

        self.font_scale = max(0.85, min(1.5, float(self.font_scale)))
        self.dialog_width = max(560, min(960, int(self.dialog_width)))
        self.window_opacity = max(0.70, min(1.0, float(self.window_opacity)))
        return self

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AppearanceSettings:
        theme = data.get("theme_preset", THEME_MIDNIGHT)
        accent = data.get("accent_color", "#38bdf8")
        font_scale = data.get("font_scale", 1.0)
        dialog_width = data.get("dialog_width", 720)
        window_opacity = data.get("window_opacity", 1.0)
        enable_animations = data.get("enable_animations", True)

        settings = cls(
            theme_preset=str(theme),
            accent_color=str(accent),
            font_scale=float(font_scale),
            dialog_width=int(dialog_width),
            window_opacity=float(window_opacity),
            enable_animations=bool(enable_animations),
        )
        return settings.validate_and_clamp()


def load_settings(path: Path | None = None) -> AppearanceSettings:
    """Load settings from JSON file with graceful fallback to defaults."""
    target_path = path or SETTINGS_PATH
    if not target_path.exists():
        return AppearanceSettings()

    try:
        with open(target_path, encoding="utf-8") as f:
            raw = json.load(f)
        if isinstance(raw, dict):
            return AppearanceSettings.from_dict(raw)
    except Exception as e:
        logger.warning("Failed to parse appearance settings from %s: %s. Using defaults.", target_path, e)

    return AppearanceSettings()


def save_settings(settings: AppearanceSettings, path: Path | None = None) -> bool:
    """Save settings to JSON file."""
    target_path = path or SETTINGS_PATH
    try:
        settings.validate_and_clamp()
        target_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(settings.to_dict(), f, indent=2)
        return True
    except Exception as e:
        logger.error("Failed to save appearance settings to %s: %s", target_path, e)
        return False
