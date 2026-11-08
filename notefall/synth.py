"""MIDI to audio preview.

Useful when a MIDI has no recording behind it, so a demo is never silent.
Additive harmonics with per note decay, not a real piano, but it reads fine
under a visualiser.
"""

import wave

import numpy as np
import pretty_midi

SR = 44100
HARMONICS = (1.0, 0.42, 0.22, 0.12, 0.07, 0.04, 0.02)


def _voice(freq, dur, vel):
    n = int(SR * dur)
    if n <= 0:
        return np.zeros(1)
    t = np.arange(n) / SR
    y = np.zeros(n)
    for k, amp in enumerate(HARMONICS, start=1):
        detune = 1 + 0.0004 * k * k
        y += amp * np.sin(2 * np.pi * freq * k * detune * t)
    y *= np.exp(-t * 2.6) * (1 - np.exp(-t * 400))
    y[: min(200, n)] *= np.linspace(0, 1, min(200, n))
    rel = int(SR * min(0.25, dur * 0.4))
    if rel > 10:
        y[-rel:] *= np.linspace(1, 0, rel)
    return y * vel


def synth(midi, out_wav, sample_rate=SR):
    """Render a MIDI file to a stereo wav. Returns the output path."""
    global SR
    SR = sample_rate
    pm = pretty_midi.PrettyMIDI(midi)
    total = pm.get_end_time() + 1.0
    buf = np.zeros(int(SR * total) + 1)
    for ins in pm.instruments:
        if ins.is_drum:
            continue
        for n in ins.notes:
            freq = 440.0 * 2 ** ((n.pitch - 69) / 12)
            y = _voice(freq, max(0.15, n.end - n.start), n.velocity / 127.0)
            start = int(n.start * SR)
            end = min(len(buf), start + len(y))
            if end > start:
                buf[start:end] += y[: end - start]

    peak = float(np.max(np.abs(buf))) or 1.0
    buf = buf / peak * 0.85
    stereo = np.stack([buf, np.roll(buf, 9)], axis=1)
    with wave.open(out_wav, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((stereo * 32767).astype(np.int16).tobytes())
    return out_wav
