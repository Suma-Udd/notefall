#!/usr/bin/env python3
"""Generate the demo: Fur Elise opening, rendered + synth audio.

    python3 examples/make_demo.py

Writes examples/fur_elise.mid, examples/fur_elise.wav and demo.mp4 in the
repo root. No external assets, so the demo can be rebuilt anywhere.
"""

import os
import sys

import pretty_midi

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from notefall import render, synth  # noqa: E402

MELODY = [
    76, 75, 76, 75, 76, 71, 74, 72, 69, None,
    60, 64, 69, 71, None,
    64, 68, 71, 72, None,
    64, 76, 75, 76, 75, 76, 71, 74, 72, 69, None,
    60, 64, 69, 71, None,
    64, 72, 71, 69,
]
BASS_BEATS = {0: 45, 9: 45, 14: 45, 19: 45, 20: 45, 30: 45, 34: 45}


def build_midi(path):
    pm = pretty_midi.PrettyMIDI(initial_tempo=120)
    right = pretty_midi.Instrument(program=0, name="right hand")
    left = pretty_midi.Instrument(program=0, name="left hand")

    step = 0.25
    t = 0.0
    for pitch in MELODY:
        if pitch:
            right.notes.append(pretty_midi.Note(velocity=92, pitch=pitch,
                                                start=t, end=t + step * 0.95))
        t += step

    for beat, pitch in BASS_BEATS.items():
        start = beat * step
        left.notes.append(pretty_midi.Note(velocity=70, pitch=pitch, start=start, end=start + 1.0))
        left.notes.append(pretty_midi.Note(velocity=62, pitch=pitch + 12,
                                           start=start + step, end=start + 1.0))

    pm.instruments.extend([right, left])
    pm.write(path)
    return path


if __name__ == "__main__":
    ex = os.path.join(ROOT, "examples")
    os.makedirs(ex, exist_ok=True)
    midi = build_midi(os.path.join(ex, "fur_elise.mid"))
    wav = synth.synth(midi, os.path.join(ex, "fur_elise.wav"))
    out = os.path.join(ROOT, "demo.mp4")
    render.render(midi, out, title="Fur Elise", audio=wav, width=1080, height=1920)
    print("demo ->", out)
