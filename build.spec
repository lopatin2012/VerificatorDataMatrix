# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for a lightweight standalone build.

Single-file exe with the GUI / CLI / web entry point. The optional neural-net
locator is excluded (torch is not bundled); `core/nn_locator.py` catches the
ImportError, so the app runs fine without it.
"""
from PyInstaller.utils.hooks import collect_all

datas = [("webui", "webui"), ("favicon.ico", ".")]
binaries = []
hiddenimports = ["waitress"]

# zxing-cpp ships a compiled extension; reportlab has font/data files.
for pkg in ("zxingcpp", "reportlab"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

excludes = [
    "torch", "torchvision", "torchaudio", "training",
    "matplotlib", "scipy", "pandas", "IPython", "notebook",
    "PyQt5", "PyQt6", "PySide2", "PySide6", "pytest",
]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="DataMatrixVerifier",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="favicon.ico",
)
