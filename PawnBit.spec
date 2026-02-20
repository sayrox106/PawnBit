# -*- mode: python ; coding: utf-8 -*-
# PawnBit.spec  –  PyInstaller build specification
#
# Usage:
#   pip install pyinstaller
#   pyinstaller PawnBit.spec
#
# Output: dist/PawnBit  (or dist/PawnBit.exe on Windows)

import sys
import os
import platform
from pathlib import Path

block_cipher = None
_CUR_DIR = os.path.abspath(os.getcwd())

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
    'chess',
    'chess.engine',
    'stockfish',
    # GUI / automation
    'pyautogui',
    'keyboard',
    'tkinter',
    'tkinter.ttk',
    'tkinter.filedialog',
    'tkinter.messagebox',
    'queue',
    'threading',
    # Selenium
    'selenium',
    'selenium.webdriver',
    'selenium.webdriver.chrome',
    'selenium.webdriver.chrome.service',
    'selenium.webdriver.chrome.options',
    'selenium.webdriver.common',
    'selenium.webdriver.common.by',
    'selenium.common',
    'selenium.common.exceptions',
    # Utility
    'packaging',
    'pkg_resources',
    'PIL',
    'PIL.Image',
    'zipfile',
    'tarfile',
    'urllib.request',
    'urllib.error',
    'tempfile',
    'subprocess',
    'platform',
]

# ---------------------------------------------------------------------------
a = Analysis(
    ['src/gui.py'],
    pathex=[_CUR_DIR, os.path.join(_CUR_DIR, 'src')],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib', 'numpy', 'pandas', 'scipy', 'IPython', 'jupyter',
        'pytest', 'unittest', 'test'
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
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='src/assets/pawn_32x32.png',
)
