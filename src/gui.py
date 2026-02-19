"""
gui.py
======
Main PawnBit GUI.

Engine interaction is done exclusively via engine_manager high-level API:
  engine_manager.ensure_engine()
  engine_manager.get_engine_status()
  engine_manager.install_engine(progress_cb)
  engine_manager.update_engine(progress_cb)

No terminal logic. No download logic. No subprocess spawning here.
"""
# All UI strings are in English (international project).

import os
import sys
import threading
import time
import platform
import multiprocess
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path

# ── DPI AWARENESS (Windows) ───────────────────────────────
if sys.platform == "win32":
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

# ── HIDE CONSOLE WINDOW ───────────────────────────────────
if sys.platform == "win32":
    import subprocess
    _original_popen = subprocess.Popen
    def _silent_popen(*args, **kwargs):
        kwargs['creationflags'] = kwargs.get('creationflags', 0) | 0x08000000
        return _original_popen(*args, **kwargs)
    subprocess.Popen = _silent_popen

if getattr(sys, 'frozen', False):
    multiprocess.set_executable(sys.executable)

# Allow running from project root or src/
_SRC_DIR = Path(__file__).resolve().parent
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

# Asset directory: when frozen by PyInstaller assets land in sys._MEIPASS/assets
if getattr(sys, 'frozen', False):
    _BASE_DIR = Path(sys.executable).resolve().parent
    _ASSET_DIR = Path(sys._MEIPASS) / "assets"
else:
    _BASE_DIR = Path(__file__).resolve().parent.parent
    _ASSET_DIR = _SRC_DIR / "assets"

from overlay import run as run_overlay
from stockfish_bot import StockfishBot
import engine_manager

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service as ChromeService
    from webdriver_manager.chrome import ChromeDriverManager
    from selenium.common import WebDriverException
except ImportError:
    pass

try:
    import keyboard as kb
    _KEYBOARD_AVAILABLE = True
except ImportError:
    _KEYBOARD_AVAILABLE = False

def log_error(msg):
    """Write error to a log file for debugging frozen exe crashes."""
    try:
        log_path = Path(_BASE_DIR) / "error_log.txt"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{time.ctime()}] {msg}\n")
    except Exception:
        pass

# Redirect stdout/stderr to file if frozen
if getattr(sys, 'frozen', False):
    try:
        sys.stdout = open(_BASE_DIR / "output_log.txt", "a", encoding="utf-8")
        sys.stderr = open(_BASE_DIR / "error_log.txt", "a", encoding="utf-8")
    except Exception:
        pass


def kill_process_tree(pid):
    """Forcefully kill a process and all its children (Windows)."""
    if sys.platform == "win32" and pid:
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                creationflags=0x08000000
            )
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Engine Status Panel
# ---------------------------------------------------------------------------

class EngineStatusPanel(tk.Frame):
    """
    Displays Stockfish engine status.
    States:
      - checking   : grey spinner text
      - ok         : green checkmark + version info
      - offline    : yellow / orange – installed but not verified online
      - missing    : red – not found
      - update     : shows update banner
    """

    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self._state = "checking"

        # Status row
        status_row = tk.Frame(self)
        status_row.pack(fill=tk.X, anchor=tk.NW)

        tk.Label(status_row, text="Stockfish Status:", font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT)
        self._icon_label = tk.Label(status_row, text="⏳", font=("Segoe UI", 9))
        self._icon_label.pack(side=tk.LEFT, padx=(4, 0))
        self._info_label = tk.Label(status_row, text="Checking...", font=("Segoe UI", 9))
        self._info_label.pack(side=tk.LEFT, padx=(2, 0))

        # Update banner (hidden by default)
        self._update_frame = tk.Frame(self, bg="#FFF3CD", relief=tk.GROOVE, bd=1)
        self._update_label = tk.Label(
            self._update_frame, bg="#FFF3CD",
            text="", font=("Segoe UI", 8)
        )
        self._update_label.pack(side=tk.LEFT, padx=4)
        self._update_btn = tk.Button(
            self._update_frame, text="Update",
            font=("Segoe UI", 8), bd=1,
            command=self._on_update
        )
        self._update_btn.pack(side=tk.LEFT, padx=2)
        self._later_btn = tk.Button(
            self._update_frame, text="Later",
            font=("Segoe UI", 8), bd=1,
            command=self._on_later
        )
        self._later_btn.pack(side=tk.LEFT, padx=2)

        self._update_cb = None   # callback(install=True/False)

    # ------------------------------------------------------------------
    def set_checking(self):
        self._icon_label.config(text="⏳", fg="#888")
        self._info_label.config(text="Checking...", fg="#555")
        self._update_frame.pack_forget()

    def set_ok(self, version: str, build: str, arch: str):
        lbl = f"Version {version}"
        if build and build != "?":
            lbl += f" – {build.upper()}"
        if arch and arch != "?":
            lbl += f" – {arch}"
        self._icon_label.config(text="✓", fg="#2e7d32")
        self._info_label.config(text=lbl, fg="#2e7d32")
        self._update_frame.pack_forget()

    def set_offline(self, version: str):
        self._icon_label.config(text="✓", fg="#e65100")
        self._info_label.config(text=f"Version {version} [Offline – Update check skipped]", fg="#e65100")
        self._update_frame.pack_forget()

    def set_missing(self):
        self._icon_label.config(text="✗", fg="#c62828")
        self._info_label.config(text="Not found", fg="#c62828")
        self._update_frame.pack_forget()

    def show_update_banner(self, current: str, latest: str, callback):
        self._update_label.config(
            text=f"New version available ({latest}). Update now?"
        )
        self._update_cb = callback
        self._update_frame.pack(fill=tk.X, pady=(4, 0), padx=4)

    def hide_update_banner(self):
        self._update_frame.pack_forget()

    def _on_update(self):
        if self._update_cb:
            self._update_cb(install=True)

    def _on_later(self):
        self.hide_update_banner()
        if self._update_cb:
            self._update_cb(install=False)


# ---------------------------------------------------------------------------
# Engine Installation Dialog
# ---------------------------------------------------------------------------

class EngineInstallDialog(tk.Toplevel):
    """
    Modal dialog for installing Stockfish.
    Shows a progress bar and status messages during download.
    """

    def __init__(self, master, on_done_cb):
        super().__init__(master)
        self.title("Installing Stockfish")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()
        self._on_done_cb = on_done_cb
        self._cancelled = False

        tk.Label(self, text="Downloading and installing Stockfish...",
                 font=("Segoe UI", 10, "bold"), pady=10).pack()

        self._stage_label = tk.Label(self, text="Preparing...", font=("Segoe UI", 9))
        self._stage_label.pack()

        self._progress = ttk.Progressbar(self, orient="horizontal",
                                          mode="determinate", length=400)
        self._progress.pack(padx=20, pady=10)

        self._pct_label = tk.Label(self, text="0%", font=("Segoe UI", 9))
        self._pct_label.pack()

        cancel_btn = tk.Button(self, text="Cancel", command=self._cancel)
        cancel_btn.pack(pady=(0, 10))

        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self._start_install()

    def _cancel(self):
        self._cancelled = True
        self._on_done_cb(success=False, reason="Cancelled")
        self.destroy()

    def _start_install(self):
        def _worker():
            try:
                engine_manager.install_engine(progress_cb=self._progress_cb)
                if not self._cancelled:
                    self.after(0, self._install_done)
            except Exception as exc:  # noqa: BLE001
                # Capture exception message in a local variable so the lambda
                # closure doesn't try to read 'exc' after the except block ends
                # (which caused the NameError in Python 3.12+).
                err_msg = str(exc)
                if not self._cancelled:
                    self.after(0, lambda msg=err_msg: self._install_failed(msg))

        t = threading.Thread(target=_worker, daemon=True)
        t.start()

    def _progress_cb(self, stage: str, done: int, total: int):
        if self._cancelled:
            return
        stage_names = {
            "detect":   "Detecting system...",
            "fetch":    "Fetching release info...",
            "download": "Downloading archive...",
            "extract":  "Extracting archive...",
            "done":     "Installation complete.",
        }
        label_text = stage_names.get(stage, stage)
        if total > 0:
            pct = min(100, int(done / total * 100))
        elif stage == "done":
            pct = 100
        else:
            pct = 50  # indeterminate-ish

        def _update():
            if not self._cancelled:
                self._stage_label.config(text=label_text)
                self._progress["value"] = pct
                self._pct_label.config(text=f"{pct}%")

        self.after(0, _update)

    def _install_done(self):
        if not self._cancelled:
            self._on_done_cb(success=True, reason="")
            self.destroy()

    def _install_failed(self, reason: str):
        if not self._cancelled:
            self._on_done_cb(success=False, reason=reason)
            self.destroy()


# ---------------------------------------------------------------------------
# Engine-Not-Found Modal
# ---------------------------------------------------------------------------

def show_engine_not_found_dialog(master, on_auto_install, on_manual_select, on_cancel):
    """
    Modal popup shown after 3 failed engine checks.
    """
    dlg = tk.Toplevel(master)
    dlg.title("Stockfish Engine Not Found")
    dlg.resizable(False, False)
    dlg.transient(master)
    dlg.grab_set()
    dlg.attributes("-topmost", True)

    tk.Label(
        dlg,
        text="Stockfish Engine Not Found",
        font=("Segoe UI", 12, "bold"),
        pady=10
    ).pack()

    tk.Label(
        dlg,
        text="PawnBit could not detect a working Stockfish installation.\n"
             "Please choose an option:",
        font=("Segoe UI", 9),
        justify=tk.CENTER,
        wraplength=380,
        pady=4
    ).pack()

    btn_frame = tk.Frame(dlg)
    btn_frame.pack(pady=12)

    def _auto():
        dlg.destroy()
        on_auto_install()

    def _manual():
        dlg.destroy()
        on_manual_select()

    def _cancel():
        dlg.destroy()
        on_cancel()

    tk.Button(
        btn_frame, text="🔄  Install Automatically",
        font=("Segoe UI", 10), width=24, command=_auto, bg="#1565C0", fg="white", bd=0
    ).pack(pady=3)

    tk.Button(
        btn_frame, text="📁  Select Manually",
        font=("Segoe UI", 10), width=24, command=_manual, bg="#37474F", fg="white", bd=0
    ).pack(pady=3)

    tk.Button(
        btn_frame, text="❌  Cancel",
        font=("Segoe UI", 10), width=24, command=_cancel, bd=0
    ).pack(pady=3)

    dlg.protocol("WM_DELETE_WINDOW", _cancel)

    # Centre on parent
    dlg.update_idletasks()
    px = master.winfo_x() + master.winfo_width()  // 2 - dlg.winfo_width()  // 2
    py = master.winfo_y() + master.winfo_height() // 2 - dlg.winfo_height() // 2
    dlg.geometry(f"+{px}+{py}")


# ---------------------------------------------------------------------------
# Main GUI
# ---------------------------------------------------------------------------

class GUI:
    def __init__(self, master):
        self.master = master

        # State
        self.match_moves        = []
        self.exit               = False
        
        # Track active resources
        self.chrome             = None
        self.chrome_url         = None
        self.chrome_session_id  = None
        self.stockfish_bot_pipe = None
        self.stockfish_bot_process = None
        self.overlay_screen_process = None
        self.overlay_queue      = None
        self.restart_after_stopping = False

        # Engine path (resolved after detection)
        self.stockfish_path     = ""
        self._engine_status     = {}

        # Window
        master.title("PawnBit")
        master.geometry("")
        _icon_path = str(_ASSET_DIR / "pawn_32x32.png")
        if os.path.isfile(_icon_path):
            master.iconphoto(True, tk.PhotoImage(file=_icon_path))
        master.resizable(False, False)
        master.attributes("-topmost", True)
        master.protocol("WM_DELETE_WINDOW", self.on_close_listener)

        style = ttk.Style()
        style.theme_use("clam")

        # ── Left frame ────────────────────────────────────────────────────
        left_frame = tk.Frame(master)

        # Engine status panel (top)
        self.engine_panel = EngineStatusPanel(left_frame)
        self.engine_panel.pack(anchor=tk.NW, fill=tk.X, pady=(4, 6))
        self.engine_panel.set_checking()

        # Status
        status_label = tk.Frame(left_frame)
        tk.Label(status_label, text="Status:").pack(side=tk.LEFT)
        self.status_text = tk.Label(status_label, text="Inactive", fg="red")
        self.status_text.pack()
        status_label.pack(anchor=tk.NW)

        # Evaluation info
        self.eval_frame = tk.Frame(left_frame)
        eval_label = tk.Frame(self.eval_frame)
        tk.Label(eval_label, text="Eval:").pack(side=tk.LEFT)
        self.eval_text = tk.Label(eval_label, text="-")
        self.eval_text.pack()
        eval_label.pack(anchor=tk.NW)

        wdl_label = tk.Frame(self.eval_frame)
        tk.Label(wdl_label, text="WDL:").pack(side=tk.LEFT)
        self.wdl_text = tk.Label(wdl_label, text="-")
        self.wdl_text.pack()
        wdl_label.pack(anchor=tk.NW)

        material_label = tk.Frame(self.eval_frame)
        tk.Label(material_label, text="Material:").pack(side=tk.LEFT)
        self.material_text = tk.Label(material_label, text="-")
        self.material_text.pack()
        material_label.pack(anchor=tk.NW)

        white_acc_label = tk.Frame(self.eval_frame)
        tk.Label(white_acc_label, text="Bot Acc:").pack(side=tk.LEFT)
        self.white_acc_text = tk.Label(white_acc_label, text="-")
        self.white_acc_text.pack()
        white_acc_label.pack(anchor=tk.NW)

        black_acc_label = tk.Frame(self.eval_frame)
        tk.Label(black_acc_label, text="Opponent Acc:").pack(side=tk.LEFT)
        self.black_acc_text = tk.Label(black_acc_label, text="-")
        self.black_acc_text.pack()
        black_acc_label.pack(anchor=tk.NW)

        self.eval_frame.pack(anchor=tk.NW)

        # Website chooser
        self.website = tk.StringVar(value="chesscom")
        self.chesscom_radio_button = tk.Radiobutton(
            left_frame, text="Chess.com", variable=self.website, value="chesscom"
        )
        self.chesscom_radio_button.pack(anchor=tk.NW)
        self.lichess_radio_button = tk.Radiobutton(
            left_frame, text="Lichess.org", variable=self.website, value="lichess"
        )
        self.lichess_radio_button.pack(anchor=tk.NW)

        # Open browser
        self.opening_browser = False
        self.opened_browser  = False
        self.open_browser_button = tk.Button(
            left_frame, text="Open Browser",
            command=self.on_open_browser_button_listener,
        )
        self.open_browser_button.pack(anchor=tk.NW)

        # Start/Stop button
        self.running = False
        self.start_button = tk.Button(
            left_frame, text="Start", command=self.on_start_button_listener
        )
        self.start_button["state"] = "disabled"
        self.start_button.pack(anchor=tk.NW, pady=5)

        # Manual mode
        self.enable_manual_mode = tk.BooleanVar(value=False)
        self.manual_mode_checkbox = tk.Checkbutton(
            left_frame, text="Manual Mode",
            variable=self.enable_manual_mode,
            command=self.on_manual_mode_checkbox_listener,
        )
        self.manual_mode_checkbox.pack(anchor=tk.NW)

        self.manual_mode_frame = tk.Frame(left_frame)
        self.manual_mode_label = tk.Label(
            self.manual_mode_frame, text="\u2022 Press 3 to make a move"
        )
        self.manual_mode_label.pack(anchor=tk.NW)

        # Mouseless mode
        self.enable_mouseless_mode = tk.BooleanVar(value=False)
        self.mouseless_mode_checkbox = tk.Checkbutton(
            left_frame, text="Mouseless Mode", variable=self.enable_mouseless_mode
        )
        self.mouseless_mode_checkbox.pack(anchor=tk.NW)

        # Non-stop puzzles
        self.enable_non_stop_puzzles = tk.IntVar(value=0)
        self.non_stop_puzzles_check_button = tk.Checkbutton(
            left_frame, text="Non-stop puzzles", variable=self.enable_non_stop_puzzles
        )
        self.non_stop_puzzles_check_button.pack(anchor=tk.NW)

        # Non-stop matches
        self.enable_non_stop_matches = tk.IntVar(value=0)
        self.non_stop_matches_check_button = tk.Checkbutton(
            left_frame, text="Non-stop online matches",
            variable=self.enable_non_stop_matches
        )
        self.non_stop_matches_check_button.pack(anchor=tk.NW)

        # Bongcloud
        self.enable_bongcloud = tk.IntVar()
        self.bongcloud_check_button = tk.Checkbutton(
            left_frame, text="Bongcloud", variable=self.enable_bongcloud
        )
        self.bongcloud_check_button.pack(anchor=tk.NW)

        # Human-like Random Delay
        self.random_delay_enabled = tk.BooleanVar(value=False)
        self._random_delay_checkbox = tk.Checkbutton(
            left_frame,
            text="Human-like Random Delay",
            variable=self.random_delay_enabled,
            command=self._on_random_delay_toggle,
        )
        self._random_delay_checkbox.pack(anchor=tk.NW)

        # Min-delay sub-frame (shown only when checkbox is ticked)
        self._random_delay_frame = tk.Frame(left_frame)
        tk.Label(self._random_delay_frame, text="Min. delay (seconds)").pack(
            side=tk.LEFT
        )
        self.random_delay_min = tk.DoubleVar(value=0.0)
        self._random_delay_scale = tk.Scale(
            self._random_delay_frame, from_=0.0, to=10.0, resolution=0.1,
            orient=tk.HORIZONTAL, variable=self.random_delay_min, length=120
        )
        self._random_delay_scale.pack(side=tk.LEFT)

        # Mouse latency
        mouse_latency_frame = tk.Frame(left_frame)
        tk.Label(mouse_latency_frame, text="Mouse Latency (seconds)").pack(
            side=tk.LEFT, pady=(17, 0)
        )
        self.mouse_latency = tk.DoubleVar(value=0.0)
        self.mouse_latency_scale = tk.Scale(
            mouse_latency_frame, from_=0.0, to=15, resolution=0.2,
            orient=tk.HORIZONTAL, variable=self.mouse_latency
        )
        self.mouse_latency_scale.pack()
        mouse_latency_frame.pack(anchor=tk.NW)
        # Start hidden; _on_random_delay_toggle will show it when needed

        # Separator – Stockfish parameters
        self._add_separator(left_frame, "Stockfish parameters")

        # Slow mover
        slow_mover_frame = tk.Frame(left_frame)
        tk.Label(slow_mover_frame, text="Slow Mover").pack(side=tk.LEFT)
        self.slow_mover = tk.IntVar(value=100)
        tk.Entry(slow_mover_frame, textvariable=self.slow_mover, justify="center", width=8).pack()
        slow_mover_frame.pack(anchor=tk.NW)

        # Skill level
        skill_level_frame = tk.Frame(left_frame)
        tk.Label(skill_level_frame, text="Skill Level").pack(side=tk.LEFT, pady=(19, 0))
        self.skill_level = tk.IntVar(value=20)
        tk.Scale(
            skill_level_frame, from_=0, to=20, orient=tk.HORIZONTAL,
            variable=self.skill_level
        ).pack()
        skill_level_frame.pack(anchor=tk.NW)

        # Depth
        stockfish_depth_frame = tk.Frame(left_frame)
        tk.Label(stockfish_depth_frame, text="Depth").pack(side=tk.LEFT, pady=19)
        self.stockfish_depth = tk.IntVar(value=15)
        tk.Scale(
            stockfish_depth_frame, from_=1, to=20, orient=tk.HORIZONTAL,
            variable=self.stockfish_depth
        ).pack()
        stockfish_depth_frame.pack(anchor=tk.NW)

        # Memory
        memory_frame = tk.Frame(left_frame)
        tk.Label(memory_frame, text="Memory").pack(side=tk.LEFT)
        self.memory = tk.IntVar(value=512)
        tk.Entry(memory_frame, textvariable=self.memory, justify="center", width=9).pack(side=tk.LEFT)
        tk.Label(memory_frame, text="MB").pack()
        memory_frame.pack(anchor=tk.NW, pady=(0, 15))

        # CPU threads
        cpu_threads_frame = tk.Frame(left_frame)
        tk.Label(cpu_threads_frame, text="CPU Threads").pack(side=tk.LEFT)
        self.cpu_threads = tk.IntVar(value=1)
        tk.Entry(cpu_threads_frame, textvariable=self.cpu_threads, justify="center", width=7).pack()
        cpu_threads_frame.pack(anchor=tk.NW)

        # Separator – Misc
        self._add_separator(left_frame, "Misc", padx=82)

        # Always on top
        self.enable_topmost = tk.IntVar(value=1)
        tk.Checkbutton(
            left_frame, text="Window stays on top",
            variable=self.enable_topmost,
            command=self.on_topmost_check_button_listener,
        ).pack(anchor=tk.NW)

        left_frame.grid(row=0, column=0, padx=5, sticky=tk.NW)

        # ── Right frame ───────────────────────────────────────────────────
        right_frame = tk.Frame(master)

        treeview_frame = tk.Frame(right_frame)
        self.tree = ttk.Treeview(
            treeview_frame,
            column=("#", "White", "Black"),
            show="headings",
            height=23,
            selectmode="browse",
        )
        self.tree.pack(anchor=tk.NW, side=tk.LEFT)

        self.vsb = ttk.Scrollbar(treeview_frame, orient="vertical", command=self.tree.yview)
        self.vsb.pack(fill=tk.Y, expand=True)
        self.tree.configure(yscrollcommand=self.vsb.set)

        self.tree.column("# 1", anchor=tk.CENTER, width=35)
        self.tree.heading("# 1", text="#")
        self.tree.column("# 2", anchor=tk.CENTER, width=60)
        self.tree.heading("# 2", text="White")
        self.tree.column("# 3", anchor=tk.CENTER, width=60)
        self.tree.heading("# 3", text="Black")

        treeview_frame.pack(anchor=tk.NW)

        self.export_pgn_button = tk.Button(
            right_frame, text="Export PGN", command=self.on_export_pgn_button_listener
        )
        self.export_pgn_button.pack(anchor=tk.NW, fill=tk.X)

        right_frame.grid(row=0, column=1, sticky=tk.NW)

        # ── Background threads ────────────────────────────────────────────
        threading.Thread(target=self.process_checker_thread, daemon=True).start()
        threading.Thread(target=self.browser_checker_thread, daemon=True).start()
        threading.Thread(target=self.process_communicator_thread, daemon=True).start()
        if _KEYBOARD_AVAILABLE:
            threading.Thread(target=self.keypress_listener_thread, daemon=True).start()

        # ── Engine detection on startup (non-blocking) ───────────────────
        self._load_settings()
        threading.Thread(target=self._startup_engine_check, daemon=True).start()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _on_random_delay_toggle(self):
        """Show/hide the min-delay slider based on the checkbox state."""
        if self.random_delay_enabled.get():
            self._random_delay_frame.pack(anchor=tk.NW, padx=(16, 0), after=self._random_delay_checkbox)
        else:
            self._random_delay_frame.pack_forget()

    def _save_settings(self):
        """Persist UI settings to config.json."""
        try:
            cfg = engine_manager.get_config()
            cfg["website"]              = self.website.get()
            cfg["manual_mode"]          = self.enable_manual_mode.get()
            cfg["mouseless_mode"]       = self.enable_mouseless_mode.get()
            cfg["non_stop_puzzles"]      = self.enable_non_stop_puzzles.get()
            cfg["non_stop_matches"]      = self.enable_non_stop_matches.get()
            cfg["bongcloud"]            = self.enable_bongcloud.get()
            cfg["mouse_latency"]        = self.mouse_latency.get()
            cfg["random_delay_enabled"] = bool(self.random_delay_enabled.get())
            cfg["random_delay_min"]     = self.random_delay_min.get()
            cfg["slow_mover"]           = self.slow_mover.get()
            cfg["skill_level"]          = self.skill_level.get()
            cfg["depth"]                = self.stockfish_depth.get()
            cfg["memory"]               = self.memory.get()
            cfg["cpu_threads"]          = self.cpu_threads.get()
            cfg["topmost"]              = self.enable_topmost.get()
            engine_manager.save_config(cfg)
        except Exception:
            pass

    def _load_settings(self):
        """Load UI settings from config.json on startup."""
        cfg = engine_manager.get_config()
        if "website" in cfg:              self.website.set(cfg["website"])
        if "manual_mode" in cfg:          self.enable_manual_mode.set(cfg["manual_mode"])
        if "mouseless_mode" in cfg:       self.enable_mouseless_mode.set(cfg["mouseless_mode"])
        if "non_stop_puzzles" in cfg:      self.enable_non_stop_puzzles.set(cfg["non_stop_puzzles"])
        if "non_stop_matches" in cfg:      self.enable_non_stop_matches.set(cfg["non_stop_matches"])
        if "bongcloud" in cfg:            self.enable_bongcloud.set(cfg["bongcloud"])
        if "mouse_latency" in cfg:        self.mouse_latency.set(cfg["mouse_latency"])
        if "random_delay_enabled" in cfg: self.random_delay_enabled.set(cfg["random_delay_enabled"])
        if "random_delay_min" in cfg:     self.random_delay_min.set(cfg["random_delay_min"])
        if "slow_mover" in cfg:           self.slow_mover.set(cfg["slow_mover"])
        if "skill_level" in cfg:          self.skill_level.set(cfg["skill_level"])
        if "depth" in cfg:                self.stockfish_depth.set(cfg["depth"])
        if "memory" in cfg:               self.memory.set(cfg["memory"])
        if "cpu_threads" in cfg:          self.cpu_threads.set(cfg["cpu_threads"])
        if "topmost" in cfg:
            self.enable_topmost.set(cfg["topmost"])
            self.on_topmost_check_button_listener()

        # Refresh dependent UI visibility
        self.on_manual_mode_checkbox_listener()
        self._on_random_delay_toggle()

    def _add_separator(self, parent, text, padx=40):
        f = tk.Frame(parent)
        sep = ttk.Separator(f, orient="horizontal")
        sep.grid(row=0, column=0, sticky="ew")
        lbl = tk.Label(f, text=text)
        lbl.grid(row=0, column=0, padx=padx)
        f.pack(anchor=tk.NW, pady=10, expand=True, fill=tk.X)

    # ------------------------------------------------------------------
    # Engine detection / installation flow (all non-blocking)
    # ------------------------------------------------------------------

    def _startup_engine_check(self):
        """Run in background thread. Perform up to 3 fast engine checks."""
        # Increased timeout to 5.0s because Windows Defender can be slow
        result = engine_manager.ensure_engine(timeout=5.0)

        if result and result.get("valid"):
            self.stockfish_path = result["binary_path"]
            self._engine_status = result
            self.master.after(0, self._on_engine_found, result)
            # Async update check (fire-and-forget)
            threading.Thread(target=self._check_updates_async, daemon=True).start()
        else:
            self.master.after(0, self._on_engine_not_found)

    def _on_engine_found(self, status: dict):
        """GUI thread: engine successfully detected."""
        self.engine_panel.set_ok(
            version=status.get("version", "?"),
            build=status.get("build", "?"),
            arch=status.get("arch", "?"),
        )

    def _on_engine_not_found(self):
        """GUI thread: show the not-found popup after 3 failed checks."""
        self.engine_panel.set_missing()
        show_engine_not_found_dialog(
            self.master,
            on_auto_install=self._do_auto_install,
            on_manual_select=self._do_manual_select,
            on_cancel=self._do_cancel_engine,
        )

    def _do_auto_install(self):
        """Open the install dialog and run installation in background."""
        EngineInstallDialog(self.master, on_done_cb=self._on_install_done)

    def _on_install_done(self, success: bool, reason: str):
        """Called when the installation dialog finishes."""
        if success:
            status = engine_manager.get_engine_status()
            if status.get("valid"):
                self.stockfish_path = status["binary_path"]
                self._engine_status = status
                self.engine_panel.set_ok(
                    version=status.get("version", "?"),
                    build=status.get("build", "?"),
                    arch=status.get("arch", "?"),
                )
                messagebox.showinfo(
                    "Engine Installed",
                    f"Stockfish {status.get('version', '')} was installed successfully.",
                )
            else:
                messagebox.showerror(
                    "Error",
                    "Installation appeared successful, but the engine could not be validated."
                )
        else:
            if reason and reason != "Cancelled":
                messagebox.showerror(
                    "Installation Error",
                    f"Installation failed:\n{reason}"
                )

    def _do_manual_select(self):
        """Open file picker, validate selected binary, store it."""
        filetypes = [
            ("Executable files", "*.exe *.EXE stockfish stockfish*"),
            ("All files", "*.*"),
        ]
        path = filedialog.askopenfilename(
            title="Select Stockfish binary",
            filetypes=filetypes,
        )
        if not path:
            return

        from pathlib import Path as _P
        abs_path = str(_P(path).resolve())

        # Validate in a thread so GUI doesn't block
        def _validate():
            valid = engine_manager.validate_engine(abs_path)
            self.master.after(0, lambda: self._on_manual_validate(abs_path, valid))

        threading.Thread(target=_validate, daemon=True).start()

    def _on_manual_validate(self, abs_path: str, valid: bool):
        if not valid:
            messagebox.showerror(
                "Invalid Engine",
                "The selected file is not a valid UCI engine."
            )
            return

        # Try to read version
        try:
            import subprocess as _sp
            proc = _sp.Popen(
                [abs_path], stdin=_sp.PIPE, stdout=_sp.PIPE, stderr=_sp.PIPE, text=True,
                creationflags=0x08000000 if platform.system() == "Windows" else 0
            ) # CREATE_NO_WINDOW
            proc.stdin.write("uci\n")
            proc.stdin.flush()
            out = ""
            t0 = time.monotonic()
            while time.monotonic() - t0 < 1.0:
                line = proc.stdout.readline()
                out += line
                if "uciok" in line:
                    break
            proc.kill()
        except Exception:
            out = ""

        import re
        vm = re.search(r"Stockfish[_ ](\d+(?:\.\d+)*)", out, re.IGNORECASE)
        version = vm.group(1) if vm else "?"

        from pathlib import Path as _P
        version_dir_name = f"stockfish-{version}"
        version_dir = engine_manager._ENGINES_DIR / version_dir_name
        version_dir.mkdir(parents=True, exist_ok=True)

        # Copy the binary to the versioned dir if it's not already there
        dest_bin = version_dir / _P(abs_path).name
        if not dest_bin.exists():
            import shutil as _sh
            _sh.copy2(abs_path, dest_bin)

        # Relative path
        try:
            rel = dest_bin.relative_to(engine_manager._BASE_DIR)
            rel_str = str(rel).replace("\\", "/")
        except ValueError:
            rel_str = str(dest_bin)

        meta = {
            "version":     version,
            "arch":        engine_manager.detect_system()["arch"],
            "build":       "manual",
            "binary_path": rel_str,
        }
        engine_manager._write_version_json(version_dir, meta)

        cfg = engine_manager._load_config()
        cfg["stockfish_path"]    = rel_str
        cfg["stockfish_version"] = version
        engine_manager._save_config(cfg)

        self.stockfish_path = str(dest_bin)
        self._engine_status = engine_manager.get_engine_status()
        self.engine_panel.set_ok(version=version, build="manual", arch="?")

    def _do_cancel_engine(self):
        """User chose to cancel engine setup."""
        self.engine_panel.set_missing()

    def _check_updates_async(self):
        """Background thread: check for Stockfish updates."""
        try:
            info = engine_manager.check_for_updates()
            if info:
                self.master.after(
                    0,
                    lambda: self.engine_panel.show_update_banner(
                        info["current"], info["latest"],
                        self._on_update_banner_choice
                    )
                )
        except Exception:
            # Offline / rate-limited: show offline status
            status = self._engine_status
            self.master.after(
                0,
                lambda: self.engine_panel.set_offline(status.get("version", "?"))
            )

    def _on_update_banner_choice(self, install: bool):
        if install:
            EngineInstallDialog(self.master, on_done_cb=self._on_install_done)

    # ------------------------------------------------------------------
    # Window / lifecycle
    # ------------------------------------------------------------------

    def on_close_listener(self):
        """Called when the user clicks the X button."""
        self.exit = True
        self._cleanup_resources()
        # Give a moment for chrome.quit() and process kills to complete
        time.sleep(0.5)
        try:
            self.master.destroy()
        except Exception:
            pass
        # Hard exit to ensure all OS threads/processes are reclaimed
        os._exit(0)

    def _cleanup_resources(self):
        """Stop all background processes and close the browser."""
        # 1. Stop the bot and overlay
        self.on_stop_button_listener()

        # 2. Close the browser
        if self.chrome:
            try:
                self.chrome.quit()
            except Exception:
                pass
            self.chrome = None
            self.opened_browser = False
            self.opening_browser = False

    # ------------------------------------------------------------------
    # Background threads
    # ------------------------------------------------------------------

    def process_checker_thread(self):
        while not self.exit:
            if (
                self.running
                and self.stockfish_bot_process is not None
                and not self.stockfish_bot_process.is_alive()
            ):
                self.on_stop_button_listener()
                if self.restart_after_stopping:
                    self.restart_after_stopping = False
                    self.on_start_button_listener()
            time.sleep(0.1)

    def browser_checker_thread(self):
        """Checks if the browser window has been closed by the user."""
        while not self.exit:
            if self.opened_browser and self.chrome is not None:
                try:
                    # Simple check: if window_handles is empty or raises Exception, browser is gone
                    _ = self.chrome.window_handles
                except Exception:
                    # Browser was closed
                    self.opened_browser = False
                    self.master.after(0, self._on_browser_closed_externally)
            time.sleep(0.5)

    def _on_browser_closed_externally(self):
        """GUI thread: handle external browser closure."""
        self.open_browser_button["text"] = "Open Browser"
        self.open_browser_button["state"] = "normal"
        self.on_stop_button_listener()
        self.chrome = None

    def process_communicator_thread(self):
        while not self.exit:
            try:
                if (
                    self.stockfish_bot_pipe is not None
                    and self.stockfish_bot_pipe.poll()
                ):
                    data = self.stockfish_bot_pipe.recv()
                    if data == "START":
                        self.clear_tree()
                        self.match_moves = []
                        self.status_text["text"] = "Running"
                        self.status_text["fg"] = "green"
                        self.status_text.update()
                        self.start_button["text"] = "Stop"
                        self.start_button["state"] = "normal"
                        self.start_button["command"] = self.on_stop_button_listener
                        self.start_button.update()
                    elif data[:7] == "RESTART":
                        self.restart_after_stopping = True
                        self.stockfish_bot_pipe.send("DELETE")
                    elif data[:6] == "S_MOVE":
                        move = data[6:]
                        self.match_moves.append(move)
                        self.insert_move(move)
                        self.tree.yview_moveto(1)
                    elif data[:6] == "M_MOVE":
                        moves = data[6:].split(",")
                        self.match_moves += moves
                        self.set_moves(moves)
                        self.tree.yview_moveto(1)
                    elif data[:5] == "EVAL|":
                        parts = data.split("|")
                        if len(parts) >= 5:
                            eval_str, wdl_str, material_str, bot_acc, opp_acc = parts[1:]
                            self.update_evaluation_display(eval_str, wdl_str, material_str, bot_acc, opp_acc)
                    elif data[:7] == "ERR_EXE":
                        messagebox.showerror("Error", "Stockfish path provided is not valid!")
                    elif data[:8] == "ERR_PERM":
                        messagebox.showerror("Error", "Stockfish path provided is not executable!")
                    elif data[:9] == "ERR_BOARD":
                        messagebox.showerror("Error", "Cant find board!")
                    elif data[:9] == "ERR_COLOR":
                        messagebox.showerror("Error", "Cant find player color!")
                    elif data[:9] == "ERR_MOVES":
                        messagebox.showerror("Error", "Cant find moves list!")
                    elif data[:12] == "ERR_GAMEOVER":
                        messagebox.showerror("Error", "Game has already finished!")
            except (BrokenPipeError, OSError):
                self.stockfish_bot_pipe = None

            time.sleep(0.1)

    def keypress_listener_thread(self):
        while not self.exit:
            time.sleep(0.1)
            if not self.opened_browser:
                continue
            if _KEYBOARD_AVAILABLE:
                try:
                    if kb.is_pressed("1"):
                        self.on_start_button_listener()
                    elif kb.is_pressed("2"):
                        self.on_stop_button_listener()
                except Exception:
                    # Keyboard hook might fail without admin rights or in certain envs
                    pass

    # ------------------------------------------------------------------
    # Button listeners
    # ------------------------------------------------------------------

    def on_open_browser_button_listener(self):
        self.opening_browser = True
        self.open_browser_button["text"] = "Opening Browser..."
        self.open_browser_button["state"] = "disabled"
        self.open_browser_button.update()

        try:
            options = webdriver.ChromeOptions()
            options.add_experimental_option(
                "excludeSwitches", ["enable-logging", "enable-automation"]
            )
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_experimental_option("useAutomationExtension", False)

            chrome_install = ChromeDriverManager().install()
            folder = os.path.dirname(chrome_install)
            chromedriver_path = os.path.join(folder, "chromedriver.exe")
            from selenium.webdriver.chrome.service import Service as ChromeService
            service = ChromeService(chromedriver_path)
            if sys.platform == "win32":
                service.creationflags = 0x08000000
            self.chrome = webdriver.Chrome(service=service, options=options)
        except WebDriverException:
            self._reset_browser_button()
            messagebox.showerror(
                "Error",
                "Cant find Chrome. You need to have Chrome installed for this to work.",
            )
            return
        except Exception as e:
            self._reset_browser_button()
            messagebox.showerror("Error", f"An error occurred while opening the browser: {e}")
            return

        if self.website.get() == "chesscom":
            self.chrome.get("https://www.chess.com")
        else:
            self.chrome.get("https://www.lichess.org")

        self.chrome_url        = self.chrome.service.service_url
        self.chrome_session_id = self.chrome.session_id

        self.opening_browser = False
        self.opened_browser  = True
        self.open_browser_button["text"] = "Browser is open"
        self.open_browser_button["state"] = "disabled"
        self.open_browser_button.update()

        self.start_button["state"] = "normal"
        self.start_button.update()

    def _reset_browser_button(self):
        self.opening_browser = False
        self.open_browser_button["text"] = "Open Browser"
        self.open_browser_button["state"] = "normal"
        self.open_browser_button.update()

    def on_start_button_listener(self):
        try:
            slow_mover = self.slow_mover.get()
            if slow_mover < 10 or slow_mover > 1000:
                raise ValueError
        except (ValueError, tk.TclError):
            messagebox.showerror("Error", "Slow Mover must be between 10 and 1000")
            return

        try:
            mem = self.memory.get()
            if mem < 16: raise ValueError
        except (ValueError, tk.TclError):
            messagebox.showerror("Error", "Memory (Hash) must be at least 16 MB")
            return

        try:
            thr = self.cpu_threads.get()
            if thr < 1: raise ValueError
            # Heuristic: Warn if threads > logical cores
            import os as _os
            cores = _os.cpu_count() or 1
            if thr > cores:
                if not messagebox.askyesno("Performance Warning", 
                    f"You have selected {thr} threads, but your system only has {cores} logical cores.\n"
                    "This may cause lag. Do you want to continue?"):
                    return
        except (ValueError, tk.TclError):
            messagebox.showerror("Error", "Threads must be at least 1")
            return

        # Persist these settings before starting
        self._save_settings()

        if not self.stockfish_path or not os.path.isfile(self.stockfish_path):
            # Try one more time to resolve from config
            status = engine_manager.get_engine_status()
            if status.get("valid"):
                self.stockfish_path = status["binary_path"]
            else:
                messagebox.showerror(
                    "Engine Missing",
                    "No valid Stockfish path found. Please install the engine first."
                )
                return

        parent_conn, child_conn = multiprocess.Pipe()
        self.stockfish_bot_pipe = parent_conn
        st_ov_queue = multiprocess.Queue()
        self.overlay_queue = st_ov_queue # Store for cleanup

        self.stockfish_bot_process = StockfishBot(
            self.chrome_url,
            self.chrome_session_id,
            self.website.get(),
            child_conn,
            st_ov_queue,
            self.stockfish_path,
            self.enable_manual_mode.get() == 1,
            self.enable_mouseless_mode.get() == 1,
            self.enable_non_stop_puzzles.get() == 1,
            self.enable_non_stop_matches.get() == 1,
            self.mouse_latency.get(),
            self.enable_bongcloud.get() == 1,
            self.slow_mover.get(),
            self.skill_level.get(),
            self.stockfish_depth.get(),
            self.memory.get(),
            self.cpu_threads.get(),
            random_delay_enabled=self.random_delay_enabled.get(),
            random_delay_min=self.random_delay_min.get(),
        )
        self.stockfish_bot_process.start()

        self.overlay_screen_process = multiprocess.Process(
            target=run_overlay, args=(st_ov_queue,)
        )
        self.overlay_screen_process.start()

        self.running = True
        self.start_button["text"]  = "Starting..."
        self.start_button["state"] = "disabled"
        self.start_button.update()

    def on_stop_button_listener(self):
        if self.stockfish_bot_process is not None:
            # 1. Try graceful stop
            try:
                if self.stockfish_bot_pipe:
                    self.stockfish_bot_pipe.send("STOP")
            except Exception:
                pass
            
            # 2. Tell overlay to stop
            try:
                # We need a reference to the queue we passed to overlay
                # I'll store it as self.overlay_queue
                if hasattr(self, 'overlay_queue') and self.overlay_queue:
                    self.overlay_queue.put("STOP")
            except Exception:
                pass

            if self.overlay_screen_process is not None:
                try:
                    self.overlay_screen_process.terminate()
                    self.overlay_screen_process.join(timeout=0.5)
                    if self.overlay_screen_process.is_alive():
                        kill_process_tree(self.overlay_screen_process.pid)
                except Exception:
                    pass
                self.overlay_screen_process = None

            if self.stockfish_bot_process.is_alive():
                self.stockfish_bot_process.join(timeout=1.5)
                if self.stockfish_bot_process.is_alive():
                    # If it's still alive, it means the graceful stop failed
                    # or it's hung. Kill it and its child (Stockfish engine).
                    kill_process_tree(self.stockfish_bot_process.pid)
            self.stockfish_bot_process = None

        if self.stockfish_bot_pipe is not None:
            self.stockfish_bot_pipe.close()
            self.stockfish_bot_pipe = None

        self.running = False
        self.status_text["text"] = "Inactive"
        self.status_text["fg"]   = "red"
        self.status_text.update()

        self.eval_text["text"]      = "-"
        self.eval_text["fg"]        = "black"
        self.wdl_text["text"]       = "-"
        self.material_text["text"]  = "-"
        self.material_text["fg"]    = "black"
        self.white_acc_text["text"] = "-"
        self.black_acc_text["text"] = "-"

        for w in (self.eval_text, self.wdl_text, self.material_text,
                  self.white_acc_text, self.black_acc_text):
            w.update()

        if not self.restart_after_stopping:
            self.start_button["text"]    = "Start"
            self.start_button["state"]   = "normal"
            self.start_button["command"] = self.on_start_button_listener
        else:
            self.restart_after_stopping = False
            self.on_start_button_listener()
        self.start_button.update()

    def on_topmost_check_button_listener(self):
        self.master.attributes("-topmost", self.enable_topmost.get() == 1)

    def on_export_pgn_button_listener(self):
        f = filedialog.asksaveasfile(
            initialfile="match.pgn",
            defaultextension=".pgn",
            filetypes=[("Portable Game Notation", "*.pgn"), ("All Files", "*.*")],
        )
        if f is None:
            return
        data = ""
        for i in range(len(self.match_moves) // 2 + 1):
            if len(self.match_moves) % 2 == 0 and i == len(self.match_moves) // 2:
                continue
            data += str(i + 1) + ". "
            data += self.match_moves[i * 2] + " "
            if (i * 2) + 1 < len(self.match_moves):
                data += self.match_moves[i * 2 + 1] + " "
        f.write(data)
        f.close()

    def on_manual_mode_checkbox_listener(self):
        if self.enable_manual_mode.get() == 1:
            self.manual_mode_frame.pack(after=self.manual_mode_checkbox)
            self.manual_mode_frame.update()
        else:
            self.manual_mode_frame.pack_forget()
            self.manual_mode_checkbox.update()

    # ------------------------------------------------------------------
    # Treeview helpers
    # ------------------------------------------------------------------

    def clear_tree(self):
        self.tree.delete(*self.tree.get_children())
        self.tree.update()

    def insert_move(self, move):
        cells_num = sum(
            [len(self.tree.item(i)["values"]) - 1 for i in self.tree.get_children()]
        )
        if (cells_num % 2) == 0:
            rows_num = len(self.tree.get_children())
            self.tree.insert("", "end", text="1", values=(rows_num + 1, move))
        else:
            self.tree.set(self.tree.get_children()[-1], column=2, value=move)
        self.tree.update()

    def set_moves(self, moves):
        self.clear_tree()
        pairs = list(zip(*[iter(moves)] * 2))
        for i, pair in enumerate(pairs):
            self.tree.insert("", "end", text="1", values=(str(i + 1), pair[0], pair[1]))
        if len(moves) % 2 == 1:
            self.tree.insert("", "end", text="1", values=(len(pairs) + 1, moves[-1]))
        self.tree.update()

    # ------------------------------------------------------------------
    # Evaluation display
    # ------------------------------------------------------------------

    def update_evaluation_display(self, eval_str, wdl_str, material_str, bot_acc, opponent_acc):
        self.eval_text["text"] = eval_str
        try:
            if eval_str.startswith("M"):
                mate_value = int(eval_str[1:])
                self.eval_text["fg"] = "green" if mate_value > 0 else "red"
            else:
                eval_value = float(eval_str)
                self.eval_text["fg"] = (
                    "green" if eval_value > 0 else ("black" if eval_value == 0 else "red")
                )
        except ValueError:
            self.eval_text["fg"] = "black"

        self.wdl_text["text"]      = wdl_str
        self.material_text["text"] = material_str

        try:
            if material_str.startswith("+"):
                self.material_text["fg"] = "green"
            elif material_str.startswith("-"):
                self.material_text["fg"] = "red"
            else:
                self.material_text["fg"] = "black"
        except Exception:
            self.material_text["fg"] = "black"

        self.white_acc_text["text"] = bot_acc
        self.black_acc_text["text"] = opponent_acc

        for w in (self.eval_text, self.wdl_text, self.material_text,
                  self.white_acc_text, self.black_acc_text):
            w.update()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    multiprocess.freeze_support()
    
    # Global exception handler for the GUI
    def handle_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        err_msg = f"Uncaught exception: {exc_type.__name__}: {exc_value}"
        log_error(err_msg)
        # Also print to stderr if not frozen
        if not getattr(sys, 'frozen', False):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)

    sys.excepthook = handle_exception

    window = tk.Tk()
    my_gui = GUI(window)
    window.mainloop()
