import time
from selenium.common import NoSuchElementException, StaleElementReferenceException, WebDriverException
from selenium.webdriver.common.by import By

from grabbers.grabber import Grabber


class ChesscomGrabber(Grabber):
    def __init__(self, chrome_url, chrome_session_id):
        super().__init__(chrome_url, chrome_session_id)

    # ------------------------------------------------------------------
    # Board element
    # ------------------------------------------------------------------

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
                self._board_elem = self.chrome.find_element(
                    By.XPATH, "//*[@id='board-play-computer']"
                )
                if self._board_elem: return
            except NoSuchElementException:
                try:
                    self._board_elem = self.chrome.find_element(
                        By.XPATH, "//*[@id='board-single']"
                    )
                    if self._board_elem: return
                except NoSuchElementException:
                    try:
                        # Puzzle board
                        self._board_elem = self.chrome.find_element(
                            By.XPATH, "//*[@id='board-puzzle']"
                        )
                        if self._board_elem: return
                    except NoSuchElementException:
                        self._board_elem = None
            except (WebDriverException, Exception):
                self._board_elem = None
                return

            # Optimized sleep
            time.sleep(1)

    # ------------------------------------------------------------------
    # Color detection
    # ------------------------------------------------------------------

    def is_white(self):
        if not self._board_elem:
            return None
        try:
            # 1. Check 'flipped' class
            cls = self._board_elem.get_attribute("class") or ""
            if "flipped" in cls:
                return False
            
            # 2. SVG Fallback
            svgs = self._board_elem.find_elements(By.TAG_NAME, "svg")
            for svg in svgs:
                if svg.get_attribute("class") == "coordinates":
                    try:
                        one = svg.find_element(By.XPATH, ".//*[text()='1']")
                        y = float(one.get_attribute("y") or 0)
                        return y > 50
                    except Exception:
                        continue
            return True
        except Exception:
            return True

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

        from selenium.webdriver.common.action_chains import ActionChains
        
        # 1. Primary Method: Selenium ActionChains (Safe "Ghost Mouse" - doesn't move real cursor)
        try:
            def get_sq_selector(sq):
                f = "abcdefgh".index(sq[0]) + 1
                r = int(sq[1])
                return f".square-{f}{r}"
            
            from_el = self._board_elem.find_element(By.CSS_SELECTOR, get_sq_selector(from_sq))
            to_el = self._board_elem.find_element(By.CSS_SELECTOR, get_sq_selector(to_sq))
            
            actions = ActionChains(self.chrome)
            actions.move_to_element(from_el).click().move_to_element(to_el).click().perform()
            return True
        except Exception: 
            pass

        # 2. Fallback: Robust JS-based API / PointerEvents
        script = """
        (function() {
            var files = {'a':1,'b':2,'c':3,'d':4,'e':5,'f':6,'g':7,'h':8};
            var from = {f: files[arguments[0][0]], r: parseInt(arguments[0][1])};
            var to   = {f: files[arguments[1][0]], r: parseInt(arguments[1][1])};
            var promo = arguments[2] || 'q';

            try {
                var inst = window.chessboard || (window.ChessBoard ? window.ChessBoard.instances[0] : null);
                var g = inst ? (inst.game || inst) : null;
                if (g && typeof g.move === 'function') {
                    g.move({from: arguments[0], to: arguments[1], promotion: promo});
                    return true;
                }
            } catch(e) {}

            try {
                var b = document.querySelector('chess-board') || document.querySelector('.board');
                if (b) {
                    var r = b.getBoundingClientRect(), flip = b.classList.contains('flipped'), sz = r.width / 8;
                    function gXY(f, r1) {
                        return {
                            x: r.left + (flip ? (8.5 - f) : (f - 0.5)) * sz,
                            y: r.top + (flip ? (r1 - 0.5) : (8.5 - r1)) * sz
                        };
                    }
                    var fXY = gXY(from.f, from.r), tXY = gXY(to.f, to.r);
                    var down = new PointerEvent('pointerdown', {bubbles:true, clientX:fXY.x, clientY:fXY.y, pointerType:'mouse', button:0});
                    var up = new PointerEvent('pointerup', {bubbles:true, clientX:tXY.x, clientY:tXY.y, pointerType:'mouse', button:0});
                    b.dispatchEvent(down);
                    setTimeout(function(){ b.dispatchEvent(up); }, 50);
                    return true;
                }
            } catch(e) {}
            return false;
        })();
        """
        try:
            return self.chrome.execute_script(script, from_sq, to_sq, promo)
        except Exception:
            return False
