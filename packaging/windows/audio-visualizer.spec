# -*- mode: python ; coding: utf-8 -*-
"""One-folder Windows build. The zip is this directory plus the install scripts."""
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

root = Path(SPECPATH).resolve().parents[1]
pkg_datas, pkg_binaries, pkg_hidden = collect_all("pyaudiowpatch")

a = Analysis(
    [str(root / "server.py")],
    pathex=[str(root)],
    binaries=pkg_binaries,
    datas=pkg_datas
    + [
        (str(root / "web"), "web"),
        (str(root / "windows" / "now_playing.ps1"), "windows"),
        (str(root / "windows" / "shortcuts.ps1"), "windows"),
        (str(root / "windows" / "setup-python.ps1"), "windows"),
    ],
    hiddenimports=pkg_hidden + ["pyaudiowpatch"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AudioVisualizer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="AudioVisualizer",
)
