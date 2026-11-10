#!/usr/bin/env python3
"""Build the demo from scratch: Bach's Prelude in C (BWV 846), bars 1 to 19.

    python examples/make_demo.py            # every demo video and the .webp previews
    python examples/make_demo.py --paper    # only the Paper look demo
    python examples/make_demo.py --quick    # small fast preview

Writes examples/prelude_in_c.mid (the MIDI is generated here, not
downloaded) and renders it with the built-in piano sound, or with a
SoundFont if you pass --soundfont. No other assets, so it rebuilds anywhere.
"""

import argparse
import os
import sys

import numpy as np
import pretty_midi

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from notefall import render, synth  # noqa: E402

# five notes per bar, played as  1 2 | 3 4 5 3 4 5  twice. First two are the
# left hand, the rest the right hand.
BARS = [
    "C4 E4 G4 C5 E5",
    "C4 D4 A4 D5 F5",
    "B3 D4 G4 D5 F5",
    "C4 E4 G4 C5 E5",
    "C4 E4 A4 E5 A5",
    "C4 D4 F#4 A4 D5",
    "B3 D4 G4 D5 G5",
    "B3 C4 E4 G4 C5",
    "A3 C4 E4 G4 C5",
    "D3 A3 D4 F#4 C5",
    "G3 B3 D4 G4 B4",
    "G3 A#3 E4 G4 C#5",
    "F3 A3 D4 A4 D5",
    "F3 G#3 D4 F4 B4",
    "E3 G3 C4 G4 C5",
    "E3 F3 A3 C4 F4",
    "D3 F3 A3 C4 F4",
    "G2 D3 G3 B3 F4",
    "C3 E3 G3 C4 E4",
]
TEMPO = 70  # quarter notes per minute


def build_midi(path):
    sixteenth = 60.0 / TEMPO / 4
    rng = np.random.default_rng(1)
    pm = pretty_midi.PrettyMIDI(initial_tempo=TEMPO)
    right = pretty_midi.Instrument(program=0, name="Right hand")
    left = pretty_midi.Instrument(program=0, name="Left hand")

    def vel(base):
        return int(np.clip(base + rng.normal(0, 4), 30, 120))

    t = 0.0
    for bar_i, bar in enumerate(BARS):
        p = [pretty_midi.note_name_to_number(n) for n in bar.split()]
        # gentle arc over the piece so it breathes
        swell = 10 * np.sin(np.pi * bar_i / (len(BARS) - 1))
        for half in range(2):
            h0 = t + half * 8 * sixteenth
            h1 = h0 + 8 * sixteenth
            # pedal down just after each new harmony, up right before the next one
            left.control_changes.append(pretty_midi.ControlChange(64, 100, h0 + 0.05))
            left.control_changes.append(pretty_midi.ControlChange(64, 0, h1 - 0.03))
            left.notes.append(pretty_midi.Note(vel(64 + swell), p[0], h0, h1 - 0.02))
            left.notes.append(pretty_midi.Note(vel(58 + swell), p[1], h0 + sixteenth, h1 - 0.02))
            for i, pitch in enumerate([p[2], p[3], p[4]] * 2):
                s = h0 + (2 + i) * sixteenth
                accent = 6 if i in (0, 3) else 0
                right.notes.append(pretty_midi.Note(vel(70 + swell + accent), pitch,
                                                    s, s + sixteenth * 0.92))
        t += 16 * sixteenth

    # final rolled C major chord, pedal held to the end
    left.control_changes.append(pretty_midi.ControlChange(64, 100, t + 0.05))
    left.control_changes.append(pretty_midi.ControlChange(64, 0, t + 5.0))
    for i, name in enumerate(["C3", "G3", "C4", "E4", "G4", "C5"]):
        ins = left if i < 2 else right
        s = t + i * 0.07
        ins.notes.append(pretty_midi.Note(vel(72), pretty_midi.note_name_to_number(name),
                                          s, t + 3.2))

    pm.time_signature_changes.append(pretty_midi.TimeSignature(4, 4, 0))
    pm.instruments.extend([right, left])
    pm.write(path)
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="small, fast preview render")
    ap.add_argument("--soundfont", help="use a .sf2 piano through FluidSynth for the audio")
    ap.add_argument("--theme", default="default")
    ap.add_argument("--paper", action="store_true", help="only render the Paper look demo")
    args = ap.parse_args()

    ex = os.path.join(ROOT, "examples")
    media_dir = os.path.join(ROOT, "docs", "media")
    os.makedirs(media_dir, exist_ok=True)
    midi = build_midi(os.path.join(ex, "prelude_in_c.mid"))
    wav = synth.synth(midi, os.path.join(ex, "prelude_in_c.wav"), soundfont=args.soundfont)
    print("audio ->", wav)

    jobs = [("demo.mp4", 1080, 1920, args.theme), ("demo-landscape.mp4", 1920, 1080, args.theme),
            ("demo-paper.mp4", 1080, 1920, "paper")]
    if args.paper:
        jobs = jobs[2:]
    if args.quick:
        jobs = [("demo-quick.mp4", 540, 960, args.theme)]
    for name, w, h, look in jobs:
        out = os.path.join(media_dir, name)
        print("rendering", out)
        title = "Prelude in C" if look == "paper" else "Prelude in C  ·  J.S. Bach"
        render.render(midi, out, width=w, height=h, title=title,
                      audio=wav, theme_name=look, crf=21, on_progress=render._cli_progress)
    if not args.quick:
        if not args.paper:
            make_webp(os.path.join(media_dir, "demo-landscape.mp4"), os.path.join(media_dir, "demo.webp"))
        make_webp(os.path.join(media_dir, "demo-paper.mp4"), os.path.join(media_dir, "demo-paper.webp"),
                  start=4.0, seconds=8.0, width=360)
    print("done")


def make_webp(video, out, start=9.0, seconds=8.0, width=760, fps=20):
    """The silent looping clip at the top of the README."""
    import subprocess

    from notefall import media

    cmd = [media.ffmpeg_bin(), "-y", "-v", "error", "-ss", str(start), "-t", str(seconds), "-i", video,
           "-vf", "fps=%d,scale=%d:-2:flags=lanczos" % (fps, width), "-c:v", "libwebp_anim",
           "-quality", "72", "-compression_level", "6", "-loop", "0", "-an", out]
    if subprocess.run(cmd).returncode == 0:
        print("preview ->", out)
    else:
        print("skipped the .webp preview (this ffmpeg has no libwebp)")


if __name__ == "__main__":
    main()
