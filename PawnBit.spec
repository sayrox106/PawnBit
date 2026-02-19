# -*- mode: python ; coding: utf-8 -*-
# PawnBit.spec  –  PyInstaller build specification
#
# Usage:
#   pip install pyinstaller
#   pyinstaller PawnBit.spec
#
# Output: dist/PawnBit  (or dist/PawnBit.exe on Windows)

import sys
import platform
from pathlib import Path

block_cipher = None

# ---------------------------------------------------------------------------
# Collect all source files as datas so they can be restored to _MEIPASS
# ---------------------------------------------------------------------------
datas = [
    # Assets (icon, images)
    ('src/assets', 'assets'),
    # Grabber package (needed for dynamic import resolution inside frozen exe)
    ('src/grabbers', 'grabbers'),
]

hidden_imports = [
    # Core
    'multiprocess',
    'multiprocess.pool',
    'multiprocess.process',
    'dill',
    'dill.detect',
    # Chess
    'chess',
    'chess.engine',
    'stockfish',
    # GUI / automation
    'pyautogui',
    'pynput',
    'pynput.keyboard',
    'pynput.mouse',
    'keyboard',
    'tkinter',
    'tkinter.ttk',
    'tkinter.filedialog',
    'tkinter.messagebox',
    # Overlay
    'PyQt6',
    'PyQt6.QtWidgets',
    'PyQt6.QtCore',
    'PyQt6.QtGui',
    # Selenium + driver manager
    'selenium',
    'selenium.webdriver',
    'selenium.webdriver.chrome',
    'selenium.webdriver.chrome.service',
    'selenium.webdriver.chrome.options',
    'selenium.webdriver.common',
    'selenium.webdriver.common.by',
    'selenium.common',
    'selenium.common.exceptions',
    'webdriver_manager',
    'webdriver_manager.chrome',
    # Utility
    'packaging',
    'packaging.version',
    'packaging.specifiers',
    'packaging.requirements',
    'pkg_resources',
    'PIL',
    'PIL.Image',
    # Stdlib that sometimes needs explicit listing
    'zipfile',
    'tarfile',
    'urllib.request',
    'urllib.error',
    'tempfile',
    'subprocess',
    'platform',
    'struct',
]

# ---------------------------------------------------------------------------
a = Analysis(
    ['src/gui.py'],
    pathex=['src'],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib',
        'numpy',
        'pandas',
        'scipy',
        'IPython',
        'jupyter',
        'pytest',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='PawnBit',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    # Keep console=True for beta builds so errors are visible.
    # Set to False for a silent final release.
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # PNG icon works on Windows (PyInstaller 6+). For macOS use .icns.
    icon='src/assets/pawn_32x32.png',
)
