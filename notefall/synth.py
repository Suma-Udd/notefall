"""MIDI to audio, so a video made from a MIDI file is never silent.

Two ways to make sound:

* a SoundFont (.sf2) played by FluidSynth, if you have both. That's a real
  sampled piano and sounds great.
* the built-in piano, which needs nothing. It's additive synthesis with the
  things that make a piano sound like a piano: slightly stretched
  harmonics, two detuned strings per note, high partials dying faster than
  low ones, a hammer thump, a soft release and a bit of room reverb. It's
  not a concert grand, but it's pleasant under a visualiser.
"""

import os
import shutil
import subprocess
import wave

import numpy as np
import pretty_midi

from . import keyboard, media

SR = 44100
RELEASE = 0.35
MAX_RING = 7.0


def _voice(freq, dur, vel, sr, rng):
    """One piano note as a mono float array: `dur` seconds held, plus release."""
    ring = min(MAX_RING, dur + RELEASE)
    n = int(sr * ring)
    if n <= 0:
        return np.zeros(1)
    t = np.arange(n) / sr

    # low notes ring for ages, high notes are short
    tau = float(np.clip(4.0 * (261.6 / freq) ** 0.55, 0.5, 9.0))
    brightness = 0.25 + 0.6 * vel
    inharm = 0.00012 * (freq / 261.6) ** 0.8

    y = np.zeros(n)
    k_max = int(min(14, 9000 // max(freq, 1.0)))
    for k in range(1, max(2, k_max + 1)):
        fk = freq * k * np.sqrt(1 + inharm * k * k)
        amp = (1.0 / k ** 1.25) * np.exp(-(k - 1) * (0.55 - 0.4 * brightness))
        decay = tau / (1 + 0.45 * (k - 1))
        env = 0.65 * np.exp(-t / (decay * 0.22)) + 0.35 * np.exp(-t / decay)
        phase = rng.random() * 2 * np.pi
        # two strings, a hair apart, give the slow beating real pianos have
        y += amp * env * (np.sin(2 * np.pi * fk * t + phase)
                          + 0.6 * np.sin(2 * np.pi * fk * 1.0009 * t + phase * 1.3))

    # hammer thump: a few ms of filtered noise
    hn = min(n, int(sr * 0.012))
    if hn > 4:
        noise = rng.standard_normal(hn)
        noise = np.convolve(noise, np.ones(6) / 6, mode="same")
        y[:hn] += noise * np.linspace(1, 0, hn) ** 2 * 0.25 * vel

    attack = min(n, int(sr * 0.002))
    if attack > 1:
        y[:attack] *= np.linspace(0, 1, attack)

    # key released: damper comes down
    held = int(sr * dur)
    if held < n:
        rel = np.exp(-(t[held:] - t[held]) / 0.09)
        y[held:] *= rel

    return y * (vel ** 1.5)


def _reverb(stereo, sr, seconds=1.6, wet=0.16, seed=3):
    """Cheap room reverb: convolve with decaying noise, block by block."""
    rng = np.random.default_rng(seed)
    n_ir = int(sr * seconds)
    t = np.arange(n_ir) / sr
    env = np.exp(-t * 4.2)
    out = stereo.copy()
    block = 1 << 16
    size = 1 << int(np.ceil(np.log2(block + n_ir)))
    for ch in range(stereo.shape[1]):
        ir = rng.standard_normal(n_ir) * env
        ir[: int(sr * 0.012)] = 0  # pre delay
        ir /= np.sqrt(np.sum(ir ** 2))
        ir_f = np.fft.rfft(ir, size)
        x = stereo[:, ch]
        acc = np.zeros(len(x) + n_ir)
        for i in range(0, len(x), block):
            seg = x[i:i + block]
            y = np.fft.irfft(np.fft.rfft(seg, size) * ir_f, size)[: len(seg) + n_ir]
            acc[i:i + len(y)] += y
        out[:, ch] = (1 - wet) * x + wet * acc[: len(x)]
    return out


def _builtin(pm, out_wav, sample_rate):
    rng = np.random.default_rng(11)
    total = pm.get_end_time() + RELEASE + 2.0
    # the sustain pedal keeps the damper off, so a note rings until the pedal lifts
    pedal = keyboard.pedal_intervals(pm.instruments)
    total = max([total] + [e + RELEASE + 2.0 for _, e in pedal])
    n = int(sample_rate * total) + 1
    left = np.zeros(n)
    right = np.zeros(n)
    for ins in pm.instruments:
        if ins.is_drum:
            continue
        for note in ins.notes:
            freq = 440.0 * 2 ** ((note.pitch - 69) / 12)
            end = keyboard.sustained_end(note.end, pedal)
            y = _voice(freq, max(0.08, end - note.start), note.velocity / 127.0,
                       sample_rate, rng)
            start = int(note.start * sample_rate)
            end = min(n, start + len(y))
            if end <= start:
                continue
            # pan like you're sitting at the keyboard: bass left, treble right
            pan = float(np.clip((note.pitch - 64) / 48.0, -0.6, 0.6))
            left[start:end] += y[: end - start] * np.sqrt(0.5 * (1 - pan))
            right[start:end] += y[: end - start] * np.sqrt(0.5 * (1 + pan))

    stereo = np.stack([left, right], axis=1)
    stereo = _reverb(stereo, sample_rate)
    peak = float(np.max(np.abs(stereo))) or 1.0
    stereo = np.tanh(stereo / peak * 1.1) / np.tanh(1.1) * 0.89
    _write_wav(out_wav, stereo, sample_rate)
    return out_wav


def _write_wav(path, stereo, sample_rate):
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes((np.clip(stereo, -1, 1) * 32767).astype("<i2").tobytes())


def fluidsynth_bin():
    return shutil.which("fluidsynth")


def _fluidsynth(midi_path, out_wav, soundfont, sample_rate):
    exe = fluidsynth_bin()
    if not exe:
        raise media.NotefallError(
            "--soundfont needs FluidSynth installed (https://www.fluidsynth.org). "
            "Leave it out to use the built-in piano."
        )
    if not os.path.exists(soundfont):
        raise media.NotefallError("no such soundfont: %s" % soundfont)
    proc = subprocess.run(
        [exe, "-ni", "-q", "-g", "0.8", "-r", str(sample_rate), "-F", out_wav, soundfont, midi_path],
        capture_output=True, text=True, **media.NO_WINDOW,
    )
    if proc.returncode != 0 or not os.path.exists(out_wav):
        raise media.NotefallError("FluidSynth failed:\n" + (proc.stderr or proc.stdout)[-800:])
    return out_wav


def synth(midi, out_wav, sample_rate=SR, soundfont=None):
    """Render a MIDI (path or PrettyMIDI) to a stereo wav. Returns the output path."""
    if soundfont:
        path = midi
        if not isinstance(midi, (str, os.PathLike)):
            path = media.temp_path(".mid")
            midi.write(path)
        return _fluidsynth(os.fspath(path), out_wav, soundfont, sample_rate)
    pm = pretty_midi.PrettyMIDI(os.fspath(midi)) if isinstance(midi, (str, os.PathLike)) else midi
    return _builtin(pm, out_wav, sample_rate)
