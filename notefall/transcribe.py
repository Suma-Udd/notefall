"""Audio or video recording to MIDI.

There are two listeners. The default is a model trained only on piano
(notefall/piano.py), which is far more accurate on piano recordings and also
hears the sustain pedal. Basic Pitch is the small fallback for when that
model can't be fetched, or for instruments that aren't piano.

Basic Pitch is Spotify's model (Apache 2.0, see
notefall/assets/models/LICENSE-basic-pitch.txt) directly through onnxruntime.

The upstream `basic-pitch` package drags in TensorFlow, CoreML or tflite
depending on your OS and Python version, and on Python 3.12+ it often can't
be installed at all. The model itself is a 230 KB ONNX file, and the note
decoding is plain numpy, so we ship both and skip the dependency mess. The
decoding below is a trimmed port of `basic_pitch.note_creation` and
`basic_pitch.inference` (no pitch bends, no librosa, no scipy).
"""

import os
import subprocess

import numpy as np

from . import media

MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "models", "nmp.onnx")

# constants from basic_pitch.constants
FFT_HOP = 256
AUDIO_SAMPLE_RATE = 22050
AUDIO_WINDOW_LENGTH = 2
ANNOTATIONS_FPS = AUDIO_SAMPLE_RATE // FFT_HOP
ANNOT_N_FRAMES = ANNOTATIONS_FPS * AUDIO_WINDOW_LENGTH
AUDIO_N_SAMPLES = AUDIO_SAMPLE_RATE * AUDIO_WINDOW_LENGTH - FFT_HOP
MIDI_OFFSET = 21
MAX_FREQ_IDX = 87
N_OVERLAPPING_FRAMES = 30
ENERGY_TOL = 11


def load_audio(media_path, sr=AUDIO_SAMPLE_RATE):
    """Decode any audio or video file to mono float32 at `sr` Hz with ffmpeg."""
    proc = subprocess.run(
        [media.ffmpeg_bin(), "-v", "error", "-i", media_path, "-vn",
         "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
        capture_output=True, **media.NO_WINDOW,
    )
    if proc.returncode != 0:
        raise media.NotefallError(
            "couldn't read the audio in %s\n%s"
            % (media_path, proc.stderr.decode(errors="replace")[-800:])
        )
    audio = np.frombuffer(proc.stdout, dtype=np.float32)
    if audio.size == 0:
        raise media.NotefallError("%s has no audio track to listen to" % media_path)
    return audio


def _session():
    try:
        import onnxruntime as ort
    except ImportError as exc:  # pragma: no cover
        raise media.NotefallError(
            "listening to recordings needs onnxruntime: pip install onnxruntime\n(%s)" % exc
        )
    opts = ort.SessionOptions()
    opts.log_severity_level = 3
    return ort.InferenceSession(MODEL_PATH, sess_options=opts, providers=["CPUExecutionProvider"])


def run_model(audio, on_progress=None):
    """Return the model's (note, onset) activation matrices, shape (frames, 88)."""
    session = _session()
    overlap_len = N_OVERLAPPING_FRAMES * FFT_HOP
    hop = AUDIO_N_SAMPLES - overlap_len
    original_length = audio.shape[0]
    audio = np.concatenate([np.zeros(overlap_len // 2, dtype=np.float32), audio])

    starts = list(range(0, audio.shape[0], hop))
    notes, onsets = [], []
    batch = 8
    for b in range(0, len(starts), batch):
        windows = []
        for i in starts[b:b + batch]:
            w = audio[i:i + AUDIO_N_SAMPLES]
            if len(w) < AUDIO_N_SAMPLES:
                w = np.pad(w, (0, AUDIO_N_SAMPLES - len(w)))
            windows.append(w)
        x = np.stack(windows)[:, :, None].astype(np.float32)
        note, onset = session.run(
            ["StatefulPartitionedCall:1", "StatefulPartitionedCall:2"],
            {"serving_default_input_2:0": x},
        )
        notes.append(note)
        onsets.append(onset)
        if on_progress:
            on_progress(min(1.0, (b + batch) / len(starts)))

    def unwrap(chunks):
        out = np.concatenate(chunks)
        n_olap = N_OVERLAPPING_FRAMES // 2
        out = out[:, n_olap:-n_olap, :]
        n_frames = int(np.floor(original_length * (ANNOTATIONS_FPS / AUDIO_SAMPLE_RATE)))
        return out.reshape(-1, out.shape[2])[:n_frames]

    return unwrap(notes), unwrap(onsets)


def _hz_to_midi(hz):
    return 12 * (np.log2(hz) - np.log2(440.0)) + 69


def _frames_to_time(n_frames):
    idx = np.arange(n_frames)
    original = idx * FFT_HOP / AUDIO_SAMPLE_RATE
    window_numbers = np.floor(idx / ANNOT_N_FRAMES)
    # the magic 0.0018 is upstream's, it lines the windows up
    window_offset = (FFT_HOP / AUDIO_SAMPLE_RATE) * (
        ANNOT_N_FRAMES - (AUDIO_N_SAMPLES / FFT_HOP)
    ) + 0.0018
    return original - window_offset * window_numbers


def _inferred_onsets(onsets, frames, n_diff=2):
    """Add onsets where the frame energy jumps, even if the onset head missed it."""
    diffs = []
    for n in range(1, n_diff + 1):
        padded = np.concatenate([np.zeros((n, frames.shape[1])), frames])
        diffs.append(padded[n:, :] - padded[:-n, :])
    frame_diff = np.min(diffs, axis=0)
    frame_diff[frame_diff < 0] = 0
    frame_diff[:n_diff, :] = 0
    peak = np.max(frame_diff)
    if peak > 0:
        frame_diff = np.max(onsets) * frame_diff / peak
    return np.maximum(onsets, frame_diff)


def _clear(energy, i0, i1, f):
    energy[i0:i1, f] = 0
    if f < MAX_FREQ_IDX:
        energy[i0:i1, f + 1] = 0
    if f > 0:
        energy[i0:i1, f - 1] = 0


def decode_notes(frames, onsets, onset_thresh=0.5, frame_thresh=0.3, min_note_len=11,
                 min_freq=None, max_freq=None, melodia_trick=True):
    """Turn activations into [(start_frame, end_frame, pitch, amplitude)]."""
    frames = np.array(frames, dtype=np.float64)
    onsets = np.array(onsets, dtype=np.float64)
    n_frames = frames.shape[0]
    if n_frames < 3:
        return []

    if max_freq is not None:
        idx = int(np.round(_hz_to_midi(max_freq) - MIDI_OFFSET))
        onsets[:, idx:] = 0
        frames[:, idx:] = 0
    if min_freq is not None:
        idx = int(np.round(_hz_to_midi(min_freq) - MIDI_OFFSET))
        onsets[:, :idx] = 0
        frames[:, :idx] = 0

    onsets = _inferred_onsets(onsets, frames)

    # strict local maxima along time, same as scipy.signal.argrelmax(axis=0)
    peaks = np.zeros(onsets.shape, dtype=bool)
    mid = onsets[1:-1]
    peaks[1:-1] = (mid > onsets[:-2]) & (mid > onsets[2:])
    peak_vals = np.where(peaks, onsets, 0.0)

    t_idx, f_idx = np.where(peak_vals >= onset_thresh)
    t_idx, f_idx = t_idx[::-1], f_idx[::-1]  # walk backwards in time

    energy = frames.copy()
    events = []
    for start, f in zip(t_idx, f_idx):
        if start >= n_frames - 1:
            continue
        i = start + 1
        k = 0
        while i < n_frames - 1 and k < ENERGY_TOL:
            k = k + 1 if energy[i, f] < frame_thresh else 0
            i += 1
        i -= k
        if i - start <= min_note_len:
            continue
        _clear(energy, start, i, f)
        events.append((int(start), int(i), int(f) + MIDI_OFFSET, float(np.mean(frames[start:i, f]))))

    if melodia_trick:
        while np.max(energy) > frame_thresh:
            i_mid, f = np.unravel_index(np.argmax(energy), energy.shape)
            energy[i_mid, f] = 0

            i = i_mid + 1
            k = 0
            while i < n_frames - 1 and k < ENERGY_TOL:
                k = k + 1 if energy[i, f] < frame_thresh else 0
                _clear(energy, i, i + 1, f)
                i += 1
            i_end = i - 1 - k

            i = i_mid - 1
            k = 0
            while i > 0 and k < ENERGY_TOL:
                k = k + 1 if energy[i, f] < frame_thresh else 0
                _clear(energy, i, i + 1, f)
                i -= 1
            i_start = i + 1 + k

            if i_end - i_start <= min_note_len:
                continue
            events.append((int(i_start), int(i_end), int(f) + MIDI_OFFSET,
                           float(np.mean(frames[i_start:i_end, f]))))

    return events


def basic_pitch_notes(audio, onset_threshold=0.65, frame_threshold=0.3,
                      minimum_note_length=58.0, minimum_frequency=None,
                      maximum_frequency=None, on_progress=None):
    """22050 Hz audio -> [(start, end, pitch, velocity)] with Basic Pitch."""
    frames, onsets = run_model(audio, on_progress=on_progress)
    min_len = int(np.round(minimum_note_length / 1000 * (AUDIO_SAMPLE_RATE / FFT_HOP)))
    events = decode_notes(frames, onsets, onset_thresh=onset_threshold,
                          frame_thresh=frame_threshold, min_note_len=min_len,
                          min_freq=minimum_frequency, max_freq=maximum_frequency)
    times = _frames_to_time(frames.shape[0])
    notes = []
    for start, end, pitch, amp in events:
        s, e = float(times[start]), float(times[min(end, len(times) - 1)])
        if e - s > 0:
            notes.append((max(0.0, s), e, pitch, int(np.clip(np.round(127 * amp), 1, 127))))
    return notes


def write_midi(notes, pedals, path):
    import pretty_midi

    pm = pretty_midi.PrettyMIDI(initial_tempo=120)
    piano = pretty_midi.Instrument(program=0, name="piano")
    for s, e, pitch, vel in sorted(notes, key=lambda n: (n[0], n[2])):
        piano.notes.append(pretty_midi.Note(velocity=int(vel), pitch=int(pitch),
                                            start=float(s), end=float(e)))
    for down, up in pedals:
        piano.control_changes.append(pretty_midi.ControlChange(64, 127, float(down)))
        piano.control_changes.append(pretty_midi.ControlChange(64, 0, float(up)))
    pm.instruments.append(piano)
    pm.write(path)
    return path


def _in_range(notes, lo_hz, hi_hz):
    lo = -1 if lo_hz is None else _hz_to_midi(lo_hz) - 0.5
    hi = 999 if hi_hz is None else _hz_to_midi(hi_hz) + 0.5
    return [n for n in notes if lo <= n[2] <= hi]


def transcribe(media_path, midi_out=None, engine="auto", onset_threshold=None,
               frame_threshold=None, minimum_note_length=None, minimum_frequency=None,
               maximum_frequency=None, on_progress=None, on_status=None):
    """Listen to a recording and write a MIDI file. Returns the .mid path.

    `engine` is "piano" (the piano model), "basic" (Basic Pitch) or "auto"
    (piano, falling back to Basic Pitch if the model can't be fetched).
    Thresholds left as None use each engine's own default. Raise
    `onset_threshold` if you get ghost notes, lower it if soft notes go
    missing. `minimum_note_length` is in milliseconds.
    """
    from . import piano

    notes = pedals = None
    if engine in ("auto", "piano"):
        try:
            audio = load_audio(media_path, sr=piano.SAMPLE_RATE)
            notes, pedals = piano.transcribe(
                audio, on_progress=on_progress, on_status=on_status,
                onset_threshold=0.3 if onset_threshold is None else onset_threshold,
                frame_threshold=0.1 if frame_threshold is None else frame_threshold)
            if minimum_note_length:
                notes = [n for n in notes if n[1] - n[0] >= minimum_note_length / 1000]
        except media.NotefallError as exc:
            if engine == "piano":
                raise
            if on_status:
                on_status("Couldn't get the piano model, using the basic listener instead (%s)"
                          % str(exc).splitlines()[0])
    if notes is None:
        audio = load_audio(media_path)
        notes = basic_pitch_notes(
            audio, on_progress=on_progress,
            onset_threshold=0.65 if onset_threshold is None else onset_threshold,
            frame_threshold=0.3 if frame_threshold is None else frame_threshold,
            minimum_note_length=58.0 if minimum_note_length is None else minimum_note_length)
        pedals = []
    notes = _in_range(notes, minimum_frequency, maximum_frequency)
    if not notes:
        raise media.NotefallError("couldn't hear any notes in %s" % os.path.basename(media_path))

    if midi_out is None:
        midi_out = media.temp_path(".mid")
    return write_midi(notes, pedals, midi_out)
