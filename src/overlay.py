import tkinter as tk
import math
import queue
import threading
import time

class TkOverlay:
    def __init__(self, master, overlay_queue):
        self.master = master
        self.overlay_queue = overlay_queue
        
        self.window = tk.Toplevel(master)
        self.window.title("PawnBit Overlay")
        
        # Make it full screen, transparent, and stay on top
        self.window.attributes("-topmost", True)
        # "grey" will be our transparent color.
        # Ensure we pick a color unlikely to be in the board.
        self._trans_color = "#123456" 
        self.window.attributes("-transparentcolor", self._trans_color)
        self.window.attributes("-disabled", True) # Click-through
        self.window.overrideredirect(True) # No title bar
        
        sw = self.window.winfo_screenwidth()
        sh = self.window.winfo_screenheight()
        self.window.geometry(f"{sw}x{sh}+0+0")
        self.window.config(bg=self._trans_color)
        
        self.canvas = tk.Canvas(self.window, width=sw, height=sh, bg=self._trans_color, highlightthickness=0)
        self.canvas.pack()
        
        self.running = True
        self.arrows = []
        self.eval_visible = False
        self.is_white = True
        
        # evaluation bar state
        self.eval_val = 0.0
        self.eval_type = "cp"
        self.board_pos = None

        # Start poll loop
        threading.Thread(target=self._poll_queue, daemon=True).start()

    def _poll_queue(self):
        while self.running:
            try:
                msg = self.overlay_queue.get(timeout=0.1)
                if msg == "STOP":
                    self.master.after(0, self.destroy)
                    break
                
                if isinstance(msg, list):
                    self.master.after(0, lambda m=msg: self.draw_arrows(m))
                elif isinstance(msg, dict):
                    self.master.after(0, lambda m=msg: self.update_eval(m))
            except queue.Empty:
                continue
            except Exception:
                break

    def draw_arrows(self, arrow_data):
        self.canvas.delete("arrow")
        for arrow in arrow_data:
            start, end = arrow
            self._create_arrow(start[0], start[1], end[0], end[1])

    def _create_arrow(self, x1, y1, x2, y2):
        # Draw a thick arrow using a line with an arrow head
        # Red with some "transparency" isn't easy in pure tk, so we use a bright red
        self.canvas.create_line(x1, y1, x2, y2, fill="red", width=5, arrow=tk.LAST, 
                               arrowshape=(16, 20, 8), tags="arrow")

    def update_eval(self, data):
        if "eval" in data:
            self.eval_val = data["eval"]
            self.eval_type = data.get("eval_type", "cp")
            self.eval_visible = True
        
        if "board_position" in data:
            self.board_pos = data["board_position"]
        
        if "is_white" in data:
            self.is_white = data["is_white"]
            
        self.draw_eval_bar()

    def draw_eval_bar(self):
        self.canvas.delete("eval")
        if not self.eval_visible or not self.board_pos:
            return
        
        pos = self.board_pos
        bx, by, bw, bh = pos['x'], pos['y'], pos['width'], pos['height']
        
        # Eval bar dimensions
        bar_w = 25
        margin = 10
        bar_x = bx - bar_w - margin
        bar_y = by
        bar_h = bh
        
        # Background/Border
        self.canvas.create_rectangle(bar_x-2, bar_y-2, bar_x+bar_w+2, bar_y+bar_h+2, 
                                    fill="black", outline="#333", tags="eval")
        
        # Advantage calculation
        if self.eval_type == "cp":
            val = max(min(float(self.eval_val), 10.0), -10.0)
            adv = 1.0 / (1.0 + math.exp(-val * 0.5))
        else: # mate
            adv = 1.0 if int(self.eval_val) > 0 else 0.0
            
        # Colors
        p_color = "white" if self.is_white else "#222"
        o_color = "#222" if self.is_white else "white"
        
        # Draw sections
        opp_h = int(bar_h * (1.0 - adv))
        # Top (opponent)
        self.canvas.create_rectangle(bar_x, bar_y, bar_x+bar_w, bar_y+opp_h, 
                                    fill=o_color, outline="", tags="eval")
        # Bottom (player)
        self.canvas.create_rectangle(bar_x, bar_y+opp_h, bar_x+bar_w, bar_y+bar_h, 
                                    fill=p_color, outline="", tags="eval")
        
        # Mid line
        self.canvas.create_line(bar_x, bar_y+bh//2, bar_x+bar_w, bar_y+bh//2, fill="grey", tags="eval")
        
        # Text
        txt = f"{self.eval_val:+.1f}" if self.eval_type == "cp" else f"M{self.eval_val}"
        self.canvas.create_text(bar_x + bar_w//2, bar_y + bar_h - 10, text=txt, 
                               fill="red", font=("Arial", 8, "bold"), tags="eval")

    def destroy(self):
        self.running = False
        try:
            self.window.destroy()
        except Exception:
            pass

def run(overlay_queue):
    # This is for backward compatibility if something still tries to 'run' it in a process
    # But we will move away from this.
    root = tk.Tk()
    root.withdraw()
    TkOverlay(root, overlay_queue)
    root.mainloop()
