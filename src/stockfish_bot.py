import threading
import time
import platform
import random
import re

import subprocess
import chess
import pyautogui
import keyboard
from stockfish import Stockfish
from grabbers.chesscom_grabber import ChesscomGrabber
from grabbers.lichess_grabber import LichessGrabber
from selenium.common.exceptions import WebDriverException



class StockfishBot(threading.Thread):
    def __init__(
        self,
        chrome_url, chrome_session_id, website, bot_to_gui_queue, gui_to_bot_queue, overlay_queue,
        stockfish_path, enable_manual_mode, enable_mouseless_mode,
        enable_non_stop_puzzles, enable_non_stop_matches,
        mouse_latency, bongcloud, slow_mover, skill_level,
        stockfish_depth, memory, cpu_threads,
        random_delay_enabled=False,
        random_delay_min=0.0,
    ):
        threading.Thread.__init__(self)

        self.chrome_url = chrome_url
        self.chrome_session_id = chrome_session_id
        self.website = website
        self.bot_to_gui_queue = bot_to_gui_queue
        self.gui_to_bot_queue = gui_to_bot_queue
        self.overlay_queue = overlay_queue
        self.stockfish_path = stockfish_path
        self.enable_manual_mode = enable_manual_mode
        self.enable_mouseless_mode = enable_mouseless_mode
        self.enable_non_stop_puzzles = enable_non_stop_puzzles
        self.enable_non_stop_matches = enable_non_stop_matches
        self.mouse_latency = mouse_latency
        self.bongcloud = bongcloud
        self.slow_mover = slow_mover
        self.skill_level = skill_level
        self.stockfish_depth = stockfish_depth
        self.grabber = None
        self.memory = memory
        self.cpu_threads = cpu_threads
        self.is_white = None
        # Random human-like delay:
        #   if enabled, sleep random(min, min + extra) before each bot move.
        self.random_delay_enabled = bool(random_delay_enabled)
        self.random_delay_min = max(0.0, float(random_delay_min))

    # ------------------------------------------------------------------
    # Safe pipe send (swallows BrokenPipeError if GUI already closed)
    # ------------------------------------------------------------------

    def _send(self, msg):
        self.bot_to_gui_queue.put(msg)

    # ------------------------------------------------------------------
    # Coordinate helpers
    # ------------------------------------------------------------------

    def get_board_geometry(self):
        """Retrieve current board position and scale factors."""
        try:
            board = self.grabber.get_board()
            if not board: return None
            
            # 1. Get browser window offsets (accounting for title bars / borders)
            canvas_x, canvas_y = self.grabber.get_top_left_corner()
            
            # 2. Get board rect relative to viewport
            rect = board.rect
            
            # 3. Calculate absolute screen coordinates for the board
            # square_size is based on the current element width
            square_size = rect['width'] / 8
            
            return {
                'x': canvas_x + rect['x'],
                'y': canvas_y + rect['y'],
                'w': rect['width'],
                'h': rect['height'],
                'sq': square_size
            }
        except Exception:
            return None

    def move_to_screen_pos(self, sq_name, geo):
        """Convert 'e2' to screen (x, y) based on current geometry."""
        files = "abcdefgh"
        f = files.index(sq_name[0])
        r = int(sq_name[1]) - 1
        
        sq_size = geo['sq']
        if self.is_white:
            rel_x = (f + 0.5) * sq_size
            rel_y = (7 - r + 0.5) * sq_size
        else:
            rel_x = (7 - f + 0.5) * sq_size
            rel_y = (r + 0.5) * sq_size
            
        return geo['x'] + rel_x, geo['y'] + rel_y

    # ------------------------------------------------------------------
    # Move execution
    # ------------------------------------------------------------------

    def apply_random_delay(self):
        """Sleep a random amount: between random_delay_min and min+5 seconds."""
        if self.random_delay_enabled:
            extra = random.uniform(0.0, 5.0)
            delay = self.random_delay_min + extra
            if delay > 0:
                time.sleep(delay)

    def make_move(self, move):
        geo = self.get_board_geometry()
        if not geo: return
        
        start_x, start_y = self.move_to_screen_pos(move[0:2], geo)
        end_x, end_y = self.move_to_screen_pos(move[2:4], geo)
        
        pyautogui.moveTo(start_x, start_y)
        time.sleep(self.mouse_latency)
        pyautogui.dragTo(end_x, end_y)

        if len(move) == 5: # Promotion
            time.sleep(0.1)
            # Simplistic promotion click logic (assumes queen is on the target square or adjacent)
            pyautogui.click()

    # ------------------------------------------------------------------
    # Control flow helpers
    # ------------------------------------------------------------------

    def wait_for_gui_to_delete(self):
        try:
            while self.gui_to_bot_queue.get() != "DELETE":
                pass
        except Exception:
            pass

    def go_to_next_puzzle(self):
        self.grabber.click_puzzle_next()
        self._send("RESTART")
        self.wait_for_gui_to_delete()

    def find_new_online_match(self):
        time.sleep(2)
        self.grabber.click_game_next()
        self._send("RESTART")
        self.wait_for_gui_to_delete()

    # ------------------------------------------------------------------
    # Main run loop
    # ------------------------------------------------------------------

    def run(self):  # sourcery skip: extract-duplicate-method, switch, use-fstring-for-concatenation
        # ── HIDE CONSOLE WINDOW ───────────────────────────────────
        if platform.system() == "Windows":
            _original_popen = subprocess.Popen
            class _LocalSilentPopen(_original_popen):
                def __init__(self, *args, **kwargs):
                    kwargs['creationflags'] = kwargs.get('creationflags', 0) | 0x08000000
                    super().__init__(*args, **kwargs)
            subprocess.Popen = _LocalSilentPopen

        if self.website == "chesscom":
            self.grabber = ChesscomGrabber(self.chrome_url, self.chrome_session_id)
        else:
            self.grabber = LichessGrabber(self.chrome_url, self.chrome_session_id)

        self.grabber.reset_moves_list()

        parameters = {
            "Threads": self.cpu_threads,
            "Hash": self.memory,
            "Ponder": True,  # Changed from "true" to True for newer stockfish-python versions
            "Slow Mover": self.slow_mover,
            "Skill Level": self.skill_level,
        }
        # ── Stockfish Initialization ───────────────────────────────
        try:
            # 1. Quick pre-validation: check if binary is UCI-responsive
            import subprocess as _sp
            proc = _sp.Popen([self.stockfish_path], stdin=_sp.PIPE, stdout=_sp.PIPE, stderr=_sp.PIPE, text=True, creationflags=0x08000000) # CREATE_NO_WINDOW
            proc.stdin.write("uci\n")
            proc.stdin.flush()
            responsive = False
            t0 = time.monotonic()
            while time.monotonic() - t0 < 3.0: # 3s timeout for responsive check
                line = proc.stdout.readline()
                if "uciok" in line:
                    responsive = True
                    break
            proc.kill()
            if not responsive:
                self._send("ERR_EXE")
                return

            # 2. Actual library initialization
            stockfish = Stockfish(
                path=self.stockfish_path,
                depth=self.stockfish_depth,
                parameters=parameters,
            )
        except (PermissionError, PermissionError):
            self._send("ERR_PERM")
            return
        except (OSError, RuntimeError, ValueError) as e:
            err_msg = str(e)
            print(f"Stockfish Init Error: {err_msg}")
            # Send the specific error message to the GUI
            self._send(f"ERR_EXE:{err_msg}")
            return

        try:
            self.grabber.update_board_elem(stop_queue=self.gui_to_bot_queue)
            if self.grabber.get_board() is None:
                self._send("ERR_BOARD")
                return

            self.is_white = self.grabber.is_white()
            if self.is_white is None:
                self._send("ERR_COLOR")
                return

            move_list = self.grabber.get_move_list()
            if move_list is None:
                self._send("ERR_MOVES")
                return

            score_pattern = r"([0-9]+)\-([0-9]+)"
            if len(move_list) > 0 and re.match(score_pattern, move_list[-1]):
                self._send("ERR_GAMEOVER")
                return

            board = chess.Board()
            for move in move_list:
                board.push_san(move)
            
            # Use set_fen_position as set_position is not available in this version
            stockfish.set_fen_position(board.fen())

            white_moves, white_best_moves = [], []
            black_moves, black_best_moves = [], []

            self.send_eval_data(stockfish, board)
            self._send("START")

            if len(move_list) > 0:
                self._send("M_MOVE" + ",".join(move_list))

            # Performance Cache
            last_geo = None
            last_geo_time = 0

            while True:
                # ── 1. CHECK STOP SIGNAL ──────────────────────────────
                if not self.gui_to_bot_queue.empty():
                    try:
                        if self.gui_to_bot_queue.get_nowait() == "STOP":
                            break
                    except Exception:
                        pass

                # ── 2. PROACTIVE SYNC FROM WEBSITE ────────────────────
                try:
                    new_site_moves = self.grabber.get_move_list()
                except (WebDriverException, Exception):
                    print("Browser connection lost. Stopping bot thread.")
                    break

                if new_site_moves is not None:
                    # Detect New Game (0 moves on site, but we have a history)
                    # We only reset if we were already in a game (e.g. at least 3 moves total)
                    # to avoid "false resets" at the very beginning of a match when the site is slow.
                    if len(new_site_moves) == 0 and len(board.move_stack) > 2:
                        # Double-check: sometimes site returns [] for a split second on lag
                        time.sleep(0.5) # Lag protection
                        recheck = self.grabber.get_move_list()
                        if recheck is not None and len(recheck) == 0:
                            print(f"New game confirmed. Resetting state.")
                            board = chess.Board()
                            stockfish.set_fen_position(board.fen())
                            white_moves, white_best_moves = [], []
                            black_moves, black_best_moves = [], []
                            move_list = []
                            self.is_white = self.grabber.is_white()
                            self._send("RESTART")
                            self.send_eval_data(stockfish, board)
                            self._send("START")
                    
                    # Detect New Moves (Opponent or missing history)
                    elif len(new_site_moves) > len(board.move_stack):
                        for i in range(len(board.move_stack), len(new_site_moves)):
                            san_move = new_site_moves[i]
                            try:
                                # Ensure move is valid before pushing
                                move_uci = board.parse_san(san_move).uci()
                                if board.turn == chess.WHITE: white_moves.append(move_uci)
                                else: black_moves.append(move_uci)
                                board.push_san(san_move)
                            except Exception:
                                break
                        stockfish.set_fen_position(board.fen())
                        move_list = new_site_moves.copy()
                        # Only send heavy eval data if GUI is active
                        self.send_eval_data(stockfish, board, white_moves=white_moves, white_best_moves=white_best_moves, black_moves=black_moves, black_best_moves=black_best_moves)
                        if move_list: self._send("S_MOVE" + move_list[-1])

                # ── 3. GAME OVER CHECK ────────────────────────────────
                if board.is_game_over() or self.grabber.is_game_over():
                    if self.enable_non_stop_puzzles and self.grabber.is_game_puzzles():
                        self.go_to_next_puzzle()
                        time.sleep(1) # Wait for reload
                        continue 
                    elif self.enable_non_stop_matches and not self.enable_non_stop_puzzles:
                        self.find_new_online_match()
                        time.sleep(1)
                        continue
                    else:
                        print("Game over detected. Stopping bot thread.")
                        break

                # ── 4. BOT'S TURN LOGIC ───────────────────────────────
                is_turn = (self.is_white and board.turn == chess.WHITE) or (
                    not self.is_white and board.turn == chess.BLACK
                )

                if is_turn:
                    # Sync check before moving (faster)
                    site_moves = self.grabber.get_move_list()
                    if site_moves is not None and len(site_moves) != len(board.move_stack):
                        continue

                    # Thinking...
                    move = None
                    if self.bongcloud:
                        move_count = len(board.move_stack) // 2
                        if move_count == 0: move = "e2e4" if board.turn == chess.WHITE else "e7e5"
                        elif move_count == 1: move = "d2d4" if board.turn == chess.WHITE else "d7d5"
                        
                        if move and not board.is_legal(chess.Move.from_uci(move)): move = None
                    
                    if move is None:
                        try:
                            # Use current state
                            move = stockfish.get_best_move()
                        except Exception: break

                    if move is None: break

                    # Stats
                    if board.turn == chess.WHITE: white_best_moves.append(move)
                    else: black_best_moves.append(move)

                    # Humanity delay
                    self.apply_random_delay()

                    # Move Execution
                    move_san = board.san(chess.Move.from_uci(move))
                    if self.enable_manual_mode:
                        # Cache geometry for manual mod arrows (refresh every 3s)
                        if not last_geo or time.time() - last_geo_time > 3:
                            last_geo = self.get_board_geometry()
                            last_geo_time = time.time()
                        
                        if last_geo:
                            sx, sy = self.move_to_screen_pos(move[0:2], last_geo)
                            ex, ey = self.move_to_screen_pos(move[2:4], last_geo)
                            self.overlay_queue.put([((int(sx), int(sy)), (int(ex), int(ey)))])
                        
                        while not keyboard.is_pressed("3"):
                            if self.grabber.get_move_list() and len(self.grabber.get_move_list()) > len(board.move_stack):
                                break
                            time.sleep(0.05)
                    else:
                        # Rapid execution
                        success = False
                        if self.enable_mouseless_mode and not self.grabber.is_game_puzzles():
                            success = self.grabber.make_mouseless_move(
                                move, 
                                len(board.move_stack), 
                                human_like=self.random_delay_enabled
                            )
                        else:
                            # Re-verify geometry only for mouse moves
                            geo = self.get_board_geometry()
                            if geo:
                                self.make_move(move) # Now uses geometry inside internally
                                success = True

                        if success:
                            if board.turn == chess.WHITE: white_moves.append(move)
                            else: black_moves.append(move)
                            board.push_uci(move)
                            move_list.append(move_san)
                            stockfish.set_fen_position(board.fen())
                            self.send_eval_data(stockfish, board, white_moves=white_moves, white_best_moves=white_best_moves, black_moves=black_moves, black_best_moves=black_best_moves)
                            self._send("S_MOVE" + move_san)
                        else:
                            print(f"Move {move} failed (Mouseless). Retrying in next loop...")
                            time.sleep(0.1)

                # ── 5. LOOP THROTTLE (FASTER) ──────────────────────────
                time.sleep(0.05)

        except (WebDriverException, ConnectionResetError) as e:
            # Browser closed or WebDriver connection lost
            print(f"WebDriver/Connection lost: {e}")
            self._send("STOPPED")
        except (WebDriverException, ConnectionResetError, Exception) as e:
            # Browser closed or WebDriver connection lost or other crash
            err_msg = f"Bot Crash: {e}"
            print(err_msg)
            if "ConnectionResetError" in err_msg or "Connection aborted" in err_msg:
                self._send("STOPPED")
            else:
                self._send(f"ERR_EXE:{err_msg}")
        finally:
            # ── CLEANUP ───────────────────────────────────────────────
            try:
                # 1. Ask Stockfish nicely
                if 'stockfish' in locals() and stockfish:
                    try:
                        # Try to get the internal process object to kill it
                        # stockfish-python internally uses ._stockfish_subprocess
                        sp = getattr(stockfish, "_stockfish_subprocess", None)
                        if sp:
                            sp.kill()
                            sp.wait()
                    except Exception:
                        pass
                    del stockfish
            except Exception:
                pass
            
            # 2. Inform GUI
            self._send("STOPPED")

    # ------------------------------------------------------------------
    # Evaluation helpers
    # ------------------------------------------------------------------

    def send_eval_data(
        self, stockfish, board,
        white_moves=None, white_best_moves=None,
        black_moves=None, black_best_moves=None,
    ):
        """Send evaluation, WDL, and material data to the GUI."""
        try:
            eval_data = stockfish.get_evaluation()
            eval_type = eval_data['type']
            eval_value = eval_data['value']

            player_perspective_eval_value = eval_value
            if not self.is_white:
                player_perspective_eval_value = -eval_value

            try:
                wdl_stats = stockfish.get_wdl_stats()
                if not wdl_stats or len(wdl_stats) < 3:
                    wdl_stats = [0, 0, 0]
            except Exception:
                wdl_stats = [0, 0, 0]

            material = self.calculate_material_advantage(board)

            white_accuracy = "-"
            black_accuracy = "-"
            if (white_moves and white_best_moves
                    and len(white_moves) > 0
                    and len(white_moves) == len(white_best_moves)):
                matches = sum(1 for a, b in zip(white_moves, white_best_moves) if a == b)
                white_accuracy = f"{matches / len(white_moves) * 100:.1f}%"

            if (black_moves and black_best_moves
                    and len(black_moves) > 0
                    and len(black_moves) == len(black_best_moves)):
                matches = sum(1 for a, b in zip(black_moves, black_best_moves) if a == b)
                black_accuracy = f"{matches / len(black_moves) * 100:.1f}%"

            if eval_type == "cp":
                eval_str = f"{player_perspective_eval_value / 100:.2f}"
                eval_value_decimal = player_perspective_eval_value / 100
            else:
                eval_str = f"M{player_perspective_eval_value}"
                eval_value_decimal = player_perspective_eval_value

            total = sum(wdl_stats)
            if total > 0:
                is_bot_turn = (
                    (self.is_white and board.turn == chess.WHITE)
                    or (not self.is_white and board.turn == chess.BLACK)
                )
                if is_bot_turn:
                    win_pct  = wdl_stats[0] / total * 100
                    draw_pct = wdl_stats[1] / total * 100
                    loss_pct = wdl_stats[2] / total * 100
                else:
                    win_pct  = wdl_stats[2] / total * 100
                    draw_pct = wdl_stats[1] / total * 100
                    loss_pct = wdl_stats[0] / total * 100
                wdl_str = f"{win_pct:.1f}/{draw_pct:.1f}/{loss_pct:.1f}"
            else:
                wdl_str = "?/?/?"

            bot_accuracy      = white_accuracy if self.is_white else black_accuracy
            opponent_accuracy = black_accuracy if self.is_white else white_accuracy

            data = f"EVAL|{eval_str}|{wdl_str}|{material}|{bot_accuracy}|{opponent_accuracy}"
            self._send(data)

            overlay_data = {"eval": eval_value_decimal, "eval_type": eval_type}
            board_elem = self.grabber.get_board()
            if board_elem:
                canvas_x_offset, canvas_y_offset = self.grabber.get_top_left_corner()
                overlay_data["board_position"] = {
                    'x': canvas_x_offset + board_elem.location['x'],
                    'y': canvas_y_offset + board_elem.location['y'],
                    'width': board_elem.size['width'],
                    'height': board_elem.size['height'],
                }
            overlay_data["is_white"] = self.is_white
            self.overlay_queue.put(overlay_data)

        except Exception as e:
            print(f"Error sending evaluation: {e}")

    def calculate_material_advantage(self, board):
        piece_values = {
            chess.PAWN: 1,
            chess.KNIGHT: 3,
            chess.BISHOP: 3,
            chess.ROOK: 5,
            chess.QUEEN: 9,
        }
        white_material = sum(
            len(board.pieces(pt, chess.WHITE)) * v for pt, v in piece_values.items()
        )
        black_material = sum(
            len(board.pieces(pt, chess.BLACK)) * v for pt, v in piece_values.items()
        )
        advantage = white_material - black_material
        if advantage > 0:
            return f"+{advantage}"
        elif advantage < 0:
            return str(advantage)
        return "0"
