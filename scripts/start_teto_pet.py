from __future__ import annotations

from pathlib import Path
import random
import time
from tkinter import Menu, PhotoImage, TclError, Tk, Label


STATE_CONFIG = {
    "angry": {
        "initial": [1, 2, 3, 4, 5, 6, 7, 8],
        "loop": [],
        "duration_ms": 10_000,
        "normal_delay_ms": 1000,
        "hold_delay_ms": 1900,
        "hold_frames": {6, 7, 8},
        "loop_mode": "once",
    },
    "listening": {
        "initial": [1, 2, 3, 4, 5, 6, 7, 8],
        "loop": [6, 7, 8],
        "duration_ms": 20_000,
        "normal_delay_ms": 560,
        "loop_mode": "loop_after_initial",
    },
    "playing": {
        "initial": [1, 2, 3, 4, 5, 6, 7, 8, 9],
        "loop": [7, 8, 9],
        "duration_ms": 20_000,
        "normal_delay_ms": 560,
        "loop_mode": "loop_after_initial",
    },
    "reading": {
        "initial": [1, 2, 3, 4, 5, 6],
        "loop": [],
        "duration_ms": 20_000,
        "normal_delay_ms": 650,
        "final_delay_ms": 900,
        "loop_mode": "reading",
    },
    "sleeping": {
        "initial": [1, 2, 3, 4, 5, 6, 7, 8],
        "loop": [3, 4, 5, 6, 7, 8],
        "duration_ms": 20_000,
        "normal_delay_ms": 640,
        "loop_mode": "loop_after_initial",
    },
}

STATE_NAMES = list(STATE_CONFIG.keys())
ROOT_DIR = Path(__file__).resolve().parents[1]
IMAGES_DIR = ROOT_DIR / "web_v4" / "images"
STATE_DIRS = {
    "angry": "teto_angring",
    "listening": "teto_listening",
    "playing": "teto_playing",
    "reading": "teto_reading",
    "sleeping": "teto_sleeping",
}


class TetoPetApp:
    def __init__(self):
        self.root = Tk()
        self.root.title("TetoPet")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.resizable(False, False)
        try:
            self.root.configure(bg="#222222")
            self.root.wm_attributes("-transparentcolor", "#222222")
        except TclError:
            self.root.configure(bg="#222222")

        self.label = Label(self.root, bd=0, highlightthickness=0, bg="#222222")
        self.label.pack()

        self.running = True
        self.current_state = None
        self.phase = "initial"
        self.frame_index = 0
        self.exit_pending = False
        self.reading_finish = False
        self.state_start_ts = 0.0
        self.dragging = False
        self.drag_start_root_x = 0
        self.drag_start_root_y = 0
        self.drag_start_win_x = 0
        self.drag_start_win_y = 0
        self.shaking = False
        self.shake_steps = 0
        self.shake_origin = (0, 0)

        self.frames = self._preload_frames()
        self.current_frame = None

        self._setup_bindings()
        self._setup_context_menu()

        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        self.root.geometry(f"+{screen_w - 260}+{screen_h - 250}")

        self._enter_state(random.choice(STATE_NAMES))

    def _setup_bindings(self):
        self.root.bind("<ButtonPress-1>", self._start_drag)
        self.root.bind("<B1-Motion>", self._drag)
        self.root.bind("<ButtonRelease-1>", self._stop_drag)
        self.root.bind("<Double-Button-1>", self._quit)
        self.root.bind("<Button-3>", self._open_context_menu)

    def _setup_context_menu(self):
        self.context_menu = Menu(self.root, tearoff=0)
        self.context_menu.add_command(label="退出", command=self._quit)

    def _open_context_menu(self, event):
        self.context_menu.tk_popup(event.x_root, event.y_root)

    def _start_drag(self, event):
        if self.shaking:
            return
        self.dragging = True
        self.drag_start_root_x = event.x_root
        self.drag_start_root_y = event.y_root
        self.drag_start_win_x = self.root.winfo_x()
        self.drag_start_win_y = self.root.winfo_y()

    def _drag(self, event):
        if not self.dragging or self.shaking:
            return
        dx = event.x_root - self.drag_start_root_x
        dy = event.y_root - self.drag_start_root_y
        self.root.geometry(f"+{self.drag_start_win_x + dx}+{self.drag_start_win_y + dy}")

    def _stop_drag(self, _event):
        self.dragging = False

    def _preload_frames(self):
        if not IMAGES_DIR.is_dir():
            raise FileNotFoundError(f"找不到精灵目录：{IMAGES_DIR}")

        all_frames = {}
        for state in STATE_NAMES:
            cfg = STATE_CONFIG[state]
            state_dir = IMAGES_DIR / STATE_DIRS[state]
            needed_frames = set(cfg["initial"])
            needed_frames.update(cfg["loop"])
            if "final_delay_ms" in cfg:
                needed_frames.add(7)
            for idx in sorted(needed_frames):
                file_path = state_dir / f"{idx:03d}.png"
                if not file_path.exists():
                    raise FileNotFoundError(f"精灵缺失：{file_path}")
                all_frames.setdefault(state, {})[idx] = PhotoImage(file=str(file_path))
        return all_frames

    def _now(self):
        return time.monotonic() * 1000

    def _current_sequence(self):
        cfg = STATE_CONFIG[self.current_state]
        if self.current_state == "reading" and self.reading_finish:
            return [7]
        if self.phase == "initial":
            return cfg["initial"]
        return cfg["loop"]

    def _current_frame(self):
        return self._current_sequence()[self.frame_index]

    def _frame_delay(self):
        cfg = STATE_CONFIG[self.current_state]
        frame_no = self._current_frame()
        if self.current_state == "angry":
            if frame_no in cfg["hold_frames"]:
                return cfg["hold_delay_ms"]
            return cfg["normal_delay_ms"]
        if self.current_state == "reading" and self.reading_finish:
            return cfg["final_delay_ms"]
        return cfg["normal_delay_ms"]

    def _show_frame(self):
        frame_no = self._current_frame()
        image = self.frames[self.current_state][frame_no]
        self.label.configure(image=image)
        self.label.image = image
        self.current_frame = frame_no

    def _start_state(self, state):
        self.current_state = state
        self.phase = "initial"
        self.frame_index = 0
        self.exit_pending = False
        self.reading_finish = False
        self.state_start_ts = self._now()

    def _enter_state(self, state):
        self._start_state(state)
        self._show_frame()
        self._tick()

    def _choose_next_state(self):
        options = [s for s in STATE_NAMES if s != self.current_state]
        return random.choice(options)

    def _exit_current_state(self):
        if not self.running:
            return
        self._enter_state(self._choose_next_state())

    def _advance_frame(self):
        cfg = STATE_CONFIG[self.current_state]
        if self.current_state == "angry":
            sequence = cfg["initial"]
            if self.phase == "initial" and self.frame_index < len(sequence) - 1:
                self.frame_index += 1
            return

        if self.current_state == "reading":
            sequence = cfg["initial"]
            if self.frame_index < len(sequence) - 1:
                self.frame_index += 1
            else:
                self.frame_index = 0
            return

        sequence = self._current_sequence()
        if self.phase == "initial":
            if self.frame_index < len(sequence) - 1:
                self.frame_index += 1
            else:
                self.phase = "loop"
                self.frame_index = 0
            return

        if self.current_state in {"listening", "playing", "sleeping"}:
            self.frame_index = (self.frame_index + 1) % len(sequence)

    def _shake(self):
        if self.current_state != "angry" or self.shaking:
            return
        self.shaking = True
        self.shake_steps = 10
        self.shake_origin = (self.root.winfo_x(), self.root.winfo_y())
        self._step_shake()

    def _step_shake(self):
        if not self.shaking or self.dragging:
            self.shaking = False
            self.root.geometry(f"+{self.shake_origin[0]}+{self.shake_origin[1]}")
            return
        if self.shake_steps <= 0:
            self.shaking = False
            self.root.geometry(f"+{self.shake_origin[0]}+{self.shake_origin[1]}")
            return
        self.shake_steps -= 1
        dx = random.randint(-3, 3)
        dy = random.randint(-2, 2)
        self.root.geometry(f"+{self.shake_origin[0] + dx}+{self.shake_origin[1] + dy}")
        self.root.after(30, self._step_shake)

    def _tick(self):
        if not self.running:
            return

        self._show_frame()

        cfg = STATE_CONFIG[self.current_state]
        elapsed = self._now() - self.state_start_ts
        current_frame = self.current_frame
        should_switch = False

        if self.current_state == "angry":
            if current_frame in cfg["hold_frames"]:
                self._shake()
            if self.phase == "initial" and self.frame_index == len(cfg["initial"]) - 1:
                should_switch = True
            self._advance_frame()

        elif self.current_state == "reading":
            if self.reading_finish:
                should_switch = True
            elif elapsed >= cfg["duration_ms"]:
                self.phase = "final"
                self.reading_finish = True
                self.frame_index = 0
            else:
                self._advance_frame()

        elif self.current_state in {"listening", "playing", "sleeping"}:
            if elapsed >= cfg["duration_ms"]:
                should_switch = True
            else:
                self._advance_frame()

        delay = self._frame_delay()
        if should_switch:
            self.root.after(delay, self._exit_current_state)
        else:
            self.root.after(delay, self._tick)

    def _quit(self, _event=None):
        self.running = False
        try:
            self.root.quit()
            self.root.destroy()
        except TclError:
            pass

    def start(self):
        self.root.mainloop()


def main():
    try:
        app = TetoPetApp()
        app.start()
    except Exception as exc:  # pragma: no cover
        raise SystemExit(f"Teto Pet 启动失败：{exc}")


if __name__ == "__main__":
    main()
