from selenium.common import NoSuchElementException, StaleElementReferenceException
from selenium.webdriver.common.by import By

from grabbers.grabber import Grabber


class ChesscomGrabber(Grabber):
    def __init__(self, chrome_url, chrome_session_id):
        super().__init__(chrome_url, chrome_session_id)

    # ------------------------------------------------------------------
    # Board element
    # ------------------------------------------------------------------

    def update_board_elem(self):
        try:
            self._board_elem = self.chrome.find_element(
                By.XPATH, "//*[@id='board-play-computer']"
            )
        except NoSuchElementException:
            try:
                self._board_elem = self.chrome.find_element(
                    By.XPATH, "//*[@id='board-single']"
                )
            except NoSuchElementException:
                try:
                    # Puzzle board
                    self._board_elem = self.chrome.find_element(
                        By.XPATH, "//*[@id='board-puzzle']"
                    )
                except NoSuchElementException:
                    self._board_elem = None

    # ------------------------------------------------------------------
    # Color detection
    # ------------------------------------------------------------------

    def is_white(self):
        square_names = None
        try:
            coordinates = self.chrome.find_element(
                By.XPATH, "//*[@id='board-play-computer']//*[name()='svg']"
            )
            square_names = coordinates.find_elements(By.XPATH, ".//*")
        except NoSuchElementException:
            try:
                coordinates = self.chrome.find_elements(
                    By.XPATH, "//*[@id='board-single']//*[name()='svg']"
                )
                coordinates = [
                    x for x in coordinates
                    if x.get_attribute("class") == "coordinates"
                ][0]
                square_names = coordinates.find_elements(By.XPATH, ".//*")
            except (NoSuchElementException, IndexError):
                try:
                    # Puzzle board
                    coordinates = self.chrome.find_element(
                        By.XPATH, "//*[@id='board-puzzle']//*[name()='svg']"
                    )
                    square_names = coordinates.find_elements(By.XPATH, ".//*")
                except NoSuchElementException:
                    return None

        if not square_names:
            return None

        # Find bottom-left square (min x, max y)
        elem = None
        min_x = None
        max_y = None
        for name_element in square_names:
            try:
                x = float(name_element.get_attribute("x"))
                y = float(name_element.get_attribute("y"))
            except (TypeError, ValueError):
                continue
            if min_x is None or (x <= min_x and y >= max_y):
                min_x = x
                max_y = y
                elem = name_element

        if elem is None:
            return None
        return elem.text == "1"

    # ------------------------------------------------------------------
    # Game-over detection
    # ------------------------------------------------------------------

    def is_game_over(self):
        try:
            game_over_window = self.chrome.find_element(
                By.CLASS_NAME, "board-modal-container"
            )
            return game_over_window is not None
        except NoSuchElementException:
            return False

    # ------------------------------------------------------------------
    # Moves list
    # ------------------------------------------------------------------

    def reset_moves_list(self):
        self.moves_list = {}

    def get_move_list(self):
        try:
            move_list_elem = self.chrome.find_element(
                By.CLASS_NAME, "play-controller-scrollable"
            )
        except NoSuchElementException:
            try:
                move_list_elem = self.chrome.find_element(
                    By.CLASS_NAME, "mode-swap-move-list-wrapper-component"
                )
            except NoSuchElementException:
                return None

        visible_moves = move_list_elem.find_elements(
            By.CSS_SELECTOR, "div.node[data-node]"
        )
        if len(visible_moves) == 0 and self.moves_list:
            self.reset_moves_list()

        if not self.moves_list:
            moves = move_list_elem.find_elements(By.CSS_SELECTOR, "div.node[data-node]")
        else:
            moves = move_list_elem.find_elements(
                By.CSS_SELECTOR, "div.node[data-node]:not([data-processed])"
            )

        for move in moves:
            move_class = move.get_attribute("class")
            if "white-move" in move_class or "black-move" in move_class:
                try:
                    figurine_elem = move.find_element(
                        By.CSS_SELECTOR, "[data-figurine]"
                    )
                    figure = figurine_elem.get_attribute("data-figurine")
                except NoSuchElementException:
                    figure = None

                if figure is None:
                    self.moves_list[move.get_attribute("data-node")] = move.text
                elif "=" in move.text:
                    m = move.text + figure
                    if "+" in m:
                        m = m.replace("+", "") + "+"
                    self.moves_list[move.get_attribute("data-node")] = m
                else:
                    self.moves_list[move.get_attribute("data-node")] = figure + move.text

                self.chrome.execute_script(
                    "arguments[0].setAttribute('data-processed', 'true')", move
                )

        return list(self.moves_list.values())

    # ------------------------------------------------------------------
    # Puzzle / game mode detection
    # ------------------------------------------------------------------

    def is_game_puzzles(self):
        """
        Detect Chess.com puzzle pages.
        Chess.com serves puzzles at /puzzles/... with a board id 'board-puzzle'
        or with a URL containing '/puzzles'.
        """
        try:
            current_url = self.chrome.current_url
            if "/puzzles" in current_url or "/puzzle" in current_url:
                return True
        except Exception:
            pass
        # Fallback: try to find the puzzle board element
        try:
            self.chrome.find_element(By.XPATH, "//*[@id='board-puzzle']")
            return True
        except NoSuchElementException:
            return False

    # ------------------------------------------------------------------
    # Non-stop helpers
    # ------------------------------------------------------------------

    def click_puzzle_next(self):
        """Click the 'Next puzzle' / continue button on Chess.com puzzles."""
        selectors = [
            # "Next puzzle" button (various class names Chess.com uses)
            "button.puzzle-buttons-playagain",
            "button.next-puzzles-start-button",
            "[class*='next'][class*='puzzle']",
            "[class*='puzzle'][class*='next']",
            "button[data-cy='next-puzzle']",
        ]
        for selector in selectors:
            try:
                btn = self.chrome.find_element(By.CSS_SELECTOR, selector)
                self.chrome.execute_script("arguments[0].click();", btn)
                return
            except NoSuchElementException:
                continue

        # XPath fallback: any button/anchor containing "Next"
        try:
            btn = self.chrome.find_element(
                By.XPATH, "//*[contains(text(),'Next') or contains(text(),'next')]"
                          "[self::button or self::a]"
            )
            self.chrome.execute_script("arguments[0].click();", btn)
        except NoSuchElementException:
            pass

    def click_game_next(self):
        """
        Click 'New game' / 'Play again' after a game ends on Chess.com.
        """
        selectors = [
            "button.board-modal-container-buttons-button",
            "button[data-cy='new-game-button']",
            "[class*='play-again']",
            "[class*='new-game']",
        ]
        for selector in selectors:
            try:
                btn = self.chrome.find_element(By.CSS_SELECTOR, selector)
                self.chrome.execute_script("arguments[0].click();", btn)
                return
            except NoSuchElementException:
                continue

        # XPath fallback
        for text in ("New Game", "Play Again", "Rematch"):
            try:
                btn = self.chrome.find_element(
                    By.XPATH, f"//*[contains(text(),'{text}')]"
                              "[self::button or self::a]"
                )
                self.chrome.execute_script("arguments[0].click();", btn)
                return
            except (NoSuchElementException, StaleElementReferenceException):
                continue

    # ------------------------------------------------------------------
    # Mouseless move (Chess.com)
    # ------------------------------------------------------------------

    def make_mouseless_move(self, move, move_count):
        """
        Make a move on Chess.com without moving the mouse by injecting a
        'move' message through Chess.com's internal game socket/API.

        Chess.com uses a WebAssembly + JS layer.  The most reliable
        mouseless method is to programmatically click the squares via JS,
        which avoids triggering anti-cheat flags from pyautogui.
        """
        from_sq = move[0:2]   # e.g. "e2"
        to_sq   = move[2:4]   # e.g. "e4"
        promo   = move[4] if len(move) == 5 else ""

        script = """
        (function() {
            function squareToCoords(sq) {
                var files = {'a':1,'b':2,'c':3,'d':4,'e':5,'f':6,'g':7,'h':8};
                return {file: files[sq[0]], rank: parseInt(sq[1])};
            }
            var from = squareToCoords(arguments[0]);
            var to   = squareToCoords(arguments[1]);
            var promo = arguments[2];

            // Try Chess.com's internal game object
            try {
                var game = window.chessboard || window.ChessBoard;
                if (game && game.game && game.game.move) {
                    game.game.move({from: arguments[0], to: arguments[1], promotion: promo || 'q'});
                    return 'api';
                }
            } catch(e) {}

            // Fallback: click the from-square, then the to-square
            // Chess.com renders squares as <div class="square-XX"> where XX = file*10+rank
            function clickSquare(file, rank) {
                var sel = '.square-' + (file * 10 + rank);
                var el = document.querySelector(sel);
                if (el) {
                    el.dispatchEvent(new MouseEvent('mousedown', {bubbles:true}));
                    el.dispatchEvent(new MouseEvent('mouseup',   {bubbles:true}));
                    el.dispatchEvent(new MouseEvent('click',     {bubbles:true}));
                    return true;
                }
                return false;
            }
            clickSquare(from.file, from.rank);
            setTimeout(function(){ clickSquare(to.file, to.rank); }, 100);
            return 'click';
        })();
        """
        try:
            self.chrome.execute_script(script, from_sq, to_sq, promo)
        except Exception:
            pass
