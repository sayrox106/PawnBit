"""
engine_manager.py
=================
Handles all Stockfish engine lifecycle management:
  - System / CPU-feature detection
  - Finding an existing engine from config.json or engines/ directory
  - Validating the engine binary (UCI spawn test)
  - Fetching the latest GitHub release
  - Selecting the best asset (AVX2 > modern > generic)
  - Downloading the full archive with progress callback
  - Extracting the COMPLETE release structure
  - Writing version.json metadata
  - Updating config.json
  - Checking for / applying updates

gui.py may ONLY call the public high-level methods:
  ensure_engine()        -> dict | None
  get_engine_status()    -> dict
  install_engine(cb)     -> bool
  update_engine(cb)      -> bool
"""

import json
import os
import platform
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
import tarfile
import urllib.request
import urllib.error
from pathlib import Path
from typing import Callable, Optional, Dict, Any

# ---------------------------------------------------------------------------
# Paths  (handles both normal Python run and PyInstaller frozen executable)
# ---------------------------------------------------------------------------
if getattr(sys, 'frozen', False):
    # Running as a bundled .exe / binary:
    # Place config.json and engines/ next to the executable.
    _BASE_DIR = Path(sys.executable).resolve().parent
else:
    # Normal source run: project root is two levels up from this file.
    _BASE_DIR = Path(__file__).resolve().parent.parent   # PawnBit/
_ENGINES_DIR = _BASE_DIR / "engines" / "stockfish"
_CONFIG_PATH = _BASE_DIR / "config.json"

_GITHUB_API_URL = "https://api.github.com/repos/official-stockfish/Stockfish/releases/latest"
_DOWNLOAD_TIMEOUT   = 60    # seconds per urllib call
_SPAWN_TIMEOUT      = 5.0  # seconds for the binary spawn test (Stockfish 18 can be slow on first run)
_INSTALL_VALIDATE_T = 10.0  # extra-long timeout used only right after installation


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_config() -> Dict[str, Any]:
    """Return parsed config.json or an empty dict."""
    try:
        if _CONFIG_PATH.exists():
            with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _save_config(data: Dict[str, Any]) -> None:
    with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _load_version_json(version_dir: Path) -> Optional[Dict[str, Any]]:
    vpath = _ENGINES_DIR / version_dir / "version.json"
    if not vpath.exists():
        # Try directly in versions_dir
        vpath = _ENGINES_DIR / "version.json"
    try:
        if vpath.exists():
            with open(vpath, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return None


def _write_version_json(version_dir: Path, meta: Dict[str, Any]) -> None:
    vpath = version_dir / "version.json"
    with open(vpath, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)


# ---------------------------------------------------------------------------
# System / CPU feature detection
# ---------------------------------------------------------------------------

def detect_system() -> Dict[str, str]:
    """Return OS name and architecture string."""
    system = platform.system().lower()   # 'windows', 'linux', 'darwin'
    machine = platform.machine().lower() # 'amd64', 'x86_64', 'arm64', etc.

    if machine in ("amd64", "x86_64"):
        arch = "x86-64"
    elif machine in ("arm64", "aarch64"):
        arch = "arm64"
    elif machine.startswith("arm"):
        arch = "arm"
    else:
        arch = machine

    return {"os": system, "arch": arch}


def detect_cpu_features() -> Dict[str, bool]:
    """
    Detect CPU ISA extensions relevant to Stockfish asset selection.
    Returns a dict: { "bmi2": bool, "avx2": bool, "popcnt": bool }
    Note: on non-x86 platforms all flags return False.
    """
    features = {"bmi2": False, "avx2": False, "popcnt": False}

    if platform.machine().lower() not in ("amd64", "x86_64"):
        return features

    try:
        import cpuid  # optional; gracefully skip if not installed
        def _check(leaf, sub, reg, bit):
            regs = cpuid.cpuid_count(leaf, sub)
            return bool(getattr(regs, reg) & (1 << bit))
        features["avx2"]   = _check(7, 0, "ebx", 5)
        features["bmi2"]   = _check(7, 0, "ebx", 8)
        features["popcnt"] = _check(1, 0, "ecx", 23)
        return features
    except ImportError:
        pass

    # Fallback: try parsing /proc/cpuinfo on Linux
    if platform.system() == "Linux":
        try:
            with open("/proc/cpuinfo", "r") as f:
                flags = ""
                for line in f:
                    if line.startswith("flags"):
                        flags = line
                        break
            features["avx2"]   = "avx2"   in flags
            features["bmi2"]   = "bmi2"   in flags
            features["popcnt"] = "popcnt" in flags
            return features
        except Exception:
            pass

    # Fallback on Windows: try to import winreg info or just assume modern CPU
    if platform.system() == "Windows":
        # Heuristic: assume at least popcnt on any 64-bit Windows ≥ 10
        features["popcnt"] = True
        # Try subprocess to check for AVX2 via PowerShell
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "[System.Runtime.Intrinsics.X86.Avx2]::IsSupported"],
                capture_output=True, text=True, timeout=3
            )
            if "True" in result.stdout:
                features["avx2"] = True
                # BMI2 usually comes with AVX2 on Intel/AMD
                features["bmi2"] = True
        except Exception:
            pass

    return features


# ---------------------------------------------------------------------------
# Asset selection
# ---------------------------------------------------------------------------

_BUILD_PRIORITY = ["bmi2", "avx2", "modern", "sse41-popcnt", "x86-64-vnni256",
                   "x86-64-avx512", "x86-64-avx2", "x86-64-bmi2", "x86-64-modern",
                   "generic", "x86-64"]

def select_best_asset(assets: list, sys_info: Dict, cpu_features: Dict) -> Optional[Dict]:
    """
    Given a list of GitHub release assets, return the best one for the current system.
    Priority: BMI2 > AVX2 > modern > generic (for x86-64 Windows/Linux/macOS).
    """
    os_name = sys_info["os"]
    arch    = sys_info["arch"]

    # Map OS to asset name fragment
    if os_name == "windows":
        os_filter = "windows"
        ext_filter = ".zip"
    elif os_name == "darwin":
        os_filter = "macos"
        ext_filter = ".tar"
    else:
        os_filter = "linux"
        ext_filter = ".tar"

    candidates = [
        a for a in assets
        if os_filter in a["name"].lower() and a["name"].endswith(
            (".zip", ".tar.gz", ".tar") if ext_filter == ".tar" else (".zip",)
        )
    ]

    if not candidates:
        # Broader fallback
        candidates = [a for a in assets if os_filter in a["name"].lower()]

    if not candidates:
        return None

    def _score(asset_name: str) -> int:
        name = asset_name.lower()
        # Higher score = better
        if cpu_features.get("bmi2") and ("bmi2" in name):
            return 100
        if cpu_features.get("avx2") and ("avx2" in name or "avx512" in name or "vnni" in name):
            return 90
        if "modern" in name:
            return 70
        if "sse41" in name or "popcnt" in name:
            return 60
        if "generic" in name:
            return 10
        return 50  # unknown / source builds

    best = max(candidates, key=lambda a: _score(a["name"]))
    return best


# ---------------------------------------------------------------------------
# Binary validation
# ---------------------------------------------------------------------------

def validate_engine(path: str, timeout: float = _SPAWN_TIMEOUT) -> bool:
    """
    Attempt to spawn the binary and check for a UCI response.
    Times out after `timeout` seconds (default: _SPAWN_TIMEOUT).
    Returns True if the binary responds to 'uci' within the timeout.
    """
    if not path or not os.path.isfile(path):
        return False

    try:
        proc = subprocess.Popen(
            [path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0,
        )
        try:
            proc.stdin.write("uci\n")
            proc.stdin.flush()
        except Exception:
            proc.kill()
            return False

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                line = proc.stdout.readline()
            except Exception:
                break
            if "uciok" in line:
                proc.kill()
                return True

        proc.kill()
        return False
    except (OSError, PermissionError, FileNotFoundError):
        return False


# ---------------------------------------------------------------------------
# Finding existing engine
# ---------------------------------------------------------------------------

def find_existing_engine() -> Optional[Dict[str, Any]]:
    """
    Try to find a usable Stockfish engine.
    Returns a status dict or None.
    """
    cfg = _load_config()
    binary_path = cfg.get("stockfish_path", "")

    # 1. Config has a path?
    if binary_path and os.path.isfile(binary_path):
        abs_path = binary_path if os.path.isabs(binary_path) else str(_BASE_DIR / binary_path)
        if os.path.isfile(abs_path) and validate_engine(abs_path):
            vj = _find_version_json_for(abs_path)
            return _build_status(abs_path, vj)

    # 2. Scan engines/stockfish/ for versioned directories
    if _ENGINES_DIR.exists():
        for entry in sorted(_ENGINES_DIR.iterdir(), reverse=True):
            if not entry.is_dir():
                continue
            vj_path = entry / "version.json"
            if vj_path.exists():
                try:
                    with open(vj_path, "r", encoding="utf-8") as f:
                        vj = json.load(f)
                    bp = vj.get("binary_path", "")
                    abs_bp = bp if os.path.isabs(bp) else str(_BASE_DIR / bp)
                    if os.path.isfile(abs_bp) and validate_engine(abs_bp):
                        return _build_status(abs_bp, vj)
                except Exception:
                    continue

    return None


def _find_version_json_for(binary_path: str) -> Optional[Dict]:
    """
    Walk up the directory tree from the binary until we find a version.json.
    Stockfish archives extract as:  stockfish-18/stockfish/<binary>
    but version.json is written at: stockfish-18/version.json
    so we must look in ancestor directories too.
    Stop at the engines/stockfish root to avoid wandering too far up.
    """
    d = Path(binary_path).parent
    for _ in range(4):  # look at most 4 levels up
        vj = d / "version.json"
        if vj.exists():
            try:
                with open(vj, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        if d == _ENGINES_DIR or d == _BASE_DIR:
            break
        d = d.parent
    return None


def _build_status(binary_path: str, vj: Optional[Dict]) -> Dict[str, Any]:
    result = {
        "binary_path": binary_path,
        "version": vj.get("version", "?") if vj else "?",
        "arch":    vj.get("arch",    "?") if vj else "?",
        "build":   vj.get("build",   "?") if vj else "?",
        "valid":   True,
    }
    return result


# ---------------------------------------------------------------------------
# GitHub API & download
# ---------------------------------------------------------------------------

def fetch_latest_release() -> Optional[Dict]:
    """
    Fetch the latest Stockfish release from GitHub.
    Returns the release JSON dict or None on error.
    """
    try:
        req = urllib.request.Request(
            _GITHUB_API_URL,
            headers={"User-Agent": "PawnBit/1.0", "Accept": "application/vnd.github+json"}
        )
        with urllib.request.urlopen(req, timeout=_DOWNLOAD_TIMEOUT) as resp:
            if resp.status == 403:
                raise RuntimeError("GitHub API rate limit exceeded.")
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 403:
            raise RuntimeError("GitHub API rate limit exceeded.")
        raise
    except Exception as e:
        raise RuntimeError(f"Failed to fetch release info: {e}") from e


def _parse_version_from_release(release: Dict) -> str:
    tag = release.get("tag_name", "")
    # e.g. "sf_17" or "v17" or "17"
    m = re.search(r"(\d+(?:\.\d+)*)", tag)
    return m.group(1) if m else tag.lstrip("v").lstrip("sf_")


def _parse_build_from_name(name: str) -> str:
    """Extract build type from asset filename."""
    name = name.lower()
    for token in ["bmi2", "avx512", "avx2", "vnni256", "modern", "sse41-popcnt", "generic"]:
        if token in name:
            return token
    return "unknown"


def download_engine(
    url: str,
    dest_path: str,
    progress_cb: Optional[Callable[[int, int], None]] = None
) -> None:
    """
    Download a file from url to dest_path.
    progress_cb(downloaded_bytes, total_bytes) is called periodically.
    """
    req = urllib.request.Request(url, headers={"User-Agent": "PawnBit/1.0"})
    with urllib.request.urlopen(req, timeout=_DOWNLOAD_TIMEOUT) as resp:
        total = int(resp.headers.get("Content-Length", 0))
        downloaded = 0
        chunk_size = 65536
        with open(dest_path, "wb") as f:
            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if progress_cb:
                    progress_cb(downloaded, total)


# ---------------------------------------------------------------------------
# Installation
# ---------------------------------------------------------------------------

def _binary_name() -> str:
    return "stockfish.exe" if platform.system() == "Windows" else "stockfish"


_SKIP_EXTS = {".txt", ".md", ".json", ".zip", ".tar", ".gz", ".bz2", ".xz", ".sh", ".bat"}


def _find_binary_in_dir(root: Path) -> Optional[Path]:
    """
    Recursively find the best Stockfish binary inside an extracted directory.
    On Windows, prefer .exe files.  On Linux/macOS prefer files with no extension
    or specifically named 'stockfish'.
    """
    is_windows = platform.system() == "Windows"

    # 1. Exact name match (stockfish.exe / stockfish)
    exact = _binary_name()
    for p in root.rglob(exact):
        if p.is_file():
            return p

    # 2. On Windows: any stockfish*.exe
    if is_windows:
        candidates = sorted(root.rglob("stockfish*.exe"), key=lambda p: len(p.name), reverse=True)
        if candidates:
            return candidates[0]

    # 3. Fallback: any file starting with 'stockfish' that is not a known non-binary
    for p in sorted(root.rglob("stockfish*"), key=lambda p: len(p.name), reverse=True):
        if p.is_file() and p.suffix.lower() not in _SKIP_EXTS:
            return p

    return None


def install_engine(
    progress_cb: Optional[Callable[[str, int, int], None]] = None
) -> bool:
    """
    Full installation flow:
      1. Detect system & CPU features
      2. Fetch latest GitHub release
      3. Select best asset
      4. Download archive
      5. Extract complete structure
      6. Write version.json
      7. Update config.json
      8. Validate binary
    progress_cb(stage: str, done: int, total: int)
    Returns True on success.
    """
    def _progress(stage, done, total):
        if progress_cb:
            progress_cb(stage, done, total)

    _progress("detect", 0, 1)
    sys_info  = detect_system()
    cpu_feat  = detect_cpu_features()
    _progress("detect", 1, 1)

    _progress("fetch", 0, 1)
    release   = fetch_latest_release()
    _progress("fetch", 1, 1)

    version   = _parse_version_from_release(release)
    assets    = release.get("assets", [])
    asset     = select_best_asset(assets, sys_info, cpu_feat)

    if asset is None:
        raise RuntimeError("No suitable Stockfish release asset found for your system.")

    build_type = _parse_build_from_name(asset["name"])
    dl_url     = asset["browser_download_url"]
    fname      = asset["name"]

    # Prepare versioned directory
    version_dir_name = f"stockfish-{version}"
    version_dir = _ENGINES_DIR / version_dir_name
    version_dir.mkdir(parents=True, exist_ok=True)

    # Download to temp file
    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(fname).suffix) as tmp:
        tmp_path = tmp.name

    try:
        def _dl_cb(done, total):
            _progress("download", done, total)

        _progress("download", 0, 1)
        download_engine(dl_url, tmp_path, _dl_cb)

        # Extract complete archive
        _progress("extract", 0, 1)
        _extract_archive(tmp_path, version_dir)
        _progress("extract", 1, 1)

    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass

    # Find the binary
    binary = _find_binary_in_dir(version_dir)
    if binary is None:
        raise RuntimeError(
            f"Could not find stockfish binary inside extracted directory: {version_dir}"
        )

    # Make executable on Unix
    if platform.system() != "Windows":
        binary.chmod(binary.stat().st_mode | 0o111)

    # Relative path for portability
    try:
        rel_binary = binary.relative_to(_BASE_DIR)
        binary_path_str = str(rel_binary).replace("\\", "/")
    except ValueError:
        binary_path_str = str(binary)

    # Write version.json
    meta = {
        "version":     version,
        "arch":        sys_info["arch"],
        "build":       build_type,
        "binary_path": binary_path_str,
    }
    _write_version_json(version_dir, meta)

    # Update config.json
    cfg = _load_config()
    cfg["stockfish_path"] = binary_path_str
    cfg["stockfish_version"] = version
    _save_config(cfg)

    # Validate — use a longer timeout right after installation because Windows Defender
    # or other AV software may scan the newly written executable on first launch.
    abs_bin = str(_BASE_DIR / binary_path_str)
    if not validate_engine(abs_bin, timeout=_INSTALL_VALIDATE_T):
        raise RuntimeError(
            f"Engine binary failed validation after installation:\n"
            f"{abs_bin}\n\n"
            f"The file exists but did not respond to the UCI protocol within "
            f"{_INSTALL_VALIDATE_T:.0f} seconds.\n"
            f"This can happen if your antivirus is scanning the file. "
            f"Please try again or add the engines/ folder to your AV exclusions."
        )

    _progress("done", 1, 1)
    return True


def _extract_archive(archive_path: str, dest_dir: Path) -> None:
    """Extract zip or tar archive preserving full structure."""
    if archive_path.endswith(".zip"):
        with zipfile.ZipFile(archive_path, "r") as z:
            z.extractall(dest_dir)
    elif archive_path.endswith((".tar.gz", ".tgz", ".tar.bz2", ".tar.xz", ".tar")):
        with tarfile.open(archive_path, "r:*") as t:
            t.extractall(dest_dir)
    else:
        # Try zip first, then tar
        try:
            with zipfile.ZipFile(archive_path, "r") as z:
                z.extractall(dest_dir)
        except zipfile.BadZipFile:
            with tarfile.open(archive_path, "r:*") as t:
                t.extractall(dest_dir)


# ---------------------------------------------------------------------------
# Update check
# ---------------------------------------------------------------------------

def check_for_updates() -> Optional[Dict[str, str]]:
    """
    Check if a newer Stockfish release is available.
    Returns {"current": "17", "latest": "18"} if an update exists, else None.
    """
    cfg = _load_config()
    current = cfg.get("stockfish_version", "")
    if not current:
        return None

    try:
        release  = fetch_latest_release()
        latest   = _parse_version_from_release(release)
        if _version_gt(latest, current):
            return {"current": current, "latest": latest}
    except Exception:
        pass

    return None


def _version_gt(a: str, b: str) -> bool:
    """Return True if version string a > version string b."""
    def _parts(v):
        return [int(x) for x in re.findall(r"\d+", v)]
    try:
        return _parts(a) > _parts(b)
    except Exception:
        return a > b


def update_engine(progress_cb=None) -> bool:
    """Download and install the latest engine, replacing the current one."""
    return install_engine(progress_cb=progress_cb)


# ---------------------------------------------------------------------------
# High-level public API (used by gui.py ONLY)
# ---------------------------------------------------------------------------

def get_config() -> Dict[str, Any]:
    """Public wrapper for _load_config."""
    return _load_config()


def save_config(data: Dict[str, Any]) -> None:
    """Public wrapper for _save_config."""
    _save_config(data)


def ensure_engine(timeout: float = 1.0) -> Optional[Dict[str, Any]]:
    """
    Perform up to 3 fast checks to find a working engine.
    Returns a status dict if found, None otherwise.
    Must complete within `timeout` seconds total.
    """
    deadline = time.monotonic() + timeout

    for attempt in range(3):
        if time.monotonic() >= deadline:
            break
        result = find_existing_engine()
        if result and result.get("valid"):
            return result
        if attempt < 2:
            time.sleep(0.05)   # tiny pause between attempts

    return None


def get_engine_status() -> Dict[str, Any]:
    """
    Return the current engine status dict.
    Keys: valid(bool), binary_path(str), version(str), arch(str), build(str)
    """
    cfg = _load_config()
    binary_path = cfg.get("stockfish_path", "")

    if binary_path:
        abs_path = binary_path if os.path.isabs(binary_path) else str(_BASE_DIR / binary_path)
        vj = _find_version_json_for(abs_path)
        if os.path.isfile(abs_path):
            return {
                "valid":       validate_engine(abs_path),
                "binary_path": abs_path,
                "version":     vj.get("version", "?") if vj else "?",
                "arch":        vj.get("arch",    "?") if vj else "?",
                "build":       vj.get("build",   "?") if vj else "?",
            }

    return {
        "valid":       False,
        "binary_path": "",
        "version":     "?",
        "arch":        "?",
        "build":       "?",
    }
