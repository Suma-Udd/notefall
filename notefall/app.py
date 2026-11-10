"""The NoteFall app.

A small, calm window: a live preview on the left, a handful of choices on
the right, one button. Built on tkinter so it ships with Python, with the
rounded bits drawn by Pillow so they stay smooth on every OS.
"""

import multiprocessing
import os
import queue
import subprocess
import sys
import threading
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
FORMAT_HINT = {"phone": "1080 × 1920 · TikTok, Reels",
               "youtube": "1920 × 1080 · YouTube",
               "square": "1080 × 1080 · Instagram"}
ASPECT = {"phone": (9, 16), "youtube": (16, 9), "square": (1, 1)}
SOUNDS = [("piano", "Piano"), ("mine", "Recording"), ("none", "None")]

# colours, roughly macOS light appearance
BG = "#F5F5F7"
CARD = "#FFFFFF"
TEXT = "#1D1D1F"
SUB = "#6E6E73"
FAINT = "#AEAEB2"
LINE = "#E5E5EA"
FIELD = "#F2F2F7"
TRACK = "#E8E8ED"
ACCENT = "#0071E3"
ACCENT_HOVER = "#0077ED"
ACCENT_DOWN = "#006EDB"
GREEN = "#34C759"

PREVIEW_FRAMES = 40
PREVIEW_FPS = 20


def _rgb(hex_colour):
    h = hex_colour.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


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


# drawing helpers -------------------------------------------------------------

SS = 3  # supersampling for smooth edges


def rounded(w, h, r, fill, outline=None, width=1, shadow=0, bg=None):
    """A smooth rounded rectangle as an RGBA image, optionally with a soft shadow."""
    pad = shadow * 2
    W, H = (w + 2 * pad) * SS, (h + 2 * pad) * SS
    img = Image.new("RGBA", (W, H), (_rgb(bg) + (255,)) if bg else (0, 0, 0, 0))
    if shadow:
        sh = Image.new("L", (W, H), 0)
        ImageDraw.Draw(sh).rounded_rectangle(
            [pad * SS, (pad + shadow * 0.35) * SS, (pad + w) * SS, (pad + h + shadow * 0.35) * SS],
            radius=r * SS, fill=38)
        sh = sh.filter(ImageFilter.GaussianBlur(shadow * SS * 0.6))
        img.alpha_composite(Image.merge("RGBA", (Image.new("L", (W, H), 0),) * 3 + (sh,)))
    shape = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(shape).rounded_rectangle(
        [pad * SS, pad * SS, (pad + w) * SS - 1, (pad + h) * SS - 1], radius=r * SS,
        fill=_rgb(fill) + (255,) if fill else None,
        outline=(_rgb(outline) + (255,)) if outline else None, width=width * SS)
    img.alpha_composite(shape)
    return img.resize((w + 2 * pad, h + 2 * pad), Image.LANCZOS)


class Canvas(tk.Canvas):
    def __init__(self, parent, width, height, bg=CARD, **kw):
        super().__init__(parent, width=width, height=height, bg=bg, highlightthickness=0,
                         bd=0, **kw)
        self._imgs = {}

    def keep(self, key, pil):
        self._imgs[key] = ImageTk.PhotoImage(pil)
        return self._imgs[key]


class Button(Canvas):
    """A pill button. kind: primary (blue) or secondary (grey)."""

    def __init__(self, parent, text, command, width=300, height=44, kind="primary",
                 font=None, bg=CARD):
        super().__init__(parent, width, height, bg=bg, cursor="hand2")
        self.command, self.kind, self.enabled = command, kind, True
        self.w, self.h = width, height
        r = 11
        if kind == "primary":
            looks = {"normal": ACCENT, "hover": ACCENT_HOVER, "down": ACCENT_DOWN,
                     "disabled": "#A9CBF5"}
            self.fg = {"normal": "#FFFFFF", "disabled": "#FFFFFF"}
        else:
            looks = {"normal": TRACK, "hover": "#DEDEE3", "down": "#D5D5DA", "disabled": TRACK}
            self.fg = {"normal": TEXT, "disabled": FAINT}
        self.looks = {k: self.keep(k, rounded(width, height, r, c, bg=bg)) for k, c in looks.items()}
        self.bgimg = self.create_image(0, 0, anchor="nw", image=self.looks["normal"])
        self.label = self.create_text(width / 2, height / 2, text=text, font=font,
                                      fill=self.fg["normal"])
        self.bind("<Enter>", lambda e: self._show("hover"))
        self.bind("<Leave>", lambda e: self._show("normal"))
        self.bind("<ButtonPress-1>", lambda e: self._show("down"))
        self.bind("<ButtonRelease-1>", self._release)

    def _show(self, state):
        if getattr(self, "_pill", None):
            return
        if not self.enabled:
            state = "disabled"
        self.itemconfigure(self.bgimg, image=self.looks[state])
        self.itemconfigure(self.label, fill=self.fg.get(state, self.fg["normal"]))

    def _release(self, e):
        inside = 0 <= e.x <= self.w and 0 <= e.y <= self.h
        self._show("hover" if inside else "normal")
        if inside and self.enabled and self.command:
            self.command()

    def set_text(self, text):
        self.itemconfigure(self.label, text=text)

    def set_progress(self, frac, text=""):
        """Turn the button into a progress pill (frac 0..1), or back with None."""
        if frac is None:
            self._pill = None
            self.itemconfigure(self.label, state="normal")
            self._show("normal")
            return
        key = (int(frac * self.w), text)
        if getattr(self, "_pill", None) == key:
            return
        self._pill = key
        from .render import UI_FONT, load_font

        S = 3
        w, h = self.w * S, self.h * S
        font = load_font(15 * S, UI_FONT)

        def layer(back, fore):
            im = Image.new("RGBA", (w, h), _rgb(back) + (255,))
            ImageDraw.Draw(im).text((w / 2, h / 2), text, font=font, fill=_rgb(fore), anchor="mm")
            return im

        base, top = layer("#E3EEFC", ACCENT), layer(ACCENT, "#FFFFFF")
        cut = Image.new("L", (w, h), 0)
        ImageDraw.Draw(cut).rectangle([0, 0, int(w * frac), h], fill=255)
        base.paste(top, (0, 0), cut)
        shape = Image.new("L", (w, h), 0)
        ImageDraw.Draw(shape).rounded_rectangle([0, 0, w - 1, h - 1], radius=11 * S, fill=255)
        out = Image.new("RGBA", (w, h), _rgb(self["bg"]) + (255,))
        out.paste(base, (0, 0), shape)
        out = out.resize((self.w, self.h), Image.LANCZOS)
        self.itemconfigure(self.bgimg, image=self.keep("pill", out))
        self.itemconfigure(self.label, state="hidden")

    def set_enabled(self, on):
        self.enabled = on
        self.configure(cursor="hand2" if on else "arrow")
        self._show("normal")


class Segmented(Canvas):
    """macOS style segmented control bound to a StringVar."""

    def __init__(self, parent, options, variable, width=300, height=32, font=None, bg=CARD,
                 on_click=None):
        super().__init__(parent, width, height, bg=bg, cursor="hand2")
        self.options, self.var, self.on_click = options, variable, on_click
        self.w, self.h = width, height
        n = len(options)
        self.seg = (width - 4) / n
        self.create_image(0, 0, anchor="nw", image=self.keep("track", rounded(width, height, 9, TRACK, bg=bg)))
        kw, kh = int(self.seg), height - 4
        knob = rounded(kw, kh, 7, CARD, shadow=3)
        self.pad = 6
        self.knob = self.create_image(0, 0, anchor="nw", image=self.keep("knob", knob))
        self.labels = []
        for i, (_, label) in enumerate(options):
            self.labels.append(self.create_text(2 + self.seg * (i + 0.5), height / 2, text=label,
                                                font=font, fill=TEXT))
        self.x = self._target()
        self._place()
        self.bind("<ButtonRelease-1>", self._click)
        variable.trace_add("write", lambda *_: self._animate())

    def _index(self):
        keys = [k for k, _ in self.options]
        return keys.index(self.var.get()) if self.var.get() in keys else 0

    def _target(self):
        return 2 + self.seg * self._index()

    def _place(self):
        self.coords(self.knob, self.x - self.pad, 2 - self.pad)
        for i, item in enumerate(self.labels):
            self.itemconfigure(item, fill=TEXT if i == self._index() else SUB)

    def _animate(self):
        target = self._target()
        step = (target - self.x) * 0.45
        if abs(step) < 0.5:
            self.x = target
            self._place()
            return
        self.x += step
        self._place()
        self.after(12, self._animate)

    def _click(self, e):
        i = int(min(len(self.options) - 1, max(0, (e.x - 2) // self.seg)))
        key = self.options[i][0]
        if self.on_click and self.on_click(key) is False:
            return
        self.var.set(key)


class Toggle(Canvas):
    """An iOS style switch bound to a BooleanVar."""

    W, H = 42, 25

    def __init__(self, parent, variable, bg=CARD):
        super().__init__(parent, self.W, self.H, bg=bg, cursor="hand2")
        self.var = variable
        self.on_img = self.keep("on", rounded(self.W, self.H, self.H // 2, GREEN, bg=bg))
        self.off_img = self.keep("off", rounded(self.W, self.H, self.H // 2, TRACK, bg=bg))
        self.track = self.create_image(0, 0, anchor="nw")
        k = self.H - 4
        self.knob = self.create_image(0, 0, anchor="nw",
                                      image=self.keep("knob", rounded(k, k, k // 2, CARD, shadow=2)))
        self.x = self._target()
        self._place()
        self.bind("<ButtonRelease-1>", lambda e: self.var.set(not self.var.get()))
        variable.trace_add("write", lambda *_: self._animate())

    def _target(self):
        return self.W - self.H + 2 if self.var.get() else 2

    def _place(self):
        self.itemconfigure(self.track, image=self.on_img if self.var.get() else self.off_img)
        self.coords(self.knob, self.x - 4, 2 - 4)

    def _animate(self):
        target = self._target()
        step = (target - self.x) * 0.5
        if abs(step) < 0.5:
            self.x = target
            self._place()
            return
        self.x += step
        self._place()
        self.after(12, self._animate)


class Swatches(Canvas):
    """One dot per theme: left hand colour on the left half, right hand on the right."""

    D, GAP = 28, 14

    def __init__(self, parent, variable, bg=CARD):
        keys = list(theme.THEMES)
        width = len(keys) * self.D + (len(keys) - 1) * self.GAP + 8
        super().__init__(parent, width, self.D + 8, bg=bg, cursor="hand2")
        self.keys, self.var = keys, variable
        self.rings = {}
        for i, key in enumerate(keys):
            pal = theme.get(key)
            x = 4 + i * (self.D + self.GAP)
            self.create_image(x, 4, anchor="nw", image=self.keep(key, self._dot(pal, bg)))
            self.rings[key] = self.create_image(x - 4, 0, anchor="nw")
        self.ring = self.keep("ring", self._ring(bg))
        self._place()
        self.bind("<ButtonRelease-1>", self._click)
        variable.trace_add("write", lambda *_: self._place())

    def _dot(self, pal, bg):
        d = self.D * SS
        img = Image.new("RGBA", (d, d), _rgb(bg) + (255,))
        dr = ImageDraw.Draw(img)
        dr.pieslice([0, 0, d - 1, d - 1], 90, 270, fill=pal["left"])
        dr.pieslice([0, 0, d - 1, d - 1], 270, 90, fill=pal["right"])
        return img.resize((self.D, self.D), Image.LANCZOS)

    def _ring(self, bg):
        d = (self.D + 8) * SS
        img = Image.new("RGBA", (d, d), (0, 0, 0, 0))
        ImageDraw.Draw(img).ellipse([SS, SS, d - SS - 1, d - SS - 1], outline=_rgb(ACCENT) + (255,),
                                    width=int(2.2 * SS))
        return img.resize((self.D + 8, self.D + 8), Image.LANCZOS)

    def _place(self):
        for key, item in self.rings.items():
            self.itemconfigure(item, image=self.ring if key == self.var.get() else "")

    def _click(self, e):
        i = int(max(0, min(len(self.keys) - 1, (e.x - 4) // (self.D + self.GAP))))
        self.var.set(self.keys[i])


class Field(tk.Frame):
    """A rounded, borderless text field with a placeholder."""

    def __init__(self, parent, variable, placeholder, width=300, height=36, font=None, bg=CARD):
        super().__init__(parent, bg=bg)
        self.canvas = Canvas(self, width, height, bg=bg)
        self.canvas.pack()
        self.canvas.create_image(0, 0, anchor="nw",
                                 image=self.canvas.keep("bg", rounded(width, height, 9, FIELD, bg=bg)))
        self.entry = tk.Entry(self.canvas, textvariable=variable, font=font, bd=0, relief="flat",
                              bg=FIELD, fg=TEXT, insertbackground=TEXT, highlightthickness=0)
        self.canvas.create_window(12, height / 2, anchor="w", window=self.entry, width=width - 24)
        self.hint = self.canvas.create_text(13, height / 2, anchor="w", text=placeholder, font=font,
                                            fill=FAINT)
        self.var = variable
        variable.trace_add("write", lambda *_: self._hint())
        self.entry.bind("<FocusIn>", lambda e: self._hint())
        self.entry.bind("<FocusOut>", lambda e: self._hint())
        self.canvas.bind("<Button-1>", lambda e: self.entry.focus_set())
        self._hint()

    def _hint(self):
        self.canvas.itemconfigure(self.hint, state="hidden" if self.var.get() else "normal")
        if not self.var.get():
            self.canvas.tag_lower(self.hint)
            self.canvas.tag_raise(self.hint)


# the window -----------------------------------------------------------------

class App:
    SIDEBAR = 344

    def __init__(self, root):
        self.root = root
        self.events = queue.Queue()
        self.cancel = threading.Event()
        self.busy = False
        self.midi_for_input = {}
        self.preview_job = None
        self.preview_token = 0
        self.frames = []
        self.frame_i = 0
        self.result = None

        self.input_path = tk.StringVar()
        self.title_text = tk.StringVar()
        self.fmt = tk.StringVar(value="phone")
        self.theme_key = tk.StringVar(value=theme.DEFAULT_THEME)
        self.sound = tk.StringVar(value="piano")
        self.own_audio = ""
        self.smooth = tk.BooleanVar(value=True)
        self.pedal_blocks = tk.BooleanVar(value=False)
        self.sparks = tk.BooleanVar(value=True)
        self.hands = tk.BooleanVar(value=True)
        self.status = tk.StringVar(value="")

        self._fonts()
        self._window()
        self._build()
        for var in (self.fmt, self.theme_key, self.pedal_blocks, self.sparks, self.hands,
                    self.title_text):
            var.trace_add("write", lambda *_: self.schedule_preview())
        self.root.after(80, self._poll)
        self.root.after(PREVIEW_FPS and int(1000 / PREVIEW_FPS), self._tick)
        self.update_info = None
        self.root.after(1500, self._check_update)

    # setup ---------------------------------------------------------------

    def _fonts(self):
        family = tkfont.nametofont("TkDefaultFont").actual()["family"]
        if sys.platform.startswith("win"):
            family = "Segoe UI"
        elif sys.platform.startswith("linux"):
            for cand in ("Inter", "Cantarell", "Ubuntu", "Noto Sans", "DejaVu Sans"):
                if cand in tkfont.families():
                    family = cand
                    break
        self.f_title = (family, 20, "bold")
        self.f_body = (family, 12)
        self.f_bold = (family, 12, "bold")
        self.f_small = (family, 10)
        self.f_button = (family, 13, "bold")
        self.f_big = (family, 17, "bold")

    def _window(self):
        r = self.root
        r.title("NoteFall")
        r.configure(bg=BG)
        r.geometry("1080x780")
        r.minsize(940, 740)
        try:
            from .icon import draw_icon

            self._icon = ImageTk.PhotoImage(draw_icon(128))
            r.iconphoto(True, self._icon)
        except Exception:
            pass

    def _label(self, parent, text, font=None, fg=TEXT, **kw):
        return tk.Label(parent, text=text, font=font or self.f_body, fg=fg, bg=CARD, **kw)

    def _section(self, parent, text, hint=""):
        row = tk.Frame(parent, bg=CARD)
        row.pack(fill="x", pady=(14, 6))
        self._label(row, text, self.f_bold).pack(side="left")
        right = self._label(row, hint, self.f_small, fg=FAINT)
        right.pack(side="right", pady=(2, 0))
        return right

    def _build(self):
        W = self.SIDEBAR - 48

        # sidebar card, drawn as a rounded white panel
        self.side_wrap = tk.Frame(self.root, bg=BG)
        self.side_wrap.pack(side="right", fill="y", padx=(0, 20), pady=20)
        self.side_bg = Canvas(self.side_wrap, self.SIDEBAR, 10, bg=BG)
        self.side_bg.place(x=0, y=0, relwidth=1, relheight=1)
        side = tk.Frame(self.side_wrap, bg=CARD)
        side.pack(fill="both", expand=True, padx=24, pady=22)
        self.side_wrap.bind("<Configure>", self._side_bg)
        self.side_wrap.configure(width=self.SIDEBAR)

        head = tk.Frame(side, bg=CARD)
        head.pack(fill="x")
        self._label(head, "NoteFall", self.f_title).pack(side="left")
        self._label(head, __version__, self.f_small, fg=FAINT).pack(side="left", padx=(8, 0), pady=(8, 0))
        # shown when a newer version is out
        self.update_link = self._label(head, "", self.f_small, fg=ACCENT, cursor="hand2")
        self.update_link.bind("<Button-1>", lambda e: self._update_click())
        self._label(side, "Piano music in. Falling notes out.", self.f_body, fg=SUB).pack(anchor="w")

        # song
        self._section(side, "Song")
        row = tk.Frame(side, bg=CARD)
        row.pack(fill="x")
        self.song_label = self._label(row, "None chosen", fg=SUB, anchor="w")
        self.song_label.pack(side="left", fill="x", expand=True)
        self.change = self._label(row, "Choose…", fg=ACCENT, cursor="hand2")
        self.change.pack(side="right")
        self.change.bind("<Button-1>", lambda e: self.pick_input())
        self.song_hint = self._label(side, "MIDI, or any recording: mp3, wav, m4a, mp4…",
                                     self.f_small, fg=FAINT, anchor="w")
        self.song_hint.pack(fill="x", pady=(2, 0))

        # format
        self.fmt_hint = self._section(side, "Format", FORMAT_HINT["phone"])
        Segmented(side, FORMATS, self.fmt, width=W, font=self.f_body).pack(anchor="w")
        self.fmt.trace_add("write", lambda *_: self.fmt_hint.configure(text=FORMAT_HINT[self.fmt.get()]))

        # look
        self.theme_hint = self._section(side, "Look", self._theme_name())
        Swatches(side, self.theme_key).pack(anchor="w")
        self.theme_key.trace_add("write", lambda *_: self.theme_hint.configure(text=self._theme_name()))

        self._section(side, "Title")
        Field(side, self.title_text, "Shown in the corner (optional)", width=W,
              font=self.f_body).pack(anchor="w")

        self._section(side, "Sound")
        Segmented(side, SOUNDS, self.sound, width=W, font=self.f_body,
                  on_click=self._sound_click).pack(anchor="w")
        self.sound_hint = self._label(side, "A piano sound made from your MIDI", self.f_small, fg=FAINT,
                                      anchor="w")
        self.sound_hint.pack(fill="x", pady=(5, 0))
        self.sound.trace_add("write", lambda *_: self._sound_hint())

        opts = tk.Frame(side, bg=CARD)
        opts.pack(fill="x", pady=(12, 0))
        for text, var in (("Smooth motion (60 fps)", self.smooth),
                          ("Notes ring with the pedal", self.pedal_blocks),
                          ("Sparks", self.sparks),
                          ("Hands on the keys (Paper look)", self.hands)):
            line = tk.Frame(opts, bg=CARD)
            line.pack(fill="x", pady=2)
            self._label(line, text).pack(side="left")
            Toggle(line, var).pack(side="right")

        # bottom: button, progress, status
        bottom = tk.Frame(side, bg=CARD)
        bottom.pack(side="bottom", fill="x", before=head)
        status_row = tk.Frame(bottom, bg=CARD, height=22)
        status_row.pack(fill="x", pady=(10, 6))
        status_row.pack_propagate(False)
        self.status_label = self._label(status_row, "", self.f_small, fg=SUB, textvariable=self.status,
                                        anchor="w")
        self.status_label.pack(side="left", fill="x", expand=True)
        self.after_row = tk.Frame(status_row, bg=CARD)
        for text, fn in (("Show in Folder", lambda: show_in_folder(self.result)),
                         ("Play", lambda: open_path(self.result))):
            link = self._label(self.after_row, text, self.f_small, fg=ACCENT, cursor="hand2")
            link.pack(side="right", padx=(12, 0))
            link.bind("<Button-1>", lambda e, fn=fn: fn())
        self.go = Button(bottom, "Create Video", self.start, width=W, font=self.f_button)
        self.go.pack()
        self.go.bind("<Enter>", lambda e: self.busy and self.status.set("Click to stop"), add="+")
        self.go.bind("<Leave>", lambda e: self.busy and self.status.set(self._busy_text), add="+")
        self._busy_text = ""

        # stage: the preview
        self.stage = Canvas(self.root, 600, 600, bg=BG)
        self.stage.pack(side="left", fill="both", expand=True, padx=20, pady=20)
        self.stage.bind("<Configure>", lambda e: self._stage_changed())
        self.stage.bind("<Button-1>", lambda e: (not self.input_path.get()) and self.pick_input())
        self.stage_img = self.stage.create_image(0, 0, anchor="center")
        self.stage_text = self.stage.create_text(0, 0, text="", font=self.f_big, fill=TEXT)
        self.stage_sub = self.stage.create_text(0, 0, text="", font=self.f_body, fill=SUB)
        self.go.set_enabled(False)

    def _side_bg(self, e):
        img = rounded(e.width, e.height, 16, CARD, bg=BG)
        self.side_bg.configure(width=e.width, height=e.height)
        self.side_bg.delete("all")
        self.side_bg.create_image(0, 0, anchor="nw", image=self.side_bg.keep("bg", img))

    # stage ----------------------------------------------------------------

    def _preview_box(self):
        cw, ch = max(200, self.stage.winfo_width()), max(200, self.stage.winfo_height())
        aw, ah = ASPECT[self.fmt.get()]
        scale = min((cw - 40) / aw, (ch - 40) / ah)
        return int(aw * scale) // 2 * 2, int(ah * scale) // 2 * 2

    def _stage_changed(self):
        cw, ch = self.stage.winfo_width(), self.stage.winfo_height()
        self.stage.coords(self.stage_img, cw / 2, ch / 2)
        self.stage.coords(self.stage_text, cw / 2, ch / 2 + 74)
        self.stage.coords(self.stage_sub, cw / 2, ch / 2 + 104)
        if not self.input_path.get():
            self._empty_stage()
        else:
            self.schedule_preview()

    def _empty_stage(self):
        cw, ch = max(200, self.stage.winfo_width()), max(200, self.stage.winfo_height())
        w, h = min(440, cw - 60), min(340, ch - 60)
        img = rounded(w, h, 22, CARD, shadow=12, bg=BG)
        try:
            from .icon import draw_icon

            icon = draw_icon(240).resize((84, 84), Image.LANCZOS)
            img.alpha_composite(icon, ((img.width - 84) // 2, img.height // 2 - 86))
        except Exception:
            pass
        self.frames = []
        self.stage.itemconfigure(self.stage_img, image=self.stage.keep("empty", img))
        self.stage.itemconfigure(self.stage_text, text="Choose a song")
        self.stage.itemconfigure(self.stage_sub, text="Click here, or use Choose… on the right")
        self.stage.coords(self.stage_text, cw / 2, ch / 2 + 22)
        self.stage.coords(self.stage_sub, cw / 2, ch / 2 + 52)
        self.stage.configure(cursor="hand2")

    def _show_frames(self, frames):
        """Rounded corners and a soft shadow around each preview frame."""
        if not frames:
            return
        w, h = frames[0].size
        r = max(10, min(w, h) // 22)
        mask = Image.new("L", (w * SS, h * SS), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, w * SS - 1, h * SS - 1], radius=r * SS, fill=255)
        mask = mask.resize((w, h), Image.LANCZOS)
        base = rounded(w, h, r, "#000000", shadow=14, bg=BG)
        pad = (base.width - w) // 2
        out = []
        for f in frames:
            img = base.copy()
            img.paste(f, (pad, pad), mask)
            out.append(ImageTk.PhotoImage(img))
        self.frames = out
        self.frame_i = 0
        self.stage.configure(cursor="")
        self.stage.itemconfigure(self.stage_text, text="")
        self.stage.itemconfigure(self.stage_sub, text="")

    def _tick(self):
        if self.frames:
            self.frame_i = (self.frame_i + 1) % len(self.frames)
            self.stage.itemconfigure(self.stage_img, image=self.frames[self.frame_i])
        self.root.after(int(1000 / PREVIEW_FPS), self._tick)

    def schedule_preview(self):
        if self.preview_job:
            self.root.after_cancel(self.preview_job)
        self.preview_job = self.root.after(220, self._preview)

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
                midi = self._midi(path, preview=True)
                from .render import preview_frames

                frames = preview_frames(midi, count=PREVIEW_FRAMES, fps=PREVIEW_FPS, **opts)
                self.events.put(("preview", token, frames))
            except Exception as exc:
                self.events.put(("preview_error", token, str(exc)))

        threading.Thread(target=work, daemon=True).start()

    # choices --------------------------------------------------------------

    def _theme_name(self):
        return theme.THEMES[self.theme_key.get()]["label"].split(" (")[0]

    def _is_midi(self, path=None):
        return os.path.splitext(path or self.input_path.get())[1].lower() in MIDI_EXT

    def _sound_hint(self):
        s = self.sound.get()
        if s == "piano":
            text = "A piano sound made from your MIDI"
        elif s == "mine":
            text = "Using " + os.path.basename(self.own_audio) if self.own_audio else "Your own recording"
        else:
            text = "A silent video"
        self.sound_hint.configure(text=text)

    def _sound_click(self, key):
        if key == "piano" and self.input_path.get() and not self._is_midi():
            self.status.set("Recordings keep their own sound, so there's no piano to add.")
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
        if not path:
            return
        self.input_path.set(path)
        name = os.path.basename(path)
        self.song_label.configure(text=name if len(name) < 34 else name[:31] + "…", fg=TEXT)
        self.change.configure(text="Change")
        self.result = None
        self.after_row.pack_forget()
        stem = os.path.splitext(name)[0].replace("_", " ").replace("-", " ").strip()
        self.title_text.set(stem[:1].upper() + stem[1:])
        if self._is_midi(path):
            self.song_hint.configure(text="MIDI file · notes will be exact")
            if self.own_audio and not self._is_midi(self.own_audio) and self.sound.get() == "mine" \
                    and self.own_audio == getattr(self, "_last_recording", None):
                self.own_audio = ""
                self.sound.set("piano")
        else:
            self.song_hint.configure(text="Recording · NoteFall will listen for the notes")
            self.own_audio = path
            self._last_recording = path
            if self.sound.get() == "piano":
                self.sound.set("mine")
        self._sound_hint()
        self.status.set("")
        self.go.set_enabled(True)
        self.schedule_preview()

    def _midi(self, path, preview=False, on_progress=None):
        if self._is_midi(path):
            return path
        if path in self.midi_for_input:
            return self.midi_for_input[path]
        if preview:
            self.events.put(("stage", "Listening…", "Finding the notes in your recording"))
        from .transcribe import transcribe

        midi = transcribe(path, on_progress=on_progress)
        self.midi_for_input[path] = midi
        return midi

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
                midi = self._midi(path, on_progress=lambda f: self.events.put(("progress", f * 0.25)))
                audio = None
                if sound == "mine" and own:
                    audio = own
                elif sound == "piano" and is_midi:
                    self.events.put(("status", "Making the piano sound…"))
                    audio = synth.synth(midi, media.temp_path(".wav"))
                base = 0.0 if is_midi else 0.25
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

    def _check_update(self):
        from . import update

        threading.Thread(target=lambda: self.events.put(("update", update.check())),
                         daemon=True).start()

    def _update_click(self):
        from . import update

        info = self.update_info
        if not info or self.busy:
            return
        if not (info["setup"] and update.installed_with_setup()):
            import webbrowser

            webbrowser.open(info["page"])
            return
        if not messagebox.askyesno("NoteFall", "NoteFall %s is out. Update now?\n\n"
                                   "It downloads, installs and reopens by itself." % info["version"]):
            return
        self.update_link.configure(text="Downloading…", cursor="")
        self.update_info = None

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
            self.update_link.configure(text="Update to %s" % value["version"])
            self.update_link.pack(side="right", pady=(8, 0))
        elif kind == "update_progress":
            self.update_link.configure(text="Downloading %d%%" % int(value * 100))
        elif kind == "update_ready":
            from . import update

            try:
                update.run_installer(value)
            except Exception as e:
                self._on_update_event("update_failed", str(e))
                return
            self.root.destroy()
        elif kind == "update_failed":
            self.update_link.configure(text="Update failed", cursor="")
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
                    self._show_frames(ev[2])
                elif kind == "preview_error" and ev[1] == self.preview_token:
                    self.frames = []
                    self.stage.itemconfigure(self.stage_img, image="")
                    self.stage.itemconfigure(self.stage_text, text="Can't preview this file")
                    self.stage.itemconfigure(self.stage_sub, text=ev[2][:120])
                    cw, ch = self.stage.winfo_width(), self.stage.winfo_height()
                    self.stage.coords(self.stage_text, cw / 2, ch / 2)
                    self.stage.coords(self.stage_sub, cw / 2, ch / 2 + 30)
                elif kind == "stage":
                    self.frames = []
                    self.stage.itemconfigure(self.stage_img, image="")
                    self.stage.itemconfigure(self.stage_text, text=ev[1])
                    self.stage.itemconfigure(self.stage_sub, text=ev[2])
                    cw, ch = self.stage.winfo_width(), self.stage.winfo_height()
                    self.stage.coords(self.stage_text, cw / 2, ch / 2)
                    self.stage.coords(self.stage_sub, cw / 2, ch / 2 + 30)
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
                elif kind == "failed":
                    self._finish()
                    if ev[1] == "cancelled":
                        self.status.set("Stopped. Nothing was saved.")
                    else:
                        self.status.set(ev[1].splitlines()[0])
                        messagebox.showerror("NoteFall", ev[1])
        except queue.Empty:
            pass
        self.root.after(80, self._poll)


def main():
    multiprocessing.freeze_support()
    if sys.platform.startswith("win"):
        try:
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    root = tk.Tk()
    App(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
