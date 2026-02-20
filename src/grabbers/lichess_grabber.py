import re
import time
from selenium.common import NoSuchElementException, StaleElementReferenceException, WebDriverException
from selenium.webdriver.common.by import By

from grabbers.grabber import Grabber


class LichessGrabber(Grabber):
    def __init__(self, chrome_url, chrome_session_id):
        super().__init__(chrome_url, chrome_session_id)
        self.tag_name = None

    def update_board_elem(self, stop_queue=None):
        """Keep looking for the board element until found, browser closed, or STOP signal."""
        while True:
            # Check for STOP signal from GUI
            if stop_queue and not stop_queue.empty():
                try:
                    if stop_queue.get_nowait() == "STOP":
                        return
                except Exception:
                    pass

            try:
                # Try finding the normal board
                self._board_elem = self.chrome.find_element(By.XPATH, '//*[@id="main-wrap"]/main/div[1]/div[1]/div/cg-container')
                if self._board_elem:
                    return
            except NoSuchElementException:
                try:
                    # Try finding the board in the puzzles page
                    self._board_elem = self.chrome.find_element(By.XPATH, '/html/body/div[2]/main/div[1]/div/cg-container')
                    if self._board_elem:
                        return
                except NoSuchElementException:
                    self._board_elem = None
            except (WebDriverException, Exception):
                # Browser likely closed or disconnected
                self._board_elem = None
                return

            # Optimized: wait a bit before next check to save CPU
            time.sleep(1)

    def is_white(self):
        if not self._board_elem:
            return None
        try:
            # 1. Try orientation class on cg-wrap or cg-container
            container = self.chrome.find_element(By.CSS_SELECTOR, ".cg-wrap, .cg-container")
            cls = container.get_attribute("class")
            if "orientation-white" in cls: return True
            if "orientation-black" in cls: return False
            
            # 2. Fallback: Check the coordinate labels (ranks)
            # Find all <coord> elements inside <coords class="ranks">
            coords = self.chrome.find_elements(By.CSS_SELECTOR, "coords.ranks coord")
            if coords:
                # Get the text of the first coordinate label (usually top-most)
                first_coord = coords[0].text
                # In White orientation, top-most rank label is '8'. In Black, it's '1'.
                if '8' in first_coord: return True
                if '1' in first_coord: return False
            
            # 3. Last fallback: Check files
            files = self.chrome.find_elements(By.CSS_SELECTOR, "coords.files coord")
            if files:
                first_file = files[0].text
                if 'a' in first_file: return True
                if 'h' in first_file: return False

            return True # Default to White
        except Exception:
            return True

    def is_game_over(self):
        # sourcery skip: assign-if-exp, boolean-if-exp-identity, reintroduce-else, remove-unnecessary-cast
        try:
            # Find the game over window
            self.chrome.find_element(By.XPATH, '//*[@id="main-wrap"]/main/aside/div/section[2]')

            # If we don't have an exception at this point, we have found the game over window
            return True
        except NoSuchElementException:
            # Try finding the puzzles game over window and checking its class
            try:
                # The game over window
                game_over_window = self.chrome.find_element(By.XPATH, '/html/body/div[2]/main/div[2]/div[3]/div[1]')

                if game_over_window.get_attribute("class") == "complete":
                    return True

                # If we don't have an exception at this point and the window's class is not "complete",
                # then the game is still going
                return False
            except NoSuchElementException:
                return False

    def set_moves_tag_name(self):
        if self.is_game_puzzles():
            return False

        move_list_elem = self.get_normal_move_list_elem()

        if move_list_elem is None or move_list_elem == []:
            return False

        try:
            last_child = move_list_elem.find_element(By.XPATH, "*[last()]")
            self.tag_name = last_child.tag_name

            return True
        except NoSuchElementException:
            return False

    def get_move_list(self):
        # sourcery skip: assign-if-exp, merge-else-if-into-elif, use-fstring-for-concatenation
        is_puzzles = self.is_game_puzzles()

        # Find the move list element
        if is_puzzles:
            move_list_elem = self.get_puzzles_move_list_elem()

            if move_list_elem is None:
                return None
        else:
            move_list_elem = self.get_normal_move_list_elem()

            if move_list_elem is None:
                return None
            if (not move_list_elem) or (self.tag_name is None and self.set_moves_tag_name() is False):
                return []

        # Get the move elements (children of the move list element)
        try:
            if not is_puzzles:
                if not self.moves_list:
                    # If the moves list is empty, find all moves
                    children = move_list_elem.find_elements(By.CSS_SELECTOR, self.tag_name)
                else:
                    # If the moves list is not empty, find only the new moves
                    children = move_list_elem.find_elements(By.CSS_SELECTOR, self.tag_name + ":not([data-processed])")
            else:
                if not self.moves_list:
                    # If the moves list is empty, find all moves
                    children = move_list_elem.find_elements(By.CSS_SELECTOR, "move")
                else:
                    # If the moves list is not empty, find only the new moves
                    children = move_list_elem.find_elements(By.CSS_SELECTOR, "move:not([data-processed])")
        except NoSuchElementException:
            return None

        # Get the moves from the elements
        for move_element in children:
            # Sanitize the move
            move = re.sub(r"[^a-zA-Z0-9+-]", "", move_element.text)
            if move != "":
                self.moves_list[move_element.id] = move

            # Mark the move as processed
            self.chrome.execute_script("arguments[0].setAttribute('data-processed', 'true')", move_element)

        return [val for val in self.moves_list.values()]

    def get_puzzles_move_list_elem(self):
        try:
            # Try finding the move list in the puzzles page
            move_list_elem = self.chrome.find_element(By.XPATH, '/html/body/div[2]/main/div[2]/div[2]/div')

            return move_list_elem
        except NoSuchElementException:
            return None

    def get_normal_move_list_elem(self):
        try:
            # Try finding the normal move list
            move_list_elem = self.chrome.find_element(By.XPATH, '//*[@id="main-wrap"]/main/div[1]/rm6/l4x')

            return move_list_elem
        except NoSuchElementException:
            try:
                # Try finding the normal move list when there are no moves yet
                self.chrome.find_element(By.XPATH, '//*[@id="main-wrap"]/main/div[1]/rm6')

                # If we don't have an exception at this point, we don't have any moves yet
                return []
            except NoSuchElementException:
                return None

    def is_game_puzzles(self):
        try:
            # Try finding the puzzles text
            self.chrome.find_element(By.XPATH, "/html/body/div[2]/main/aside/div[1]/div[1]/div/p[1]")

            # If we don't have an exception at this point, the game is a puzzle
            return True
        except NoSuchElementException:
            return False

    def click_puzzle_next(self):
        # Find the next continue training button
        try:
            next_button = self.chrome.find_element(By.XPATH, "/html/body/div[2]/main/div[2]/div[3]/a")
        except NoSuchElementException:
            try:
                next_button = self.chrome.find_element(By.XPATH, '//*[@id="main-wrap"]/main/div[2]/div[3]/div[3]/a[2]')
            except NoSuchElementException:
                return

        # Click the continue training button
        self.chrome.execute_script("arguments[0].click();", next_button)

    def click_game_next(self):
        # Find the next new game button
        try:
            next_button = self.chrome.find_element(By.XPATH, "//*[contains(text(), 'New opponent')]")
            self.chrome.execute_script("arguments[0].click();", next_button)
        except (NoSuchElementException, Exception):
            pass

    def make_mouseless_move(self, move, move_count, human_like=False):
        from selenium.webdriver.common.action_chains import ActionChains
        import random

        # ─── METHOD 1: Direct Injection (FAST) ────────────────────
        # Only used if human_like is OFF for maximum speed/efficiency.
        if not human_like:
            script_api = """
            (function() {
                try {
                    var uci = arguments[0];
                    var count = arguments[1];
                    if (window.lichess && lichess.pubsub) {
                        lichess.pubsub.emit('socket.send', 'move', {u: uci, b: 1, a: count});
                        return true;
                    }
                    var board = document.querySelector('cg-board');
                    if (board && board.parentNode && board.parentNode.chessground) {
                        board.parentNode.chessground.move(uci.substring(0,2), uci.substring(2,4));
                        return true;
                    }
                } catch(e) {}
                return false;
            })();
            """
            try:
                if self.chrome.execute_script(script_api, move, move_count):
                    return True
            except Exception:
                pass

        # ─── METHOD 2: The Ghost Human (REALISTIC) ────────────────
        # Used if human_like is ON, or as a fallback.
        try:
            board = self._board_elem if "cg-board" in self._board_elem.tag_name else self._board_elem.find_element(By.TAG_NAME, "cg-board")
            rect = board.rect
            is_white = "orientation-black" not in board.find_element(By.XPATH, "..").get_attribute("class")
            
            def get_rel_xy(sq):
                # Only add jitter if human_like is enabled
                jitter_x = random.uniform(-1.0, 1.0) if human_like else 0
                jitter_y = random.uniform(-1.0, 1.0) if human_like else 0
                
                f = "abcdefgh".index(sq[0])
                r = int(sq[1]) - 1
                if is_white: return (f * 12.5 + 6.25 + jitter_x, (7 - r) * 12.5 + 6.25 + jitter_y)
                return ((7 - f) * 12.5 + 6.25 + jitter_x, r * 12.5 + 6.25 + jitter_y)

            f_x, f_y = get_rel_xy(move[0:2])
            t_x, t_y = get_rel_xy(move[2:4])
            
            off_f_x = (f_x - 50) * rect['width'] / 100
            off_f_y = (f_y - 50) * rect['height'] / 100
            off_t_x = (t_x - 50) * rect['width'] / 100
            off_t_y = (t_y - 50) * rect['height'] / 100

            # Faster duration if not human_like
            dur = random.randint(50, 150) if human_like else 10
            actions = ActionChains(self.chrome, duration=dur)
            actions.move_to_element_with_offset(board, off_f_x, off_f_y).click_and_hold()
            if human_like: actions.pause(random.uniform(0.05, 0.15))
            actions.move_to_element_with_offset(board, off_t_x, off_t_y).release().perform()
            return True
        except Exception:
            pass

        return False
