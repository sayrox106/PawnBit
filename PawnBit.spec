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
    pathex=['src'],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib', 'numpy', 'pandas', 'scipy', 'IPython', 'jupyter',
        'pytest', 'unittest', 'test', 'distutils', 'pywin32', 'pydoc',
        'http.server', 'xmlrpc', 'curses', 'sqlite3'
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
    strip=True,       # Strip symbols to reduce size
    upx=False,       # Disable UPX to avoid Antivirus false positives
    upx_exclude=[],
    runtime_tmpdir=None,
    # Set console=False for a professional silent windowed app.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='src/assets/pawn_32x32.png',
)
