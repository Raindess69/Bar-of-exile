# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Bar of Exile — onedir, windowed, shareable build.

Bundles assets/ and data/ (skipping _tmp* backup dirs) next to the frozen game.
Saves are written beside the .exe at runtime (see game/save.py _default_save_dir),
NOT into the bundle, so player progress survives across launches.

Build:   python -m PyInstaller bar_of_exile.spec --noconfirm
Output:  dist/BarOfExile/BarOfExile.exe  (+ _internal/ with all assets)
"""
import os

PROJECT = os.getcwd()


def _collect(top: str) -> list:
    """(source_file, dest_dir) pairs for every file under `top`, preserving the
    tree and skipping _tmp*/__pycache__ so raw-source backups don't bloat the exe."""
    out = []
    for root, dirs, files in os.walk(os.path.join(PROJECT, top)):
        dirs[:] = [d for d in dirs
                   if not d.startswith("_tmp") and d != "__pycache__"]
        for f in files:
            if f.endswith((".pyc",)):
                continue
            src = os.path.join(root, f)
            rel = os.path.relpath(root, PROJECT)   # e.g. assets\sprites\goblin
            out.append((src, rel))
    return out


datas = _collect("assets") + _collect("data")

# Optional modules main.py imports under try/except — force-include so the frozen
# build has the full game, not the degraded fallback.
hiddenimports = [
    "game.tree", "ui.tree_panel", "ui.vendor_panel",
    "game.gamble", "ui.gamble_panel",
    "game.stats_track", "ui.stats_panel", "ui.skills_panel",
]

a = Analysis(
    ["main.py"],
    pathex=[PROJECT],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "numpy", "matplotlib", "PIL"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="BarOfExile",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,              # windowed — no console popup for players
    icon="build_icon.ico",
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="BarOfExile",
)
