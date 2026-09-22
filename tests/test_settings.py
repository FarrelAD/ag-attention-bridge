"""Unit tests for user appearance settings and dynamic theming."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QApplication

from ag_attention_bridge.settings import (
    THEME_LIGHT,
    THEME_MIDNIGHT,
    THEME_NORD,
    THEME_OLED_BLACK,
    AppearanceSettings,
    load_settings,
    save_settings,
)
from ag_attention_bridge.ui.main_dialog import InteractionModal
from ag_attention_bridge.ui.settings_dialog import AppearanceSettingsDialog
from ag_attention_bridge.ui.theme import generate_stylesheet, get_palette


def test_appearance_settings_defaults():
    settings = AppearanceSettings()
    assert settings.theme_preset == THEME_MIDNIGHT
    assert settings.accent_color == "#38bdf8"
    assert settings.dialog_width == 720
    assert settings.font_scale == 1.0
    assert settings.window_opacity == 1.0


def test_appearance_settings_clamping():
    settings = AppearanceSettings(
        theme_preset="invalid_theme",
        accent_color="invalid_color",
        font_scale=999.0,
        dialog_width=2000,
        window_opacity=0.1,
    )
    settings.validate_and_clamp()

    assert settings.theme_preset == THEME_MIDNIGHT
    assert settings.accent_color == "#38bdf8"
    assert settings.dialog_width == 960  # Upper bound
    assert settings.font_scale == 1.5   # Upper bound
    assert settings.window_opacity == 0.70  # Lower bound


def test_load_and_save_settings(tmp_path: Path):
    target = tmp_path / "custom_settings.json"
    s = AppearanceSettings(
        theme_preset=THEME_OLED_BLACK,
        accent_color="#10b981",
        font_scale=1.15,
        dialog_width=800,
    )

    saved = save_settings(s, target)
    assert saved is True
    assert target.exists()

    loaded = load_settings(target)
    assert loaded.theme_preset == THEME_OLED_BLACK
    assert loaded.accent_color == "#10b981"
    assert loaded.font_scale == 1.15
    assert loaded.dialog_width == 800


def test_load_corrupted_settings_fallback(tmp_path: Path):
    target = tmp_path / "corrupt.json"
    target.write_text("{ invalid json !!", encoding="utf-8")

    loaded = load_settings(target)
    assert loaded.theme_preset == THEME_MIDNIGHT
    assert loaded.dialog_width == 720


def test_generate_stylesheet_presets():
    for preset in [THEME_MIDNIGHT, THEME_OLED_BLACK, THEME_NORD, THEME_LIGHT]:
        settings = AppearanceSettings(theme_preset=preset, accent_color="#f59e0b", font_scale=1.2)
        qss = generate_stylesheet(settings)
        palette = get_palette(preset)

        assert palette.bg_window in qss
        assert "#f59e0b" in qss  # Accent color injected
        assert "QFrame#ModalContainer" in qss


def test_interaction_modal_apply_appearance(qapp: QApplication):
    modal = InteractionModal()
    assert modal.width() == 720

    new_settings = AppearanceSettings(dialog_width=840, font_scale=1.15)
    modal.apply_appearance(new_settings)
    assert modal.width() == 840
    assert modal.settings.dialog_width == 840


def test_settings_dialog_interaction(qapp: QApplication):
    dialog = AppearanceSettingsDialog()
    assert dialog.combo_theme.count() >= 4
    assert dialog.slider_width.value() == 720

    # Switch theme in UI
    idx = dialog.combo_theme.findData(THEME_NORD)
    assert idx >= 0
    dialog.combo_theme.setCurrentIndex(idx)
    assert dialog.settings.theme_preset == THEME_NORD

    # Adjust width
    dialog.slider_width.setValue(780)
    assert dialog.settings.dialog_width == 780
