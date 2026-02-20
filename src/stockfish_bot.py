import threading
from stockfish import Stockfish
import pyautogui
import time
import sys
import os
import random
import chess
import re
from grabbers.chesscom_grabber import ChesscomGrabber
from grabbers.lichess_grabber import LichessGrabber
from utilities import char_to_num
import keyboard


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

    def move_to_screen_pos(self, move):
        canvas_x_offset, canvas_y_offset = self.grabber.get_top_left_corner()
        board_x = canvas_x_offset + self.grabber.get_board().location["x"]
        board_y = canvas_y_offset + self.grabber.get_board().location["y"]
        square_size = self.grabber.get_board().size['width'] / 8

        if self.is_white:
            x = board_x + square_size * (char_to_num(move[0]) - 1) + square_size / 2
            y = board_y + square_size * (8 - int(move[1])) + square_size / 2
        else:
            x = board_x + square_size * (8 - char_to_num(move[0])) + square_size / 2
            y = board_y + square_size * (int(move[1]) - 1) + square_size / 2

        return x, y

    def get_move_pos(self, move):  # sourcery skip: remove-redundant-slice-index
        start_pos_x, start_pos_y = self.move_to_screen_pos(move[0:2])
        end_pos_x, end_pos_y = self.move_to_screen_pos(move[2:4])
        return (start_pos_x, start_pos_y), (end_pos_x, end_pos_y)

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

    def make_move(self, move):  # sourcery skip: extract-method
        start_pos, end_pos = self.get_move_pos(move)
        pyautogui.moveTo(start_pos[0], start_pos[1])
        time.sleep(self.mouse_latency)
        pyautogui.dragTo(end_pos[0], end_pos[1])

        if len(move) == 5:
            time.sleep(0.1)
            end_pos_x = None
            end_pos_y = None
            if move[4] == "n":
                end_pos_x, end_pos_y = self.move_to_screen_pos(move[2] + str(int(move[3]) - 1))
            elif move[4] == "r":
                end_pos_x, end_pos_y = self.move_to_screen_pos(move[2] + str(int(move[3]) - 2))
            elif move[4] == "b":
                end_pos_x, end_pos_y = self.move_to_screen_pos(move[2] + str(int(move[3]) - 3))

            pyautogui.moveTo(x=end_pos_x, y=end_pos_y)
            pyautogui.click(button='left')

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
            import subprocess
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
            "Ponder": "true",
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
            print(f"Stockfish Init Error: {e}")
            self._send("ERR_EXE")
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
            move_list_uci = [move.uci() for move in board.move_stack]
            stockfish.set_position(move_list_uci)

            white_moves, white_best_moves = [], []
            black_moves, black_best_moves = [], []

            self.send_eval_data(stockfish, board)
            self._send("START")

            if len(move_list) > 0:
                self._send("M_MOVE" + ",".join(move_list))

            while True:
                # ── Check for STOP from GUI ────────────────────────────
                if not self.gui_to_bot_queue.empty():
                    try:
                        if self.gui_to_bot_queue.get_nowait() == "STOP":
                            break
                    except Exception:
                        pass

                # ── Bot's turn ─────────────────────────────────────────
                if (self.is_white and board.turn == chess.WHITE) or (
                    not self.is_white and board.turn == chess.BLACK
                ):
                    move = None
                    move_count = len(board.move_stack)

                    if self.bongcloud and move_count <= 3:
                        if move_count == 0:
                            move = "e2e3"
                        elif move_count == 1:
                            move = "e7e6"
                        elif move_count == 2:
                            move = "e1e2"
                        elif move_count == 3:
                            move = "e8e7"
                        if move and not board.is_legal(chess.Move.from_uci(move)):
                            move = stockfish.get_best_move()
                    else:
                        try:
                            move = stockfish.get_best_move()
                        except Exception as e:
                            print(f"Stockfish crashed/failed to get best move: {e}")
                            break

                    if move is None:
                        # Game is over (stalemate/checkmate from Stockfish's perspective)
                        break

                    if board.turn == chess.WHITE:
                        white_best_moves.append(move)
                    else:
                        black_best_moves.append(move)

                    # Apply human-like random delay before making the move
                    self.apply_random_delay()

                    self_moved = False
                    if self.enable_manual_mode:
                        move_start_pos, move_end_pos = self.get_move_pos(move)
                        self.overlay_queue.put([
                            (
                                (int(move_start_pos[0]), int(move_start_pos[1])),
                                (int(move_end_pos[0]), int(move_end_pos[1])),
                            ),
                        ])
                        while True:
                            if keyboard.is_pressed("3"):
                                break
                            new_ml = self.grabber.get_move_list()
                            if new_ml and len(new_ml) != len(move_list):
                                self_moved = True
                                move_list = new_ml
                                move_san = move_list[-1]
                                move = board.parse_san(move_san).uci()
                                if board.turn == chess.WHITE:
                                    white_moves.append(move)
                                else:
                                    black_moves.append(move)
                                board.push_uci(move)
                                stockfish.make_moves_from_current_position([move])
                                break

                    if not self_moved:
                        move_san = board.san(
                            chess.Move(
                                chess.parse_square(move[0:2]),
                                chess.parse_square(move[2:4]),
                            )
                        )
                        if board.turn == chess.WHITE:
                            white_moves.append(move)
                        else:
                            black_moves.append(move)
                        board.push_uci(move)
                        stockfish.make_moves_from_current_position([move])
                        move_list.append(move_san)
                        if self.enable_mouseless_mode and not self.grabber.is_game_puzzles():
                            self.grabber.make_mouseless_move(move, move_count + 1)
                        else:
                            self.make_move(move)

                    self.overlay_queue.put([])
                    self.send_eval_data(
                        stockfish, board,
                        white_moves, white_best_moves,
                        black_moves, black_best_moves,
                    )
                    self._send("S_MOVE" + move_san)

                    if board.is_checkmate() or board.is_stalemate() or board.is_game_over():
                        if self.enable_non_stop_puzzles and self.grabber.is_game_puzzles():
                            self.go_to_next_puzzle()
                        elif self.enable_non_stop_matches and not self.enable_non_stop_puzzles:
                            self.find_new_online_match()
                        return

                    time.sleep(0.1)

                # ── Wait for opponent ──────────────────────────────────
                previous_move_list = move_list.copy()
                while True:
                    if self.grabber.is_game_over():
                        if self.enable_non_stop_puzzles and self.grabber.is_game_puzzles():
                            self.go_to_next_puzzle()
                        elif self.enable_non_stop_matches and not self.enable_non_stop_puzzles:
                            self.find_new_online_match()
                        return

                    new_move_list = self.grabber.get_move_list()
                    if new_move_list is None:
                        # Grabber failed or tab closed/reloaded?
                        time.sleep(0.5)
                        continue

                    if len(new_move_list) == 0 and len(move_list) > 0:
                        # New game started
                        move_list = []
                        board = chess.Board()
                        stockfish.set_position([])
                        white_moves, white_best_moves = [], []
                        black_moves, black_best_moves = [], []
                        self.is_white = self.grabber.is_white()
                        self._send("RESTART")
                        self.wait_for_gui_to_delete()
                        self.send_eval_data(stockfish, board)
                        self._send("START")
                        break

                    if len(new_move_list) > len(previous_move_list):
                        move_list = new_move_list
                        break

                # Guard: if move_list is still empty (new game branch), restart loop
                if not move_list:
                    continue

                # Parse the move that the opponent just made
                if not move_list:
                    continue
                move = move_list[-1]
                prev_board = board.copy()

                try:
                    board.push_san(move)
                except Exception:
                    continue

                move_uci = prev_board.parse_san(move).uci()

                if prev_board.turn == chess.WHITE:
                    white_moves.append(move_uci)
                else:
                    black_moves.append(move_uci)

                best_move = stockfish.get_best_move_time(300)
                if best_move:
                    if prev_board.turn == chess.WHITE:
                        white_best_moves.append(best_move)
                    else:
                        black_best_moves.append(best_move)

                stockfish.make_moves_from_current_position([str(board.peek())])
                self.send_eval_data(
                    stockfish, board,
                    white_moves, white_best_moves,
                    black_moves, black_best_moves,
                )
                self._send("S_MOVE" + move)

                if board.is_checkmate() or board.is_stalemate() or board.is_game_over():
                    if self.enable_non_stop_puzzles and self.grabber.is_game_puzzles():
                        self.go_to_next_puzzle()
                    elif self.enable_non_stop_matches and not self.enable_non_stop_puzzles:
                        self.find_new_online_match()
                    return

        except Exception as e:
            # log_error is only in gui.py, so we use print and send back to GUI
            err_msg = f"Bot Crash: {e}"
            print(err_msg)
            # Potentially send a specific error to GUI if needed
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
