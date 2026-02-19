# PawnBit

<a target="_blank" href="https://www.paypal.com/donate/?hosted_button_id=J65KNQYEK88ML">
  <img src="https://img.shields.io/badge/Donate-PayPal-green.svg">
</a>

A powerful bot for chess.com and lichess.org that automatically plays chess for you with human-like behavior and advanced engine management.

Chess.com  
![](match_chesscom.gif)

Lichess.org  
![](match_lichess.gif)  
_Note: The mouse is moved by Python in standard mode._

## 🚀 Features

- **Multi-Platform Support**: Windows, Linux, and macOS.
- **Auto-Engine Management**: Stockfish 18 is bundled with the executable. No manual download required for fresh installs.
- **Human-like Behavior**:
  - **Random Delays**: Simulates human thinking time with configurable minimum delays.
  - **Mouse Latency**: Adjustable movement speed.
- **Gameplay Modes**:
  - **Auto Mode**: Full automatic play.
  - **Manual Mode**: Visualizes moves via an overlay; press `3` to execute the move.
  - **Mouseless Mode**: Injects moves directly (works in background).
  - **Non-stop Mode**: Automatically cues into the next match or puzzle.
- **Smart Analytics**:
  - Real-time evaluation bar and W/D/L stats.
  - Material advantage tracking.
  - Accuracy estimation for you and your opponent.
- **Customizable Engine**: Control Depth, Skill Level, Memory (Hash), and CPU Threads.
- **Settings Persistence**: Your configuration is automatically saved and loaded.

## 📥 Installation

### 1. Download (Recommended)

Download the latest pre-built executable from the [Releases](../../releases) page.

- **Windows**: Run `PawnBit-windows.exe`. Stockfish is included!
- **macOS/Linux**: Download the binary, run `chmod +x PawnBit-platform` and execute.

### 2. From Source

1. Clone the repository: `git clone https://github.com/sayrox106/PawnBit.git`
2. Open a terminal in the folder.
3. Setup virtual environment:
   - **Windows**: `python -m venv venv` then `venv\Scripts\pip install -r requirements.txt`
   - **Linux/macOS**: `python3 -m venv venv` then `venv/bin/pip3 install -r requirements.txt`
4. Run:
   - **Windows**: `venv\Scripts\python.exe src\gui.py`
   - **Linux/macOS**: `venv/bin/python3 src/gui.py`

## 🎮 How to Use

1. **Open Browser**: Click the button to launch a controlled Chrome instance.
2. **Navigate**: Go to a live match or puzzle on Chess.com or Lichess.
3. **Configure**: Adjust your Skill Level, Depth, and Delays in the GUI.
4. **Start**: Click **Start** (or press `1`).
5. **Stop**: Click **Stop** (or press `2`) at any time.

## 🛠 Supported Sites & Modes

| Feature             | Chess.com | Lichess.org |
| ------------------- | :-------: | :---------: |
| Online Matches      |    ✅     |     ✅      |
| Puzzles             |    ✅     |     ✅      |
| Non-stop Mode       |    ✅     |     ✅      |
| Mouseless Injection |    ✅     |     ✅      |

## ⚠️ Disclaimer

Under no circumstances should you use this bot to cheat in online games or tournaments. This bot was made for **educational purposes only**. Using this bot to cheat in online games or tournaments is against the rules of chess platforms and will result in a ban. The developers are not responsible for any banned accounts.
