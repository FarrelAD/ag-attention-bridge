# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for Ag Attention Bridge on Windows."""

import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

repo_root = Path(SPECPATH).parent.parent.resolve()
src_dir = repo_root / "src"

sys.path.insert(0, str(src_dir))

# 1. Daemon GUI executable (windowed, no console window)
a_app = Analysis(
    [str(src_dir / "ag_attention_bridge" / "app.py")],
    pathex=[str(src_dir)],
    binaries=[],
    datas=[],
    hiddenimports=[
        "PySide6.QtNetwork",
        "PySide6.QtWidgets",
        "PySide6.QtGui",
        "PySide6.QtCore",
        "ag_attention_bridge.antigravity.client",
        "ag_attention_bridge.antigravity.discovery",
        "ag_attention_bridge.antigravity.interaction_resolver",
        "ag_attention_bridge.antigravity.models",
        "ag_attention_bridge.domain.models",
        "ag_attention_bridge.ipc.protocol",
        "ag_attention_bridge.ipc.server",
        "ag_attention_bridge.state.store",
        "ag_attention_bridge.state.watcher",
        "ag_attention_bridge.ui.main_dialog",
        "ag_attention_bridge.ui.permission_view",
        "ag_attention_bridge.ui.question_view",
        "ag_attention_bridge.ui.theme",
        "ag_attention_bridge.ui.tray",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy", "scipy"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz_app = PYZ(a_app.pure, a_app.zipped_data, cipher=block_cipher)

exe_app = EXE(
    pyz_app,
    a_app.scripts,
    [],
    exclude_binaries=True,
    name="ag-attention-bridge",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # Windowed GUI application
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# 2. Lightweight CLI Hook Adapter (console app, fast startup)
a_adapter = Analysis(
    [str(src_dir / "ag_attention_bridge" / "hooks" / "adapter.py")],
    pathex=[str(src_dir)],
    binaries=[],
    datas=[],
    hiddenimports=[
        "ag_attention_bridge.config",
        "ag_attention_bridge.ipc.protocol",
        "ag_attention_bridge.ipc.client",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PySide6", "tkinter", "matplotlib"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz_adapter = PYZ(a_adapter.pure, a_adapter.zipped_data, cipher=block_cipher)

exe_adapter = EXE(
    pyz_adapter,
    a_adapter.scripts,
    [],
    exclude_binaries=True,
    name="ag-hook-adapter",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,  # Console application for stdin/stdout piping
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe_app,
    a_app.binaries,
    a_app.zipfiles,
    a_app.datas,
    exe_adapter,
    a_adapter.binaries,
    a_adapter.zipfiles,
    a_adapter.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="AgAttentionBridge",
)
