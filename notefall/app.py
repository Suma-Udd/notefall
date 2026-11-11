"""The NoteFall app.

A big live preview, a settings column in the style of macOS System Settings
(grouped rounded cards, hairline separators, a segmented control, switches)
and one blue button. Light and dark appearance follow the system, with a
button in the corner to pick one yourself.

Built on tkinter so it ships with Python. Every rounded shape is drawn by
Pillow at three times the size and scaled down, so edges stay smooth, and
every size is multiplied by the screen's scale so it looks right on a 4K
Windows screen at 150% as well as on a Mac.
"""

import json
import math
import multiprocessing
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import traceback

import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox

from PIL import Image, ImageDraw, ImageFilter, ImageTk

from . import __version__, media, theme

MIDI_EXT = (".mid", ".midi", ".kar", ".smf")
MEDIA_EXT = (".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma",
             ".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v")

FORMATS = [("phone", "Phone"), ("youtube", "YouTube"), ("square", "Square")]
FORMAT_HINT = {"phone": "1080 × 1920", "youtube": "1920 × 1080", "square": "1080 × 1080"}
ASPECT = {"phone": (9, 16), "youtube": (16, 9), "square": (1, 1)}
SOUNDS = [("piano", "Piano"), ("mine", "Recording"), ("none", "None")]

PALETTES = {
    "light": {
        "window": "#F5F5F7", "side": "#FBFBFD", "card": "#FFFFFF", "text": "#1D1D1F",
        "sub": "#6E6E73", "faint": "#A1A1A6", "line": "#E3E3E8", "track": "#E9E9EE",
        "field": "#F2F2F7", "knob": "#FFFFFF", "accent": "#0071E3", "accent_hover": "#0077ED",
        "accent_down": "#006EDB", "accent_off": "#A8CBF3", "accent_soft": "#E1EDFC",
        "green": "#34C759", "shadow": 34, "edge": "#E5E5EA",
    },
    "dark": {
        "window": "#121214", "side": "#1A1A1D", "card": "#242427", "text": "#F5F5F7",
        "sub": "#A1A1A6", "faint": "#6E6E73", "line": "#36363A", "track": "#333337",
        "field": "#2C2C30", "knob": "#E8E8ED", "accent": "#0A84FF", "accent_hover": "#2490FF",
        "accent_down": "#0077ED", "accent_off": "#1D3D61", "accent_soft": "#16314F",
        "green": "#30D158", "shadow": 90, "edge": "#2A2A2E",
    },
}

PREVIEW_FPS = 30
SS = 3  # supersampling for smooth edges

P = dict(PALETTES["light"])  # the palette in use
UI = 1.0                      # screen scale


def px(n):
    return max(1, int(round(n * UI)))


def _rgb(hex_colour):
    h = hex_colour.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def mix(a, b, t):
    """Colour `a` moved `t` of the way (0..1) to colour `b`."""
    return "#%02X%02X%02X" % tuple(int(round(p + (q - p) * t)) for p, q in zip(_rgb(a), _rgb(b)))


def ease(t):
    """Fast at first, soft landing."""
    return 1 - (1 - t) ** 3


class Tween:
    """A number that glides to its target and tells `fn` each step of the way.

    Everything that moves in the app (switches, the segmented knob, button
    colours, the progress fill, scrolling) runs on one of these, timed by the
    clock so it takes the same time on a slow machine as on a fast one.
    """

    def __init__(self, widget, fn, value=0.0, ms=180):
        self.widget, self.fn, self.ms = widget, fn, ms
        self.value = self.target = float(value)
        self._job = None

    def to(self, target, ms=None):
        self.start, self.target = self.value, float(target)
        self.t0, self.dur = time.perf_counter(), max(1, ms or self.ms) / 1000
        if self._job is None:
            self._step()

    def jump(self, value):
        self.value = self.target = self.start = float(value)
        self.t0, self.dur = 0.0, 0.001

    def _step(self):
        self._job = None
        f = min(1.0, (time.perf_counter() - self.t0) / self.dur)
        self.value = self.start + (self.target - self.start) * ease(f)
        try:
            self.fn(self.value)
            if f < 1.0:
                self._job = self.widget.after(12, self._step)
        except tk.TclError:
            pass  # the widget is gone


def open_path(path):
    if sys.platform.startswith("win"):
        os.startfile(path)  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def show_in_folder(path):
    if sys.platform.startswith("win"):
        subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", path])
    else:
        subprocess.Popen(["xdg-open", os.path.dirname(path)])


# appearance --------------------------------------------------------------

def settings_path():
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, "NoteFall", "settings.json")
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/NoteFall/settings.json")
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "notefall", "settings.json")


def load_settings():
    try:
        with open(settings_path()) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save_settings(data):
    try:
        os.makedirs(os.path.dirname(settings_path()), exist_ok=True)
        with open(settings_path(), "w") as fh:
            json.dump(data, fh)
    except OSError:
        pass


def system_is_dark():
    """Best guess at whether the OS is in dark mode."""
    try:
        if sys.platform.startswith("win"):
            import winreg

            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                 r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
            return winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0
        if sys.platform == "darwin":
            out = subprocess.run(["defaults", "read", "-g", "AppleInterfaceStyle"],
                                 capture_output=True, text=True, timeout=2)
            return "dark" in out.stdout.lower()
        out = subprocess.run(["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
                             capture_output=True, text=True, timeout=2)
        return "dark" in out.stdout.lower()
    except Exception:
        return False


def dark_title_bar(root, dark):
    """Windows 10/11 draw the title bar dark when asked."""
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes

        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        value = ctypes.c_int(1 if dark else 0)
        for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE, and its pre-20H1 number
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(value), 4) == 0:
                break
    except Exception:
        pass


# drawing helpers -----------------------------------------------------------

def rounded(w, h, r, fill, outline=None, width=1, shadow=0, bg=None, shadow_alpha=None):
    """A smooth rounded rectangle as an RGBA image, optionally with a soft shadow."""
    pad = shadow * 2
    W, H = (w + 2 * pad) * SS, (h + 2 * pad) * SS
    img = Image.new("RGBA", (W, H), (_rgb(bg) + (255,)) if bg else (0, 0, 0, 0))
    if shadow:
        sh = Image.new("L", (W, H), 0)
        ImageDraw.Draw(sh).rounded_rectangle(
            [pad * SS, (pad + shadow * 0.35) * SS, (pad + w) * SS, (pad + h + shadow * 0.35) * SS],
            radius=r * SS, fill=shadow_alpha if shadow_alpha is not None else P["shadow"])
        sh = sh.filter(ImageFilter.GaussianBlur(shadow * SS * 0.6))
        img.alpha_composite(Image.merge("RGBA", (Image.new("L", (W, H), 0),) * 3 + (sh,)))
    shape = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(shape).rounded_rectangle(
        [pad * SS, pad * SS, (pad + w) * SS - 1, (pad + h) * SS - 1], radius=r * SS,
        fill=_rgb(fill) + (255,) if fill else None,
        outline=(_rgb(outline) + (255,)) if outline else None, width=max(1, int(width * SS)))
    img.alpha_composite(shape)
    return img.resize((w + 2 * pad, h + 2 * pad), Image.LANCZOS)


class Canvas(tk.Canvas):
    def __init__(self, parent, width, height, bg=None, **kw):
        super().__init__(parent, width=width, height=height, bg=bg or P["card"],
                         highlightthickness=0, bd=0, **kw)
        self._imgs = {}
        self._traces = []
        self.bind("<Destroy>", self._untrace, add="+")

    def keep(self, key, pil):
        self._imgs[key] = ImageTk.PhotoImage(pil)
        return self._imgs[key]

    def trace(self, var, fn):
        self._traces.append((var, var.trace_add("write", lambda *_: fn())))

    def _untrace(self, e=None):
        if e is not None and e.widget is not self:
            return
        for var, tid in self._traces:
            try:
                var.trace_remove("write", tid)
            except Exception:
                pass
        self._traces = []


class Card(tk.Frame):
    """A rounded panel. Put widgets in .body."""

    def __init__(self, parent, bg_outer, fill=None, radius=12, pad=(14, 10)):
        super().__init__(parent, bg=bg_outer)
        self.fill, self.radius, self.outer = fill or P["card"], radius, bg_outer
        self.back = Canvas(self, 10, 10, bg=bg_outer)
        self.back.place(x=0, y=0, relwidth=1, relheight=1)
        self.body = tk.Frame(self, bg=self.fill)
        self.body.pack(fill="both", expand=True, padx=px(pad[0]), pady=px(pad[1]))
        self.bind("<Configure>", self._draw)

    def _draw(self, e):
        if e.width < 4 or e.height < 4:
            return
        img = rounded(e.width, e.height, px(self.radius), self.fill, bg=self.outer,
                      outline=P["edge"] if P is not None else None, width=1)
        self.back.delete("all")
        self.back.create_image(0, 0, anchor="nw", image=self.back.keep("bg", img))


class Button(Canvas):
    """A filled pill button that can turn into a progress bar.

    Its colour fades between states instead of snapping, the progress fill
    glides, and `flash` shows a short "done" state.
    """

    def __init__(self, parent, text, command, width, height, font=None, bg=None):
        bg = bg or P["side"]
        super().__init__(parent, width, height, bg=bg, cursor="hand2")
        self.command, self.enabled = command, True
        self.w, self.h, self.font, self.text = width, height, font, text
        self.r = px(11)
        self.colour = self._from = self._to = P["accent"]
        self._pill = None
        self._flash = False
        self._pill_font = None
        self.bgimg = self.create_image(0, 0, anchor="nw")
        self.label = self.create_text(width / 2, height / 2, text=text, font=font, fill="#FFFFFF")
        self.fade = Tween(self, lambda t: self._paint(mix(self._from, self._to, t)), 1.0, ms=150)
        self.fill = Tween(self, self._paint_pill, 0.0, ms=320)
        self._paint(self.colour)
        self.bind("<Enter>", lambda e: self._show("hover"))
        self.bind("<Leave>", lambda e: self._show("normal"))
        self.bind("<ButtonPress-1>", lambda e: self._show("down", ms=70))
        self.bind("<ButtonRelease-1>", self._release)

    def _paint(self, colour):
        self.colour = colour
        self.itemconfigure(self.bgimg, image=self.keep(
            "bg", rounded(self.w, self.h, self.r, colour, bg=self["bg"])))

    def _go(self, colour, ms=150):
        self._from, self._to = self.colour, colour
        self.fade.jump(0.0)
        self.fade.to(1.0, ms)

    def _show(self, state, ms=150):
        if self._pill is not None or self._flash:
            return
        if not self.enabled:
            state = "disabled"
        self._go({"normal": P["accent"], "hover": P["accent_hover"], "down": P["accent_down"],
                  "disabled": P["accent_off"]}[state], ms)

    def _release(self, e):
        inside = 0 <= e.x <= self.w and 0 <= e.y <= self.h
        self._show("hover" if inside else "normal")
        if inside and self.enabled and self.command:
            self.command()

    def set_progress(self, frac, text=""):
        """Turn the button into a progress pill (frac 0..1), or back with None."""
        if frac is None:
            self._pill = None
            self._flash = False
            self.fill.jump(0.0)
            self.itemconfigure(self.label, state="normal", text=self.text)
            self._paint(P["accent"] if self.enabled else P["accent_off"])
            return
        if self._pill is None:
            self.fill.jump(0.0)
        self._flash = False
        self._pill = text
        self.itemconfigure(self.label, state="hidden")
        if abs(frac - self.fill.target) < 1e-4:
            self._paint_pill(self.fill.value)
        else:
            self.fill.to(frac)

    def _paint_pill(self, frac):
        if self._pill is None:
            return
        from .render import UI_FONT, load_font

        w, h = self.w * SS, self.h * SS
        if self._pill_font is None:
            self._pill_font = load_font(self.h * 0.36 * SS, UI_FONT)

        def layer(back, fore):
            im = Image.new("RGBA", (w, h), _rgb(back) + (255,))
            ImageDraw.Draw(im).text((w / 2, h / 2), self._pill, font=self._pill_font,
                                    fill=_rgb(fore), anchor="mm")
            return im

        base, top = layer(P["accent_soft"], P["accent"]), layer(P["accent"], "#FFFFFF")
        edge = int(w * max(0.0, min(1.0, frac)))
        if edge > 0:
            # the filled part gets a rounded end of its own, like a real progress bar
            cut = Image.new("L", (w, h), 0)
            ImageDraw.Draw(cut).rounded_rectangle([-h, 0, edge, h - 1], radius=self.r * SS, fill=255)
            base.paste(top, (0, 0), cut)
        shape = Image.new("L", (w, h), 0)
        ImageDraw.Draw(shape).rounded_rectangle([0, 0, w - 1, h - 1], radius=self.r * SS, fill=255)
        out = Image.new("RGBA", (w, h), _rgb(self["bg"]) + (255,))
        out.paste(base, (0, 0), shape)
        self.itemconfigure(self.bgimg, image=self.keep(
            "bg", out.resize((self.w, self.h), Image.LANCZOS)))

    def flash(self, text, colour, ms=1900):
        """Show `text` on a `colour` button for a moment (the 'done' state)."""
        self._flash = False
        self.itemconfigure(self.label, text=text, state="normal")
        self._go(colour, 260)
        self._flash = True
        self.after(ms, self._unflash)

    def _unflash(self):
        if not self._flash:
            return
        self._flash = False
        self.itemconfigure(self.label, text=self.text)
        self._show("normal", ms=320)

    def set_enabled(self, on):
        self.enabled = on
        self.configure(cursor="hand2" if on else "arrow")
        self._show("normal")


class Segmented(Canvas):
    """macOS style segmented control bound to a StringVar."""

    def __init__(self, parent, options, variable, width, height, font=None, bg=None,
                 on_click=None):
        bg = bg or P["card"]
        super().__init__(parent, width, height, bg=bg, cursor="hand2")
        self.options, self.var, self.on_click = options, variable, on_click
        self.seg = (width - 4) / len(options)
        self.create_image(0, 0, anchor="nw",
                          image=self.keep("track", rounded(width, height, px(8), P["track"], bg=bg)))
        knob = rounded(int(self.seg), height - 4, px(7), P["knob"] if P is PALETTES["light"] or
                       P["window"] != PALETTES["dark"]["window"] else "#5A5A5F", shadow=px(3),
                       shadow_alpha=40)
        self.pad = px(3) * 2
        self.knob = self.create_image(0, 0, anchor="nw", image=self.keep("knob", knob))
        self.labels = [self.create_text(2 + self.seg * (i + 0.5), height / 2, text=label, font=font,
                                        fill=P["text"]) for i, (_, label) in enumerate(options)]
        self.x = self._target()
        self._place()
        self.slide = Tween(self, self._move, self.x, ms=240)
        self.bind("<ButtonRelease-1>", self._click)
        self.trace(variable, lambda: self.slide.to(self._target()))

    def _index(self):
        keys = [k for k, _ in self.options]
        return keys.index(self.var.get()) if self.var.get() in keys else 0

    def _target(self):
        return 2 + self.seg * self._index()

    def _place(self):
        self.coords(self.knob, self.x - self.pad, 2 - self.pad)
        for i, item in enumerate(self.labels):
            self.itemconfigure(item, fill=P["text"] if i == self._index() else P["sub"])

    def _move(self, x):
        self.x = x
        self._place()

    def _click(self, e):
        i = int(min(len(self.options) - 1, max(0, (e.x - 2) // self.seg)))
        key = self.options[i][0]
        if self.on_click and self.on_click(key) is False:
            return
        self.var.set(key)


class Toggle(Canvas):
    """An iOS style switch bound to a BooleanVar. The knob glides and the track fades."""

    STEPS = 10

    def __init__(self, parent, variable, bg=None):
        bg = bg or P["card"]
        self.W, self.H = px(40), px(24)
        super().__init__(parent, self.W, self.H, bg=bg, cursor="hand2")
        self.var = variable
        self.track = self.create_image(0, 0, anchor="nw")
        k = self.H - 4
        self.sh = px(2)
        self.knob = self.create_image(0, 0, anchor="nw", image=self.keep(
            "knob", rounded(k, k, k // 2, "#FFFFFF", shadow=self.sh, shadow_alpha=50)))
        self.pos = Tween(self, self._place, 1.0 if variable.get() else 0.0, ms=220)
        self._place(self.pos.value)
        self.bind("<ButtonRelease-1>", lambda e: self.var.set(not self.var.get()))
        self.trace(variable, lambda: self.pos.to(1.0 if self.var.get() else 0.0))

    def _place(self, t):
        q = int(round(max(0.0, min(1.0, t)) * self.STEPS))
        key = "track%d" % q
        if key not in self._imgs:
            self.keep(key, rounded(self.W, self.H, self.H // 2,
                                   mix(P["track"], P["green"], q / self.STEPS), bg=self["bg"]))
        self.itemconfigure(self.track, image=self._imgs[key])
        x = 2 + (self.W - self.H) * t
        self.coords(self.knob, x - 2 * self.sh, 2 - 2 * self.sh)


class Swatches(Canvas):
    """One dot per look: left hand colour on the left half, right hand on the right."""

    def __init__(self, parent, variable, width, bg=None):
        bg = bg or P["card"]
        keys = list(theme.THEMES)
        self.D = px(26)
        self.GAP = max(px(8), int((width - 8 - len(keys) * self.D) / max(1, len(keys) - 1)))
        self.GAP = min(self.GAP, px(16))
        w = len(keys) * self.D + (len(keys) - 1) * self.GAP + 8
        super().__init__(parent, w, self.D + 8, bg=bg, cursor="hand2")
        self.keys, self.var = keys, variable
        for i, key in enumerate(keys):
            x = 4 + i * (self.D + self.GAP)
            self.create_image(x, 4, anchor="nw", image=self.keep(key, self._dot(theme.get(key), bg)))
        # one ring that slides to whichever look is picked
        self.ring = self.create_image(self._ring_x(), 0, anchor="nw",
                                      image=self.keep("ring", self._ring()))
        self.slide = Tween(self, lambda x: self.coords(self.ring, x, 0), self._ring_x(), ms=260)
        self.bind("<ButtonRelease-1>", self._click)
        self.trace(variable, lambda: self.slide.to(self._ring_x()))

    def _ring_x(self):
        i = self.keys.index(self.var.get()) if self.var.get() in self.keys else 0
        return i * (self.D + self.GAP)

    def _dot(self, pal, bg):
        d = self.D * SS
        img = Image.new("RGBA", (d, d), _rgb(bg) + (255,))
        dr = ImageDraw.Draw(img)
        dr.pieslice([0, 0, d - 1, d - 1], 90, 270, fill=pal["left"])
        dr.pieslice([0, 0, d - 1, d - 1], 270, 90, fill=pal["right"])
        dr.ellipse([0, 0, d - 1, d - 1], outline=(0, 0, 0, 30), width=SS)
        return img.resize((self.D, self.D), Image.LANCZOS)

    def _ring(self):
        d = (self.D + 8) * SS
        img = Image.new("RGBA", (d, d), (0, 0, 0, 0))
        ImageDraw.Draw(img).ellipse([SS, SS, d - SS - 1, d - SS - 1],
                                    outline=_rgb(P["accent"]) + (255,), width=int(2.2 * SS))
        return img.resize((self.D + 8, self.D + 8), Image.LANCZOS)

    def _click(self, e):
        i = int(max(0, min(len(self.keys) - 1, (e.x - 4) // (self.D + self.GAP))))
        self.var.set(self.keys[i])


class Field(tk.Frame):
    """A rounded, borderless text field with a placeholder."""

    def __init__(self, parent, variable, placeholder, width, height, font=None, bg=None):
        bg = bg or P["card"]
        super().__init__(parent, bg=bg)
        self.canvas = Canvas(self, width, height, bg=bg)
        self.canvas.pack()
        self.canvas.create_image(0, 0, anchor="nw", image=self.canvas.keep(
            "bg", rounded(width, height, px(8), P["field"], bg=bg)))
        self.entry = tk.Entry(self.canvas, textvariable=variable, font=font, bd=0, relief="flat",
                              bg=P["field"], fg=P["text"], insertbackground=P["text"],
                              highlightthickness=0)
        self.canvas.create_window(px(11), height / 2, anchor="w", window=self.entry,
                                  width=width - px(22))
        # a canvas item would sit under the entry, so the hint is a label inside it
        self.hint = tk.Label(self.entry, text=placeholder, font=font, bg=P["field"],
                             fg=P["faint"], bd=0, padx=0, pady=0, cursor="xterm")
        self.hint.bind("<Button-1>", lambda e: self.entry.focus_set())
        self.var = variable
        self.canvas.trace(variable, self._hint)
        self.entry.bind("<FocusIn>", lambda e: self._hint())
        self.entry.bind("<FocusOut>", lambda e: self._hint())
        self.canvas.bind("<Button-1>", lambda e: self.entry.focus_set())
        self._hint()

    def _hint(self):
        if self.var.get():
            self.hint.place_forget()
        else:
            self.hint.place(x=0, rely=0.5, anchor="w")


class ScrollArea(tk.Frame):
    """A frame that scrolls with the wheel when its content is taller than it."""

    def __init__(self, parent, bg):
        super().__init__(parent, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.body = tk.Frame(self.canvas, bg=bg)
        self.win = self.canvas.create_window(0, 0, anchor="nw", window=self.body)
        self.glide = Tween(self, self._goto, 0.0, ms=240)
        # a slim thumb on the right edge, only there when there is more to scroll to
        self.thumb = tk.Frame(self, bg=P["line"], width=max(3, px(4)))
        self.body.bind("<Configure>", lambda e: self._fit())
        self.canvas.bind("<Configure>", lambda e: (
            self.canvas.itemconfigure(self.win, width=e.width), self._fit()))
        self.bind("<Enter>", lambda e: [self.bind_all(s, self._wheel) for s in
                                        ("<MouseWheel>", "<Button-4>", "<Button-5>")])
        self.bind("<Leave>", lambda e: [self.unbind_all(s) for s in
                                        ("<MouseWheel>", "<Button-4>", "<Button-5>")])

    def _fit(self):
        h = self.body.winfo_reqheight()
        self.canvas.configure(scrollregion=(0, 0, 1, h))
        if h <= self.canvas.winfo_height():
            self.glide.jump(0.0)
            self.canvas.yview_moveto(0)
        self._thumb()

    def _thumb(self):
        h, view = self.body.winfo_reqheight(), self.canvas.winfo_height()
        if h <= view + 1 or view < 20:
            self.thumb.place_forget()
            return
        top = self.canvas.yview()[0]
        self.thumb.place(relx=1.0, anchor="ne", y=int(top * view), height=max(px(24), int(view * view / h)))

    def _goto(self, y):
        h = self.body.winfo_reqheight()
        self.canvas.yview_moveto(y / h if h else 0)
        self._thumb()

    def _wheel(self, e):
        h, view = self.body.winfo_reqheight(), self.canvas.winfo_height()
        if h <= view:
            return
        if getattr(e, "num", None) in (4, 5):
            step = -1 if e.num == 4 else 1
        elif sys.platform == "darwin":
            step = -e.delta / 3
        else:
            step = -e.delta / 120
        self.glide.to(min(max(0.0, self.glide.target + step * px(54)), h - view))


class Pill(Canvas):
    """A small tinted pill button whose text can change (used for updates)."""

    def __init__(self, parent, text, command, font, bg=None):
        self.bg = bg or P["side"]
        self.font = font
        self.h = px(28)
        super().__init__(parent, px(60), self.h, bg=self.bg, cursor="hand2")
        self.command = command
        self.img = self.create_image(0, 0, anchor="nw")
        self.label = self.create_text(0, self.h / 2, anchor="center", font=font)
        self.hover = False
        self.solid = False
        self.bind("<Enter>", lambda e: self._hover(True))
        self.bind("<Leave>", lambda e: self._hover(False))
        self.bind("<ButtonRelease-1>", lambda e: self.command and self.command())
        self.set(text)

    def _hover(self, on):
        self.hover = on
        self._paint()

    def set(self, text, solid=False, clickable=True):
        self.text, self.solid, self.clickable = text, solid, clickable
        self.configure(cursor="hand2" if clickable else "arrow")
        self._paint()

    def _paint(self):
        w = tkfont.Font(font=self.font).measure(self.text) + px(28)
        self.configure(width=w)
        if self.solid:
            fill = P["accent_hover"] if self.hover and self.clickable else P["accent"]
            ink = "#FFFFFF"
        else:
            fill = P["line"] if self.hover and self.clickable else P["track"]
            ink = P["accent"] if self.clickable else P["sub"]
        self.itemconfigure(self.img, image=self.keep(
            "bg", rounded(w, self.h, self.h // 2, fill, bg=self.bg)))
        self.coords(self.label, w / 2, self.h / 2)
        self.itemconfigure(self.label, text=self.text, fill=ink)


class IconButton(Canvas):
    """A small round button with a drawn glyph (sun or moon)."""

    def __init__(self, parent, glyph, command, bg=None):
        bg = bg or P["side"]
        self.S = px(30)
        super().__init__(parent, self.S, self.S, bg=bg, cursor="hand2")
        self.command = command
        self.normal = self.keep("n", self._draw(glyph, bg, P["track"]))
        self.hover = self.keep("h", self._draw(glyph, bg, P["line"]))
        self.img = self.create_image(0, 0, anchor="nw", image=self.normal)
        self.bind("<Enter>", lambda e: self.itemconfigure(self.img, image=self.hover))
        self.bind("<Leave>", lambda e: self.itemconfigure(self.img, image=self.normal))
        self.bind("<ButtonRelease-1>", lambda e: self.command())

    def _draw(self, glyph, bg, fill):
        s = self.S * SS
        img = Image.new("RGBA", (s, s), _rgb(bg) + (255,))
        d = ImageDraw.Draw(img)
        d.ellipse([0, 0, s - 1, s - 1], fill=_rgb(fill))
        ink = _rgb(P["text"])
        c = s / 2
        if glyph == "sun":
            r = s * 0.15
            d.ellipse([c - r, c - r, c + r, c + r], fill=ink)
            import math

            for k in range(8):
                a = k * math.pi / 4
                d.line([c + math.cos(a) * s * 0.24, c + math.sin(a) * s * 0.24,
                        c + math.cos(a) * s * 0.32, c + math.sin(a) * s * 0.32],
                       fill=ink, width=int(s * 0.055))
        else:
            r = s * 0.24
            d.ellipse([c - r, c - r, c + r, c + r], fill=ink)
            off = s * 0.13
            d.ellipse([c - r + off, c - r - off * 0.6, c + r + off, c + r - off * 0.6], fill=_rgb(fill))
        return img.resize((self.S, self.S), Image.LANCZOS)


# the window ---------------------------------------------------------------

class App:
    def __init__(self, root):
        global UI
        self.root = root
        UI = self._screen_scale()
        self.settings = load_settings()
        self.events = queue.Queue()
        self.cancel = threading.Event()
        self.busy = False
        self.midi_for_input = {}
        self._midi_lock = threading.Lock()
        self.preview_job = None
        self.preview_token = 0
        self.mode = "idle"          # what the stage shows: empty, message, play, idle
        self.player = None          # the live preview of the song
        self.play_t = 0.0
        self.play_song = None
        self.want = None            # (token, player, time) the main thread asks for
        self.ready = None           # (token, time, picture) the render thread hands back
        self.shown = None           # the picture on the stage right now
        self.fade_from = None
        self.fade_t0 = 0.0
        self.ring_frac = None
        self.ring_shown = 0.0
        self.hover = None
        self._last_tick = time.perf_counter()
        self.result = None
        self.update_info = None
        self._updating = False
        self._busy_text = ""
        self._stage_msg = None

        self.input_path = tk.StringVar()
        self.title_text = tk.StringVar()
        self.fmt = tk.StringVar(value="phone")
        self.theme_key = tk.StringVar(value=self.settings.get("look", theme.DEFAULT_THEME)
                                      if self.settings.get("look") in theme.THEMES else theme.DEFAULT_THEME)
        self.sound = tk.StringVar(value="piano")
        self.own_audio = ""
        self.smooth = tk.BooleanVar(value=True)
        self.pedal_blocks = tk.BooleanVar(value=False)
        self.sparks = tk.BooleanVar(value=True)
        self.hands = tk.BooleanVar(value=self.settings.get("hands", True))
        self.status = tk.StringVar(value="")

        self._fonts()
        self._window()
        self.appearance = self.settings.get("appearance", "system")
        self._apply_palette()
        self._build()

        for var in (self.fmt, self.theme_key, self.pedal_blocks, self.sparks, self.hands,
                    self.title_text):
            var.trace_add("write", lambda *_: self.schedule_preview())
        self.fmt.trace_add("write", lambda *_: self.fmt_hint.configure(text=FORMAT_HINT[self.fmt.get()]))
        self.theme_key.trace_add("write", lambda *_: self._look_changed())
        self.hands.trace_add("write", lambda *_: self._remember())
        self.sound.trace_add("write", lambda *_: self._sound_hint())
        self.root.after(80, self._poll)
        threading.Thread(target=self._render_loop, daemon=True).start()
        self.root.after(int(1000 / PREVIEW_FPS), self._tick)
        self.root.after(1500, self._check_update)
        self._fade_in()

    # setup ---------------------------------------------------------------

    def _screen_scale(self):
        if sys.platform == "darwin":
            return 1.0  # macOS already works in points
        try:
            return max(1.0, min(3.0, self.root.winfo_fpixels("1i") / 96.0))
        except Exception:
            return 1.0

    def _fade_in(self):
        """The window fades in instead of popping up (where the system can do that)."""
        try:
            self.root.attributes("-alpha", 0.0)
            Tween(self.root, lambda a: self.root.attributes("-alpha", a), 0.0, ms=260).to(1.0)
            self.root.after(600, lambda: self.root.attributes("-alpha", 1.0))
        except tk.TclError:
            pass

    def _fonts(self):
        families = set(tkfont.families())
        family = tkfont.nametofont("TkDefaultFont").actual()["family"]
        if sys.platform.startswith("win"):
            family = next((f for f in ("Segoe UI Variable Text", "Segoe UI") if f in families), "Segoe UI")
        elif sys.platform == "darwin":
            family = next((f for f in ("SF Pro Text", ".AppleSystemUIFont", "Helvetica Neue")
                           if f in families), family)
        else:
            family = next((f for f in ("Inter", "Cantarell", "Ubuntu", "Noto Sans", "DejaVu Sans")
                           if f in families), family)
        display = family
        if sys.platform.startswith("win") and "Segoe UI Variable Display" in families:
            display = "Segoe UI Variable Display"
        self.f_title = (display, 17, "bold")
        self.f_body = (family, 11)
        self.f_bold = (family, 11, "bold")
        self.f_small = (family, 9)
        self.f_head = (family, 9, "bold")
        self.f_button = (family, 12, "bold")
        self.f_big = (display, 18, "bold")

    def _window(self):
        r = self.root
        r.title("NoteFall")
        sw, sh = r.winfo_screenwidth(), r.winfo_screenheight()
        w, h = min(px(1160), int(sw * 0.9)), min(px(900), int(sh * 0.9))
        r.geometry("%dx%d+%d+%d" % (w, h, (sw - w) // 2, max(0, (sh - h) // 3)))
        r.minsize(min(px(920), w), min(px(700), h))
        try:
            from .icon import draw_icon

            self._icon = ImageTk.PhotoImage(draw_icon(128))
            r.iconphoto(True, self._icon)
        except Exception:
            pass

    def _apply_palette(self):
        global P
        dark = self.appearance == "dark" or (self.appearance == "system" and system_is_dark())
        P = PALETTES["dark" if dark else "light"]
        self.dark = dark
        self.root.configure(bg=P["window"])
        dark_title_bar(self.root, dark)

    def _toggle_appearance(self):
        self.appearance = "light" if self.dark else "dark"
        self._remember()
        self._apply_palette()
        for child in self.root.winfo_children():
            child.destroy()
        self._build()
        if self.input_path.get():
            self._song_chosen(self.input_path.get(), quiet=True)
        if self.result:
            self.after_row.pack(side="right")
        self._stage_changed()

    def _remember(self):
        self.settings.update(appearance=self.appearance, hands=bool(self.hands.get()),
                             look=self.theme_key.get())
        save_settings(self.settings)

    def _label(self, parent, text, font=None, fg=None, bg=None, **kw):
        return tk.Label(parent, text=text, font=font or self.f_body, fg=fg or P["text"],
                        bg=bg or P["card"], **kw)

    def _group(self, parent, title=None, note=None):
        """A titled group card, like a section in System Settings. Returns its body."""
        if title:
            self._label(parent, title.upper(), self.f_head, fg=P["sub"], bg=P["side"]).pack(
                anchor="w", padx=px(4), pady=(px(14), px(5)))
        card = Card(parent, P["side"])
        card.pack(fill="x")
        if note is not None:
            lab = self._label(parent, note, self.f_small, fg=P["faint"], bg=P["side"], anchor="w",
                              justify="left", wraplength=self.CW - px(12))
            lab.pack(fill="x", padx=px(4), pady=(px(5), 0))
            card.note = lab
        return card.body, card

    def _row(self, body, first=False):
        if not first:
            tk.Frame(body, bg=P["line"], height=1).pack(fill="x", pady=px(6))
        row = tk.Frame(body, bg=P["card"])
        row.pack(fill="x")
        return row

    def _build(self):
        self.SIDE = px(360)
        self.CW = self.SIDE - px(28) * 2       # width of a group card
        IW = self.CW - px(14) * 2              # width inside a card

        side_outer = tk.Frame(self.root, bg=P["side"], width=self.SIDE)
        side_outer.pack(side="right", fill="y")
        side_outer.pack_propagate(False)
        tk.Frame(self.root, bg=P["edge"], width=1).pack(side="right", fill="y")
        side = tk.Frame(side_outer, bg=P["side"])
        gutter = px(14)  # room on the right for the scroll thumb
        side.pack(fill="both", expand=True, padx=(px(28), px(28) - gutter), pady=(px(22), px(22)))

        # header
        head = tk.Frame(side, bg=P["side"])
        head.pack(fill="x", padx=(0, gutter))
        try:
            from .icon import draw_icon

            ic = Canvas(head, px(34), px(34), bg=P["side"])
            ic.create_image(0, 0, anchor="nw", image=ic.keep("i", draw_icon(256).resize(
                (px(34), px(34)), Image.LANCZOS)))
            ic.pack(side="left", padx=(0, px(10)))
        except Exception:
            pass
        names = tk.Frame(head, bg=P["side"])
        names.pack(side="left")
        line1 = tk.Frame(names, bg=P["side"])
        line1.pack(anchor="w")
        self._label(line1, "NoteFall", self.f_title, bg=P["side"]).pack(side="left")
        self._label(line1, __version__, self.f_small, fg=P["faint"], bg=P["side"]).pack(
            side="left", padx=(px(6), 0), pady=(px(4), 0))
        self._label(names, "Piano music in. Falling notes out.", self.f_small, fg=P["sub"],
                    bg=P["side"]).pack(anchor="w")
        IconButton(head, "sun" if self.dark else "moon", self._toggle_appearance).pack(side="right")

        # bottom: button and status (packed first so it always has room)
        bottom = tk.Frame(side, bg=P["side"])
        bottom.pack(side="bottom", fill="x", padx=(0, gutter))
        status_row = tk.Frame(bottom, bg=P["side"], height=px(24))
        status_row.pack(fill="x", pady=(0, px(8)))
        status_row.pack_propagate(False)
        self.status_label = self._label(status_row, "", self.f_small, fg=P["sub"], bg=P["side"],
                                        textvariable=self.status, anchor="w")
        self.status_label.pack(side="left", fill="x", expand=True)
        self.after_row = tk.Frame(status_row, bg=P["side"])
        for text, fn in (("Show in Folder", lambda: show_in_folder(self.result)),
                         ("Play", lambda: open_path(self.result))):
            link = self._label(self.after_row, text, self.f_small, fg=P["accent"], bg=P["side"],
                               cursor="hand2")
            link.pack(side="right", padx=(px(12), 0))
            link.bind("<Button-1>", lambda e, fn=fn: fn())
        self.go = Button(bottom, "Create Video", self.start, width=self.CW, height=px(44),
                         font=self.f_button)
        self.go.pack()
        self.update_pill = Pill(bottom, "Check for updates", self._update_click, self.f_small)
        self.update_pill.pack(pady=(px(12), 0))
        if self.update_info:
            self._on_update_event("update", self.update_info)
        self.go.bind("<Enter>", lambda e: self.busy and self.status.set("Click to stop"), add="+")
        self.go.bind("<Leave>", lambda e: self.busy and self.status.set(self._busy_text), add="+")
        self.go.set_enabled(bool(self.input_path.get()) and not self.busy)

        scroll = ScrollArea(side, P["side"])
        scroll.pack(fill="both", expand=True, pady=(px(2), px(12)))
        side = tk.Frame(scroll.body, bg=P["side"])
        side.pack(fill="both", expand=True, padx=(0, gutter))

        # song
        body, _ = self._group(side, "Song", "MIDI files are exact. Recordings (mp3, mp4, wav…) "
                                            "are listened to, so a few notes can be off.")
        self.song_note = _.note
        row = self._row(body, first=True)
        self.song_label = self._label(row, "No song yet", fg=P["sub"], anchor="w")
        self.song_label.pack(side="left", fill="x", expand=True)
        self.change = self._label(row, "Choose…", fg=P["accent"], cursor="hand2")
        self.change.pack(side="right")
        self.change.bind("<Button-1>", lambda e: self.pick_input())
        self.song_label.bind("<Button-1>", lambda e: self.pick_input())
        # shown once a recording has been listened to: keep the notes as a MIDI file
        self.midi_row = tk.Frame(body, bg=P["card"])
        tk.Frame(self.midi_row, bg=P["line"], height=1).pack(fill="x", pady=px(6))
        row = tk.Frame(self.midi_row, bg=P["card"])
        row.pack(fill="x")
        self._label(row, "Notes as MIDI", anchor="w").pack(side="left")
        save = self._label(row, "Save…", fg=P["accent"], cursor="hand2")
        save.pack(side="right")
        save.bind("<Button-1>", lambda e: self.save_midi())
        self._midi_row_update()

        # video
        body, _ = self._group(side, "Video")
        row = self._row(body, first=True)
        self._label(row, "Format").pack(side="left")
        self.fmt_hint = self._label(row, FORMAT_HINT[self.fmt.get()], self.f_small, fg=P["faint"])
        self.fmt_hint.pack(side="right")
        Segmented(body, FORMATS, self.fmt, width=IW, height=px(30), font=self.f_body).pack(
            fill="x", pady=(px(8), px(2)))
        row = self._row(body)
        self._label(row, "Look").pack(side="left")
        self.theme_hint = self._label(row, self._theme_name(), self.f_small, fg=P["faint"])
        self.theme_hint.pack(side="right")
        Swatches(body, self.theme_key, IW).pack(anchor="w", pady=(px(8), px(2)))
        row = self._row(body)
        self._label(row, "Title").pack(side="left")
        Field(row, self.title_text, "Optional", width=IW - px(64), height=px(30),
              font=self.f_body).pack(side="right")

        # sound
        body, card = self._group(side, "Sound", "")
        self.sound_hint = card.note
        Segmented(body, SOUNDS, self.sound, width=IW, height=px(30), font=self.f_body,
                  on_click=self._sound_click).pack(fill="x", pady=px(2))
        self._sound_hint()

        # options
        body, _ = self._group(side, "Options")
        for i, (text, var) in enumerate((("Hands on the keys", self.hands),
                                         ("Smooth motion (60 fps)", self.smooth),
                                         ("Notes ring with the pedal", self.pedal_blocks),
                                         ("Sparks", self.sparks))):
            row = self._row(body, first=i == 0)
            self._label(row, text).pack(side="left")
            Toggle(row, var).pack(side="right")

        # stage: the preview
        self.stage = Canvas(self.root, 600, 600, bg=P["window"])
        self.stage.pack(side="left", fill="both", expand=True, padx=px(28), pady=px(28))
        self.stage.bind("<Configure>", lambda e: self._stage_changed())
        self.stage.bind("<Button-1>", lambda e: (not self.input_path.get()) and self.pick_input())
        self.stage.bind("<Enter>", lambda e: self.hover and self.hover.to(1.0))
        self.stage.bind("<Leave>", lambda e: self.hover and self.hover.to(0.0))
        self.stage_img = self.stage.create_image(0, 0, anchor="center")
        self.stage_text = self.stage.create_text(0, 0, text="", font=self.f_big, fill=P["text"])
        self.stage_sub = self.stage.create_text(0, 0, text="", font=self.f_body, fill=P["sub"],
                                                justify="center")
        self.hover = Tween(self.stage, lambda v: None, 0.0, ms=200)
        self.photo = None
        self.shown = None
        self.player = None
        self.want = None
        self._cards = {}
        self.mode = "idle"

    # stage ----------------------------------------------------------------

    def _preview_box(self):
        cw, ch = max(200, self.stage.winfo_width()), max(200, self.stage.winfo_height())
        aw, ah = ASPECT[self.fmt.get()]
        scale = min((cw - px(40)) / aw, (ch - px(40)) / ah)
        return int(aw * scale) // 2 * 2, int(ah * scale) // 2 * 2

    def _stage_changed(self):
        if not self.input_path.get():
            self._empty_stage()
        elif self._stage_msg:
            self._stage_message(*self._stage_msg, progress=self.ring_frac,
                                ring=getattr(self, "ring_on", False))
        else:
            cw, ch = self.stage.winfo_width(), self.stage.winfo_height()
            self.stage.coords(self.stage_img, cw / 2, ch / 2)
            self.schedule_preview()

    def _put(self, img, x=None, y=None):
        """Show a picture on the stage, reusing the same Tk image when the size allows."""
        if self.photo is None or (self.photo.width(), self.photo.height()) != img.size:
            self.photo = ImageTk.PhotoImage(img)
            self.stage.itemconfigure(self.stage_img, image=self.photo)
        else:
            self.photo.paste(img)
        cw, ch = self.stage.winfo_width(), self.stage.winfo_height()
        self.stage.coords(self.stage_img, cw / 2 if x is None else x, ch / 2 if y is None else y)

    # the empty state: a small NoteFall playing by itself inside the drop card

    def _empty_stage(self):
        cw, ch = max(200, self.stage.winfo_width()), max(200, self.stage.winfo_height())
        w, h = min(px(420), cw - px(60)), min(px(300), ch - px(60))
        self._card_size = (w, h)
        self._cards = {}
        self.mode = "empty"
        self.player = self.want = None
        self._stage_msg = None
        self.stage.itemconfigure(self.stage_text, text="Choose a song", fill=P["text"])
        self.stage.itemconfigure(self.stage_sub, text="A MIDI file, or any recording of a piano")
        self.stage.coords(self.stage_text, cw / 2, ch / 2 + h * 0.14)
        self.stage.coords(self.stage_sub, cw / 2, ch / 2 + h * 0.14 + px(30))
        self.stage.configure(cursor="hand2")
        self._draw_empty(time.perf_counter())

    def _card(self, q):
        """The drop card, its border leaning towards blue as the mouse comes over it."""
        if q not in self._cards:
            w, h = self._card_size
            card = rounded(w, h, px(22), mix(P["card"], P["accent_soft"], q / 6 * 0.35),
                           outline=mix(P["line"], P["accent"], q / 6),
                           width=1.5 * UI, bg=P["window"])
            self._cards[q] = card.convert("RGB")
        return self._cards[q]

    LANES = ((0.00, 0.34, 0), (0.37, 0.22, 1), (0.71, 0.30, 0), (0.18, 0.42, 1),
             (0.55, 0.20, 0), (0.86, 0.36, 1), (0.29, 0.26, 0))

    def _draw_empty(self, now):
        w, h = self._card_size
        q = int(round(self.hover.value * 6))
        img = self._card(q).copy()
        aw, ah = min(px(168), w - px(40)), int(h * 0.36)
        key_h = max(3, px(7))
        s = SS
        layer = Image.new("RGB", (aw * s, (ah + key_h + px(5)) * s), img.getpixel((w // 2, h // 3)))
        d = ImageDraw.Draw(layer)
        lane = aw * s / len(self.LANES)
        bar_w = lane * 0.56
        floor = ah * s
        back = layer.getpixel((0, 0))
        for i, (offset, length, hand) in enumerate(self.LANES):
            colour = P["accent"] if hand else P["green"]
            x0 = i * lane + (lane - bar_w) / 2
            L = length * floor
            y1 = ((now * 0.22 + offset) % 1.0) * (floor + L)
            y0 = y1 - L
            top, bottom = max(0.0, y0), min(float(floor), y1)
            if bottom - top > 2:
                # bars fade in as they enter at the top
                fade = min(1.0, bottom / (floor * 0.35))
                d.rounded_rectangle([x0, top, x0 + bar_w, bottom],
                                    radius=min(bar_w * 0.32, (bottom - top) / 2),
                                    fill=mix("#%02X%02X%02X" % back, colour, fade))
            hit = y0 < floor <= y1
            d.rounded_rectangle([i * lane + s, floor + px(5) * s, (i + 1) * lane - s,
                                 floor + (px(5) + key_h) * s], radius=key_h * s * 0.4,
                                fill=colour if hit else P["track"])
        layer = layer.resize((aw, ah + key_h + px(5)), Image.LANCZOS)
        img.paste(layer, ((w - aw) // 2, int(h * 0.12)))
        self._put(img)

    # messages, with a progress ring while a recording is listened to

    def _stage_message(self, title, sub="", progress=None, ring=False):
        self._stage_msg = (title, sub)
        self.player = self.want = None
        if self.mode != "message" or not ring:
            self.ring_shown = 0.0
            self.stage.itemconfigure(self.stage_img, image="")
            self.photo = None
        self.mode = "message"
        self.ring_on = ring
        self.ring_frac = progress
        cw, ch = self.stage.winfo_width(), self.stage.winfo_height()
        lift = px(34) if ring else 0
        self.stage.itemconfigure(self.stage_text, text=title)
        self.stage.itemconfigure(self.stage_sub, text=sub, width=max(200, cw - px(80)))
        self.stage.coords(self.stage_text, cw / 2, ch / 2 - px(10) + lift)
        self.stage.coords(self.stage_sub, cw / 2, ch / 2 + px(22) + lift)
        self.stage.configure(cursor="")

    def _draw_ring(self, now):
        if not getattr(self, "ring_on", False):
            return
        size = px(64)
        s = size * SS
        img = Image.new("RGB", (s, s), _rgb(P["window"]))
        d = ImageDraw.Draw(img)
        t = int(s * 0.1)
        box = [t, t, s - t, s - t]
        d.arc(box, 0, 360, fill=_rgb(P["track"]), width=t)
        if self.ring_frac is None:
            a = (now * 300) % 360          # nothing to measure yet: a turning arc
            d.arc(box, a, a + 90, fill=_rgb(P["accent"]), width=t)
            ends = (a, a + 90)
        else:
            self.ring_shown += (self.ring_frac - self.ring_shown) * 0.18
            ends = (-90, -90 + 360 * max(0.01, self.ring_shown))
            d.arc(box, ends[0], ends[1], fill=_rgb(P["accent"]), width=t)
        r = (s - 2 * t) / 2 - t / 2
        for a in ends:  # round caps
            x, y = s / 2 + math.cos(math.radians(a)) * r, s / 2 + math.sin(math.radians(a)) * r
            d.ellipse([x - t / 2, y - t / 2, x + t / 2, y + t / 2], fill=_rgb(P["accent"]))
        cw, ch = self.stage.winfo_width(), self.stage.winfo_height()
        self._put(img.resize((size, size), Image.LANCZOS), y=ch / 2 - px(40))

    # the live preview: the song really plays, at the size it is shown

    def _dress(self, player, frame):
        """Rounded corners and a soft shadow around a preview frame."""
        img = player.base.copy()
        img.paste(frame, (player.pad, player.pad), player.mask)
        return img

    def _prepare(self, player, w, h):
        r = max(px(10), min(w, h) // 22)
        mask = Image.new("L", (w * SS, h * SS), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, w * SS - 1, h * SS - 1], radius=r * SS, fill=255)
        player.mask = mask.resize((w, h), Image.LANCZOS)
        player.base = rounded(w, h, r, "#000000", shadow=px(14), bg=P["window"]).convert("RGB")
        player.pad = (player.base.width - w) // 2
        return player

    def _render_loop(self):
        """Draws preview frames off the main thread, always the newest one asked for."""
        last = None
        while True:
            job = self.want
            if job is None or job is last:
                time.sleep(0.004)
                continue
            last = job
            token, player, t = job
            try:
                self.ready = (token, self._dress(player, player.frame(t)))
            except Exception:
                time.sleep(0.05)

    def _start_player(self, player, song):
        was_playing = self.mode == "play" and self.shown is not None
        if song != self.play_song or self.player is None:
            if song != self.play_song:
                # a new song starts just before its first note lands
                self.play_t = max(player.begin, player.first - 1.2)
            self.play_song = song
        self.play_t = min(max(self.play_t, player.begin), player.end)
        size = player.base.size
        if was_playing and self.shown.size == size:
            self.fade_from = self.shown                      # same size: cross-fade
        elif was_playing:
            self.fade_from = None                            # resized: just swap
        else:
            self.fade_from = Image.new("RGB", size, _rgb(P["window"]))  # fade in
        self.fade_t0 = None
        self._stage_msg = None
        self.player = player
        self.mode = "play"
        self.ready = None
        self.stage.configure(cursor="")
        self.stage.itemconfigure(self.stage_text, text="")
        self.stage.itemconfigure(self.stage_sub, text="")

    def _advance(self, dt, now):
        player = self.player
        if player is None:
            return
        if not self.busy:
            self.play_t += dt
            if self.play_t > player.end:
                self.play_t = player.begin
        self.want = (self.preview_token, player, self.play_t)
        got, self.ready = self.ready, None
        if not got or got[0] != self.preview_token:
            return
        img = got[1]
        if self.fade_from is not None:
            if self.fade_t0 is None:
                self.fade_t0 = now
            f = (now - self.fade_t0) / 0.28
            if f >= 1.0 or self.fade_from.size != img.size:
                self.fade_from = None
            else:
                self.shown = img
                self._put(Image.blend(self.fade_from, img, ease(f)))
                return
        self.shown = img
        self._put(img)

    def _tick(self):
        now = time.perf_counter()
        dt, self._last_tick = min(0.1, now - self._last_tick), now
        try:
            if self.mode == "empty":
                self._draw_empty(now)
            elif self.mode == "message":
                self._draw_ring(now)
            elif self.mode == "play":
                self._advance(dt, now)
        except tk.TclError:
            pass
        self.root.after(int(1000 / PREVIEW_FPS), self._tick)

    def schedule_preview(self):
        if self.preview_job:
            self.root.after_cancel(self.preview_job)
        self.preview_job = self.root.after(180, self._preview)

    def _preview(self):
        self.preview_job = None
        path = self.input_path.get()
        if not path:
            return
        self.preview_token += 1
        token = self.preview_token
        w, h = self._preview_box()
        opts = dict(width=w, height=h, theme_name=self.theme_key.get(),
                    title=self.title_text.get() or None, particles=self.sparks.get(),
                    hands=self.hands.get(), sustain="pedal" if self.pedal_blocks.get() else "keys")

        def work():
            try:
                midi = self._midi(path, preview=True,
                                  on_progress=lambda f: self.events.put(("listen", token, f)))
                from .render import preview_player

                player = self._prepare(preview_player(midi, fps=PREVIEW_FPS, **opts), w, h)
                self.events.put(("preview", token, player, path))
            except Exception as exc:
                self.events.put(("preview_error", token, str(exc)))

        threading.Thread(target=work, daemon=True).start()

    # choices --------------------------------------------------------------

    def _theme_name(self):
        return theme.THEMES[self.theme_key.get()]["label"].split(" (")[0]

    def _look_changed(self):
        self.theme_hint.configure(text=self._theme_name())
        self._remember()

    def _is_midi(self, path=None):
        return os.path.splitext(path or self.input_path.get())[1].lower() in MIDI_EXT

    def _sound_hint(self):
        s = self.sound.get()
        if s == "piano":
            text = "A piano sound played from the notes."
        elif s == "mine":
            text = ("Using " + os.path.basename(self.own_audio)) if self.own_audio else "Your own recording."
        else:
            text = "A silent video."
        try:
            self.sound_hint.configure(text=text)
        except (tk.TclError, AttributeError):
            pass

    def _sound_click(self, key):
        if key == "piano" and self.input_path.get() and not self._is_midi():
            self.status.set("Recordings keep their own sound.")
            return False
        if key == "mine":
            if not self._is_midi() and self.input_path.get():
                self.own_audio = self.input_path.get()
            else:
                path = filedialog.askopenfilename(
                    title="Choose the recording to use as sound",
                    filetypes=[("Audio or video", " ".join("*" + e for e in MEDIA_EXT)),
                               ("All files", "*")])
                if not path:
                    return False
                self.own_audio = path
        return True

    def pick_input(self):
        if self.busy:
            return
        path = filedialog.askopenfilename(
            title="Choose a MIDI file or a piano recording",
            filetypes=[("Songs", " ".join("*" + e for e in MIDI_EXT + MEDIA_EXT)),
                       ("MIDI", " ".join("*" + e for e in MIDI_EXT)),
                       ("Recordings", " ".join("*" + e for e in MEDIA_EXT)),
                       ("All files", "*")])
        if path:
            self._song_chosen(path)

    def _song_chosen(self, path, quiet=False):
        self.input_path.set(path)
        name = os.path.basename(path)
        self.song_label.configure(text=name if len(name) < 32 else name[:29] + "…", fg=P["text"])
        self.change.configure(text="Change")
        if quiet:
            self.go.set_enabled(not self.busy)
            return
        self.result = None
        self.after_row.pack_forget()
        # the title stays whatever you typed: file names like "V24044gl00..." are no title
        if self._is_midi(path):
            self.song_note.configure(text="MIDI file. The notes will be exact.")
            if self.own_audio and self.sound.get() == "mine" \
                    and self.own_audio == getattr(self, "_last_recording", None):
                self.own_audio = ""
                self.sound.set("piano")
        else:
            self.song_note.configure(text="Recording. NoteFall listens for the notes with a piano "
                                          "model, so a few can be off. For a perfect result use a MIDI.")
            self.own_audio = path
            self._last_recording = path
            if self.sound.get() == "piano":
                self.sound.set("mine")
        self._sound_hint()
        self._midi_row_update()
        self.status.set("")
        self.go.set_enabled(True)
        self.schedule_preview()

    def _midi(self, path, preview=False, on_progress=None):
        if self._is_midi(path):
            return path
        if path in self.midi_for_input:
            return self.midi_for_input[path]
        if preview:
            self.events.put(("stage", "Listening…", "Finding every note in your recording. "
                                                    "This takes a moment the first time."))
        from .transcribe import transcribe

        with self._midi_lock:  # the preview and Create Video never listen twice at once
            if path not in self.midi_for_input:
                self.midi_for_input[path] = transcribe(
                    path, on_progress=on_progress,
                    on_status=lambda s: self.events.put(("stage", s, "")) if preview else None)
        self.events.put(("heard", path))
        return self.midi_for_input[path]

    def _midi_row_update(self):
        """The 'Notes as MIDI' row is only there for a recording that has been listened to."""
        try:
            if self.input_path.get() in self.midi_for_input:
                self.midi_row.pack(fill="x")
            else:
                self.midi_row.pack_forget()
        except (tk.TclError, AttributeError):
            pass

    def save_midi(self):
        path = self.input_path.get()
        midi = self.midi_for_input.get(path)
        if not midi:
            return
        default = os.path.splitext(path)[0] + ".mid"
        out = filedialog.asksaveasfilename(
            title="Save the notes as MIDI", defaultextension=".mid",
            initialdir=os.path.dirname(default), initialfile=os.path.basename(default),
            filetypes=[("MIDI file", "*.mid")])
        if not out:
            return
        try:
            shutil.copyfile(midi, out)
        except OSError as exc:
            messagebox.showerror("NoteFall", "Couldn't save the MIDI: %s" % exc)
            return
        name = os.path.basename(out)
        self.status.set("Saved " + (name if len(name) < 22 else name[:19] + "…"))

    # rendering ------------------------------------------------------------

    def start(self):
        if self.busy:
            self.cancel.set()
            self._set_busy_text("Stopping…")
            return
        path = self.input_path.get()
        if not path:
            self.pick_input()
            return
        default = os.path.splitext(path)[0] + "-notefall.mp4"
        out = filedialog.asksaveasfilename(
            title="Save video as", defaultextension=".mp4",
            initialdir=os.path.dirname(default), initialfile=os.path.basename(default),
            filetypes=[("MP4 video", "*.mp4")])
        if not out:
            return
        self.busy = True
        self.cancel.clear()
        self.after_row.pack_forget()
        self._set_busy_text("Getting ready…")
        self.go.set_progress(0, "Creating Video")

        fmt, sound, own, is_midi = self.fmt.get(), self.sound.get(), self.own_audio, self._is_midi(path)
        opts = dict(theme_name=self.theme_key.get(), title=self.title_text.get() or None,
                    sustain="pedal" if self.pedal_blocks.get() else "keys",
                    particles=self.sparks.get(), hands=self.hands.get(),
                    fps=60 if self.smooth.get() else 30)

        def work():
            try:
                from . import render, synth

                if not is_midi:
                    self.events.put(("status", "Listening for the notes…"))
                midi = self._midi(path, on_progress=lambda f: self.events.put(("progress", f * 0.3)))
                audio = None
                if sound == "mine" and own:
                    audio = own
                elif sound == "piano":
                    self.events.put(("status", "Making the piano sound…"))
                    audio = synth.synth(midi, media.temp_path(".wav"))
                base = 0.0 if is_midi else 0.3
                self.events.put(("status", "Drawing every frame…"))
                w, h = render.FORMATS[fmt]
                render.render(midi, out, width=w, height=h, audio=audio, bar_lines=is_midi,
                              cancel=self.cancel,
                              on_progress=lambda f: self.events.put(("progress", base + f * (1 - base))),
                              **opts)
                self.events.put(("done", out))
            except media.NotefallError as exc:
                self.events.put(("failed", str(exc)))
            except Exception:
                self.events.put(("failed", "Something went wrong.\n\n" + traceback.format_exc()[-1200:]))

        threading.Thread(target=work, daemon=True).start()

    # updates -------------------------------------------------------------

    def _check_update(self, manual=False):
        from . import update

        if manual:
            self.update_pill.set("Checking…", clickable=False)

        def work():
            try:
                self.events.put(("update", update.check(manual=manual)))
            except Exception as e:
                self.events.put(("update_check_failed", str(e)))
            else:
                if manual:
                    self.events.put(("update_checked", None))

        threading.Thread(target=work, daemon=True).start()

    def _pill_reset(self):
        if not self.update_info and not self._updating:
            self.update_pill.set("Check for updates")

    def _update_click(self):
        from . import update

        info = self.update_info
        if self.busy or self._updating:
            return
        if not info:
            if self.update_pill.clickable:
                self._check_update(manual=True)
            return
        if not (info["setup"] and update.installed_with_setup()):
            import webbrowser

            webbrowser.open(info["page"])
            return
        if not messagebox.askyesno("NoteFall", "NoteFall %s is out. Update now?\n\n"
                                   "It downloads, installs and reopens by itself." % info["version"]):
            return
        self._updating = True
        self.update_pill.set("Downloading…", solid=True, clickable=False)

        def work():
            try:
                path = update.download(info["setup"], lambda f: self.events.put(("update_progress", f)))
                self.events.put(("update_ready", path))
            except Exception as e:
                self.events.put(("update_failed", str(e)))

        threading.Thread(target=work, daemon=True).start()

    def _on_update_event(self, kind, value):
        if kind == "update" and value:
            self.update_info = value
            self.update_pill.set("Update to %s" % value["version"], solid=True)
        elif kind == "update_checked":
            if not self.update_info:
                self.update_pill.set("You're up to date ✓", clickable=False)
                self.root.after(4000, self._pill_reset)
        elif kind == "update_check_failed":
            self.update_pill.set("Couldn't check, try again later", clickable=False)
            self.root.after(4000, self._pill_reset)
        elif kind == "update_progress":
            self.update_pill.set("Downloading %d%%" % int(value * 100), solid=True, clickable=False)
        elif kind == "update_ready":
            from . import update

            self.update_pill.set("Installing…", solid=True, clickable=False)
            try:
                update.run_installer(value)
            except Exception as e:
                self._on_update_event("update_failed", str(e))
                return
            self.root.destroy()
        elif kind == "update_failed":
            self._updating = False
            self.update_pill.set("Update failed, try again", solid=True)
            messagebox.showerror("NoteFall", "Couldn't update: %s\n\nYou can grab the new version "
                                 "from the download page." % value)

    def _set_busy_text(self, text):
        self._busy_text = text
        self.status.set(text)

    def _finish(self):
        self.busy = False
        self.go.set_progress(None)

    def _poll(self):
        try:
            while True:
                ev = self.events.get_nowait()
                kind = ev[0]
                if kind.startswith("update"):
                    self._on_update_event(kind, ev[1])
                elif kind == "preview" and ev[1] == self.preview_token:
                    self._start_player(ev[2], ev[3])
                elif kind == "preview_error" and ev[1] == self.preview_token:
                    self._stage_message("Can't preview this file", ev[2][:160])
                elif kind == "listen" and ev[1] == self.preview_token:
                    self._stage_message("Listening… %d%%" % int(ev[2] * 100),
                                        "Finding every note in your recording.",
                                        progress=ev[2], ring=True)
                elif kind == "stage":
                    if ev[1]:
                        self._stage_message(ev[1], ev[2], ring=True)
                elif kind == "heard":
                    self._midi_row_update()
                elif kind == "status":
                    self._set_busy_text(ev[1])
                elif kind == "progress":
                    if self.busy:
                        self.go.set_progress(ev[1], "%d%%" % int(ev[1] * 100))
                elif kind == "done":
                    self._finish()
                    self.result = ev[1]
                    name = os.path.basename(ev[1])
                    self.status.set("Saved " + (name if len(name) < 22 else name[:19] + "…"))
                    self.after_row.pack(side="right")
                    self.go.flash("Done ✓", P["green"])
                elif kind == "failed":
                    self._finish()
                    if ev[1] == "cancelled":
                        self.status.set("Stopped. Nothing was saved.")
                    else:
                        self.status.set(ev[1].splitlines()[0][:60])
                        messagebox.showerror("NoteFall", ev[1])
        except queue.Empty:
            pass
        except tk.TclError:
            pass
        self.root.after(80, self._poll)


def main():
    multiprocessing.freeze_support()
    if sys.platform.startswith("win"):
        try:
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass
    root = tk.Tk()
    App(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
