"""The NoteFall app window.

Pick a song, pick a look, press the big button. Built on tkinter so it
ships with Python and needs nothing else.
"""

import multiprocessing
import os
import queue
import subprocess
import sys
import threading
import traceback

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import __version__, media, theme

MIDI_EXT = (".mid", ".midi", ".kar", ".smf")
MEDIA_EXT = (".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma",
             ".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v")

FORMATS = [
    ("phone", "Phone", "TikTok, Reels, Shorts"),
    ("youtube", "YouTube", "wide screen"),
    ("square", "Square", "Instagram feed"),
]
PREVIEW = {"phone": (216, 384), "youtube": (384, 216), "square": (300, 300)}

BG = "#0d1120"
PANEL = "#151a2e"
FG = "#eef1f8"
MUTED = "#9aa3bd"
ACCENT = "#48dea0"
ACCENT_DARK = "#2fb37f"


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


class App:
    def __init__(self, root):
        self.root = root
        self.events = queue.Queue()
        self.cancel = threading.Event()
        self.busy = False
        self.midi_for_input = {}  # recording path -> transcribed midi
        self.preview_job = None
        self.preview_token = 0
        self.result = None

        self.input_path = tk.StringVar()
        self.input_info = tk.StringVar(value="MIDI files, or a recording (mp3, wav, mp4, ...)")
        self.title_text = tk.StringVar()
        self.fmt = tk.StringVar(value="phone")
        self.theme_label = tk.StringVar(value=theme.THEMES[theme.DEFAULT_THEME]["label"])
        self.sound = tk.StringVar(value="piano")
        self.own_audio = tk.StringVar()
        self.pedal_blocks = tk.BooleanVar(value=False)
        self.sparks = tk.BooleanVar(value=True)
        self.out_path = tk.StringVar()
        self.status = tk.StringVar(value="Pick a song to start.")

        self._style()
        self._build()
        for var in (self.fmt, self.theme_label, self.pedal_blocks, self.title_text):
            var.trace_add("write", lambda *_: self.schedule_preview())
        self.root.after(100, self._poll)

    # look ------------------------------------------------------------------

    def _style(self):
        r = self.root
        r.title("NoteFall")
        r.configure(bg=BG)
        r.minsize(760, 560)
        st = ttk.Style(r)
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass
        base = ("Segoe UI", 10) if sys.platform.startswith("win") else ("Helvetica", 11)
        self.font = base
        st.configure(".", background=BG, foreground=FG, fieldbackground=PANEL, font=base)
        st.configure("TFrame", background=BG)
        st.configure("Panel.TFrame", background=PANEL)
        st.configure("TLabel", background=BG, foreground=FG)
        st.configure("Panel.TLabel", background=PANEL, foreground=FG)
        st.configure("Muted.TLabel", background=PANEL, foreground=MUTED)
        st.configure("Head.TLabel", background=PANEL, foreground=FG,
                     font=(base[0], base[1] + 1, "bold"))
        st.configure("Title.TLabel", background=BG, foreground=FG, font=(base[0], 22, "bold"))
        st.configure("Sub.TLabel", background=BG, foreground=MUTED)
        st.configure("TRadiobutton", background=PANEL, foreground=FG)
        st.map("TRadiobutton", background=[("active", PANEL)], indicatorcolor=[("selected", ACCENT)])
        st.configure("TCheckbutton", background=PANEL, foreground=FG)
        st.map("TCheckbutton", background=[("active", PANEL)], indicatorcolor=[("selected", ACCENT)])
        st.configure("TButton", background="#262d48", foreground=FG, borderwidth=0, padding=(12, 6))
        st.map("TButton", background=[("active", "#323a5c"), ("disabled", "#1b2036")],
               foreground=[("disabled", MUTED)])
        st.configure("Big.TButton", background=ACCENT, foreground="#08130e",
                     font=(base[0], base[1] + 3, "bold"), padding=(18, 12))
        st.map("Big.TButton", background=[("active", ACCENT_DARK), ("disabled", "#2a3a34")],
               foreground=[("disabled", "#6c7a74")])
        st.configure("TEntry", fieldbackground="#0f1426", foreground=FG, insertcolor=FG,
                     bordercolor="#2a3150", padding=6)
        st.configure("TCombobox", fieldbackground="#0f1426", foreground=FG, background="#262d48",
                     arrowcolor=FG, padding=4)
        st.map("TCombobox", fieldbackground=[("readonly", "#0f1426")],
               foreground=[("readonly", FG)])
        r.option_add("*TCombobox*Listbox.background", "#0f1426")
        r.option_add("*TCombobox*Listbox.foreground", FG)
        st.configure("Horizontal.TProgressbar", background=ACCENT, troughcolor="#0f1426",
                     bordercolor=PANEL, lightcolor=ACCENT, darkcolor=ACCENT)
        try:
            from PIL import ImageTk

            from .icon import draw_icon

            self._icon = ImageTk.PhotoImage(draw_icon(128))
            r.iconphoto(True, self._icon)
        except Exception:
            pass

    def _section(self, parent, text):
        ttk.Label(parent, text=text, style="Head.TLabel").pack(anchor="w", pady=(14, 4))

    def _build(self):
        outer = ttk.Frame(self.root, padding=18)
        outer.pack(fill="both", expand=True)

        head = ttk.Frame(outer)
        head.pack(fill="x")
        ttk.Label(head, text="NoteFall", style="Title.TLabel").pack(side="left")
        ttk.Label(head, text="   piano music in, falling notes video out",
                  style="Sub.TLabel").pack(side="left", pady=(10, 0))

        body = ttk.Frame(outer)
        body.pack(fill="both", expand=True, pady=(14, 0))

        left = ttk.Frame(body, style="Panel.TFrame", padding=(18, 6, 18, 18))
        left.pack(side="left", fill="both", expand=True)
        right = ttk.Frame(body, style="Panel.TFrame", padding=14)
        right.pack(side="left", fill="y", padx=(14, 0))

        # 1. song
        self._section(left, "1.  Your song")
        row = ttk.Frame(left, style="Panel.TFrame")
        row.pack(fill="x")
        ttk.Button(row, text="Choose a file...", command=self.pick_input).pack(side="left")
        self.input_label = ttk.Label(row, text="nothing picked yet", style="Muted.TLabel")
        self.input_label.pack(side="left", padx=10)
        ttk.Label(left, textvariable=self.input_info, style="Muted.TLabel",
                  wraplength=380).pack(anchor="w", pady=(4, 0))

        # 2. look
        self._section(left, "2.  How it looks")
        fr = ttk.Frame(left, style="Panel.TFrame")
        fr.pack(fill="x")
        for key, name, hint in FORMATS:
            ttk.Radiobutton(fr, text="%s  (%s)" % (name, hint), value=key,
                            variable=self.fmt).pack(anchor="w")
        crow = ttk.Frame(left, style="Panel.TFrame")
        crow.pack(fill="x", pady=(8, 0))
        ttk.Label(crow, text="Colours", style="Panel.TLabel").pack(side="left")
        ttk.Combobox(crow, textvariable=self.theme_label, state="readonly", width=28,
                     values=[t["label"] for t in theme.THEMES.values()]).pack(side="left", padx=10)
        trow = ttk.Frame(left, style="Panel.TFrame")
        trow.pack(fill="x", pady=(8, 0))
        ttk.Label(trow, text="Title", style="Panel.TLabel").pack(side="left")
        ttk.Entry(trow, textvariable=self.title_text, width=34).pack(side="left", padx=(28, 0))
        ttk.Checkbutton(left, text="Make blocks last as long as the sustain pedal",
                        variable=self.pedal_blocks).pack(anchor="w", pady=(8, 0))
        ttk.Checkbutton(left, text="Little sparks when notes land",
                        variable=self.sparks).pack(anchor="w")

        # 3. sound
        self._section(left, "3.  Sound")
        self.sound_frame = ttk.Frame(left, style="Panel.TFrame")
        self.sound_frame.pack(fill="x")
        self.rb_piano = ttk.Radiobutton(self.sound_frame, text="Piano sound (made for you)",
                                        value="piano", variable=self.sound)
        self.rb_piano.pack(anchor="w")
        srow = ttk.Frame(self.sound_frame, style="Panel.TFrame")
        srow.pack(fill="x")
        ttk.Radiobutton(srow, text="My own recording", value="mine", variable=self.sound,
                        command=self._need_own_audio).pack(side="left")
        self.own_label = ttk.Label(srow, text="", style="Muted.TLabel")
        self.own_label.pack(side="left", padx=8)
        ttk.Radiobutton(self.sound_frame, text="No sound", value="none",
                        variable=self.sound).pack(anchor="w")

        # go
        go = ttk.Frame(left, style="Panel.TFrame")
        go.pack(fill="x", pady=(18, 0))
        self.go_btn = ttk.Button(go, text="Make my video", style="Big.TButton", command=self.start)
        self.go_btn.pack(side="left")
        self.cancel_btn = ttk.Button(go, text="Stop", command=self.stop)
        self.cancel_btn.pack(side="left", padx=10)
        self.cancel_btn.state(["disabled"])
        self.bar = ttk.Progressbar(left, mode="determinate", maximum=1.0)
        self.bar.pack(fill="x", pady=(14, 4))
        ttk.Label(left, textvariable=self.status, style="Muted.TLabel",
                  wraplength=400).pack(anchor="w")
        done = ttk.Frame(left, style="Panel.TFrame")
        done.pack(fill="x", pady=(8, 0))
        self.open_btn = ttk.Button(done, text="Play video", command=lambda: open_path(self.result))
        self.folder_btn = ttk.Button(done, text="Show in folder",
                                     command=lambda: show_in_folder(self.result))

        # preview
        ttk.Label(right, text="Preview", style="Head.TLabel").pack(anchor="w")
        self.preview = tk.Label(right, bg="#05070d", width=384, height=384, bd=0,
                                text="your video\nwill show here", fg=MUTED)
        self.preview.pack(pady=(6, 0))
        ttk.Label(right, text="v" + __version__, style="Muted.TLabel").pack(anchor="e", pady=(8, 0))

    # actions ---------------------------------------------------------------

    def _theme_key(self):
        for key, t in theme.THEMES.items():
            if t["label"] == self.theme_label.get():
                return key
        return theme.DEFAULT_THEME

    def _is_midi(self, path=None):
        return os.path.splitext(path or self.input_path.get())[1].lower() in MIDI_EXT

    def pick_input(self):
        path = filedialog.askopenfilename(
            title="Pick a MIDI file or a piano recording",
            filetypes=[("Songs", " ".join("*" + e for e in MIDI_EXT + MEDIA_EXT)),
                       ("MIDI", " ".join("*" + e for e in MIDI_EXT)),
                       ("Recordings", " ".join("*" + e for e in MEDIA_EXT)),
                       ("Everything", "*")])
        if not path:
            return
        self.input_path.set(path)
        self.input_label.configure(text=os.path.basename(path), style="Panel.TLabel")
        self.result = None
        self.open_btn.pack_forget()
        self.folder_btn.pack_forget()
        if not self.title_text.get():
            name = os.path.splitext(os.path.basename(path))[0].replace("_", " ").strip()
            self.title_text.set(name[:1].upper() + name[1:])
        if self._is_midi(path):
            self.input_info.set("MIDI file. The notes will be exact.")
            self.rb_piano.state(["!disabled"])
            if self.own_label.cget("text") == "(the file you picked)":
                self.own_audio.set("")
                self.own_label.configure(text="")
                self.sound.set("piano")
        else:
            self.input_info.set("Recording. NoteFall will listen to it and figure out the notes. "
                                "Works best on a clear solo piano.")
            self.rb_piano.state(["disabled"])
            if self.sound.get() == "piano":
                self.sound.set("mine")
                self.own_audio.set(path)
                self.own_label.configure(text="(the file you picked)")
        self.out_path.set(os.path.splitext(path)[0] + "-notefall.mp4")
        self.status.set("Ready. Press the green button when you like the preview.")
        self.schedule_preview()

    def _need_own_audio(self):
        if not self.own_audio.get():
            path = filedialog.askopenfilename(
                title="Pick the recording to use as sound",
                filetypes=[("Audio or video", " ".join("*" + e for e in MEDIA_EXT)),
                           ("Everything", "*")])
            if not path:
                self.sound.set("piano" if self._is_midi() else "none")
                return
            self.own_audio.set(path)
        self.own_label.configure(text=os.path.basename(self.own_audio.get()))

    def schedule_preview(self):
        if self.preview_job:
            self.root.after_cancel(self.preview_job)
        self.preview_job = self.root.after(250, self._preview)

    def _preview(self):
        self.preview_job = None
        path = self.input_path.get()
        if not path or self.busy:
            return
        self.preview_token += 1
        token = self.preview_token
        w, h = PREVIEW[self.fmt.get()]
        opts = dict(width=w, height=h, theme_name=self._theme_key(),
                    title=self.title_text.get() or None,
                    sustain="pedal" if self.pedal_blocks.get() else "keys")

        def work():
            try:
                midi = self._midi(path, preview=True)
                if midi is None:
                    return
                from .render import preview

                self.events.put(("preview", token, preview(midi, **opts)))
            except Exception as exc:
                self.events.put(("preview_error", token, str(exc)))

        threading.Thread(target=work, daemon=True).start()

    def _midi(self, path, preview=False, on_progress=None):
        """The MIDI for `path`, listening to it first if it's a recording."""
        if self._is_midi(path):
            return path
        if path in self.midi_for_input:
            return self.midi_for_input[path]
        if preview:
            self.events.put(("status", "Listening to your recording to find the notes..."))
        from .transcribe import transcribe

        midi = transcribe(path, on_progress=on_progress)
        self.midi_for_input[path] = midi
        if preview:
            self.events.put(("status", "Ready. Press the green button when you like the preview."))
        return midi

    def start(self):
        path = self.input_path.get()
        if not path:
            self.pick_input()
            if not self.input_path.get():
                return
            path = self.input_path.get()
        out = filedialog.asksaveasfilename(
            title="Save the video as", defaultextension=".mp4",
            initialdir=os.path.dirname(self.out_path.get()) or None,
            initialfile=os.path.basename(self.out_path.get()),
            filetypes=[("MP4 video", "*.mp4")])
        if not out:
            return
        self.out_path.set(out)
        self.busy = True
        self.cancel.clear()
        self.go_btn.state(["disabled"])
        self.cancel_btn.state(["!disabled"])
        self.open_btn.pack_forget()
        self.folder_btn.pack_forget()
        self.bar.configure(value=0)

        fmt = self.fmt.get()
        sound = self.sound.get()
        opts = dict(theme_name=self._theme_key(), title=self.title_text.get() or None,
                    sustain="pedal" if self.pedal_blocks.get() else "keys",
                    particles=self.sparks.get())
        own = self.own_audio.get()
        is_midi = self._is_midi(path)

        def work():
            try:
                from . import render, synth

                if not is_midi:
                    self.events.put(("status", "Listening to your recording to find the notes..."))
                midi = self._midi(path, on_progress=lambda f: self.events.put(("progress", f * 0.3)))
                audio = None
                if sound == "mine" and own:
                    audio = own
                elif sound == "piano" and is_midi:
                    self.events.put(("status", "Making the piano sound..."))
                    audio = synth.synth(midi, media.temp_path(".wav"))
                base = 0.0 if is_midi else 0.3
                self.events.put(("status", "Drawing your video. This takes about as long as "
                                           "the song, sometimes less."))
                w, h = render.FORMATS[fmt]
                render.render(midi, out, width=w, height=h, audio=audio,
                              bar_lines=is_midi, cancel=self.cancel,
                              on_progress=lambda f: self.events.put(("progress", base + f * (1 - base))),
                              **opts)
                self.events.put(("done", out))
            except media.NotefallError as exc:
                self.events.put(("failed", str(exc)))
            except Exception:
                self.events.put(("failed", "Something went wrong:\n" + traceback.format_exc()[-1200:]))

        threading.Thread(target=work, daemon=True).start()

    def stop(self):
        self.cancel.set()
        self.status.set("Stopping...")

    # events ----------------------------------------------------------------

    def _poll(self):
        try:
            while True:
                ev = self.events.get_nowait()
                kind = ev[0]
                if kind == "preview" and ev[1] == self.preview_token:
                    from PIL import ImageTk

                    self._preview_img = ImageTk.PhotoImage(ev[2])
                    self.preview.configure(image=self._preview_img, text="",
                                           width=ev[2].width, height=ev[2].height)
                elif kind == "preview_error" and ev[1] == self.preview_token:
                    self.preview.configure(image="", text="couldn't preview:\n" + ev[2][:200])
                    self.status.set(ev[2][:300])
                elif kind == "status":
                    self.status.set(ev[1])
                elif kind == "progress":
                    self.bar.configure(value=ev[1])
                elif kind == "done":
                    self._finish()
                    self.result = ev[1]
                    self.bar.configure(value=1.0)
                    self.status.set("Done! Saved to %s" % ev[1])
                    self.open_btn.pack(side="left")
                    self.folder_btn.pack(side="left", padx=10)
                elif kind == "failed":
                    self._finish()
                    if ev[1] == "cancelled":
                        self.status.set("Stopped. Nothing was saved.")
                        self.bar.configure(value=0)
                    else:
                        self.status.set("That didn't work. " + ev[1].splitlines()[0])
                        messagebox.showerror("NoteFall", ev[1])
        except queue.Empty:
            pass
        self.root.after(80, self._poll)

    def _finish(self):
        self.busy = False
        self.go_btn.state(["!disabled"])
        self.cancel_btn.state(["disabled"])


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
