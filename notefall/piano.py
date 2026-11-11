"""Piano recordings to notes with a model made only for piano.

This is ByteDance's "High-resolution Piano Transcription with Pedals by
Regressing Onset and Offset Times" (Kong, Li, Song, Wan and Wang, 2021),
which gets about 96% of note onsets right on the MAESTRO piano recordings,
well ahead of a general purpose model like Basic Pitch. It also hears the
sustain pedal and how hard each key was hit.

The network was exported once to ONNX (scripts/models/export_piano_model.py,
run by the piano-model workflow), so it runs on onnxruntime like everything
else here. The post-processing below is a numpy port of
piano_transcription_inference (MIT licence, Qiuqiang Kong), vectorised where
the original loops frame by frame.

The model file is about 170 MB, so it isn't in the git repo. It's downloaded once,
the first time you use a recording, into NoteFall's own folder (a copy in
assets/models or $NOTEFALL_PIANO_MODEL is used first if there is one).
"""

import hashlib
import json
import os
import sys
import tempfile
import urllib.request

import numpy as np

from . import media

SAMPLE_RATE = 16000
FPS = 100
SEGMENT = SAMPLE_RATE * 10
BEGIN_NOTE = 21
OUTPUTS = ("reg_onset_output", "reg_offset_output", "frame_output", "velocity_output",
           "reg_pedal_onset_output", "reg_pedal_offset_output", "pedal_frame_output")

MODEL_NAME = "piano-transcription.onnx"
MODEL_URL = "https://github.com/Suma-Udd/notefall/releases/download/piano-model/" + MODEL_NAME
BUNDLED = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "models", MODEL_NAME)


def model_dir():
    """Where a downloaded model lives: NoteFall's folder in the user's app data."""
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local")
        return os.path.join(base, "NoteFall", "models")
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/NoteFall/models")
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "notefall", "models")


def model_path():
    """The model file if it's already here (bundled or downloaded), else None."""
    for p in (os.environ.get("NOTEFALL_PIANO_MODEL"), BUNDLED,
              os.path.join(model_dir(), MODEL_NAME)):
        if p and os.path.exists(p) and os.path.getsize(p) > 50_000_000:
            return p
    return None


def _ssl_context():
    import ssl

    ctx = ssl.create_default_context()  # the system's certificates
    try:
        import certifi

        ctx.load_verify_locations(certifi.where())  # plus certifi's, for frozen apps
    except Exception:
        pass
    return ctx


def download_model(on_progress=None, url=MODEL_URL):
    """Fetch the model once. `on_progress(fraction)` while it downloads."""
    dest_dir = model_dir()
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, MODEL_NAME)
    fd, tmp = tempfile.mkstemp(dir=dest_dir, suffix=".part")
    out = os.fdopen(fd, "wb")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "NoteFall"})
        with urllib.request.urlopen(req, timeout=30, context=_ssl_context()) as resp:
            total = int(resp.headers.get("Content-Length") or 0)
            got = 0
            while True:
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
                got += len(chunk)
                if on_progress and total:
                    on_progress(got / total)
        out.close()
        if os.path.getsize(tmp) < 50_000_000:
            raise media.NotefallError("the piano model download was cut short, try again")
        os.replace(tmp, dest)
    except OSError as exc:
        raise media.NotefallError(
            "couldn't download the piano model (%s). It's needed once for recordings, "
            "so check your internet and try again." % exc)
    finally:
        out.close()
        if os.path.exists(tmp):
            os.unlink(tmp)
    return dest


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# running the network ---------------------------------------------------------

def _session(path):
    import onnxruntime as ort

    opts = ort.SessionOptions()
    opts.log_severity_level = 3
    return ort.InferenceSession(path, sess_options=opts, providers=["CPUExecutionProvider"])


def run_model(audio, path, on_progress=None):
    """Model outputs over the whole recording, {name: (frames, 88 or 1)}.

    Like the original: 10 s windows that overlap by half, and each window
    keeps its middle half when they're stitched back together.
    """
    n = len(audio)
    padded = int(np.ceil(n / SEGMENT)) * SEGMENT
    audio = np.concatenate([audio, np.zeros(padded - n, np.float32)])
    starts = list(range(0, padded - SEGMENT + 1, SEGMENT // 2))
    session = _session(path)
    parts = {k: [] for k in OUTPUTS}
    for i, s in enumerate(starts):
        out = session.run(None, {"audio": audio[None, s:s + SEGMENT].astype(np.float32)})
        for k, v in zip(OUTPUTS, out):
            parts[k].append(v[0])
        if on_progress:
            on_progress((i + 1) / len(starts))

    frames = n * FPS // SAMPLE_RATE + 1
    result = {}
    for k, segs in parts.items():
        if len(segs) == 1:
            y = segs[0]
        else:
            segs = [x[:-1] for x in segs]  # 'center=True' adds a frame at the end
            q = segs[0].shape[0] // 4
            y = np.concatenate([segs[0][:3 * q]] + [x[q:3 * q] for x in segs[1:-1]] + [segs[-1][q:]])
        result[k] = y[:frames]
    return result


# post-processing (port of piano_transcription_inference) -------------------

def binarize(reg, threshold, neighbour):
    """Peaks of an onset/offset regression curve, and their sub-frame shift."""
    reg = np.asarray(reg, np.float64)
    n = reg.shape[0]
    binary = np.zeros_like(reg)
    shift = np.zeros_like(reg)
    if n <= 2 * neighbour:
        return binary, shift
    idx = np.arange(neighbour, n - neighbour)
    ok = reg[idx] > threshold
    for i in range(neighbour):
        ok &= reg[idx - i] >= reg[idx - i - 1]
        ok &= reg[idx + i] >= reg[idx + i + 1]
    rows, cols = idx[np.nonzero(ok)[0]], np.nonzero(ok)[1]
    binary[rows, cols] = 1
    x0, x1, x2 = reg[rows - 1, cols], reg[rows, cols], reg[rows + 1, cols]
    with np.errstate(divide="ignore", invalid="ignore"):
        s = np.where(x0 > x2, (x2 - x0) / (x1 - x2) / 2, (x2 - x0) / (x1 - x0) / 2)
    shift[rows, cols] = s
    return binary, shift


def _notes_one_key(frame, onset, onset_shift, offset, offset_shift, velocity, frame_threshold):
    out = []
    bgn = None
    frame_disappear = None
    offset_occur = None
    last = onset.shape[0] - 1
    onsets = set(np.nonzero(onset == 1)[0].tolist())
    last_onset = max(onsets) if onsets else -1
    for i in range(onset.shape[0]):
        if i in onsets:
            if bgn:
                out.append([bgn, max(i - 1, 0), onset_shift[bgn], 0, velocity[bgn]])
                frame_disappear, offset_occur = None, None
            bgn = i
        if bgn and i > bgn:
            if frame[i] <= frame_threshold and not frame_disappear:
                frame_disappear = i
            if offset[i] == 1 and not offset_occur:
                offset_occur = i
            if frame_disappear:
                if offset_occur and offset_occur - bgn > frame_disappear - offset_occur:
                    fin = offset_occur
                else:
                    fin = frame_disappear
                out.append([bgn, fin, onset_shift[bgn], offset_shift[fin], velocity[bgn]])
                bgn, frame_disappear, offset_occur = None, None, None
            if bgn and (i - bgn >= 600 or i == last):
                out.append([bgn, i, onset_shift[bgn], offset_shift[i], velocity[bgn]])
                bgn, frame_disappear, offset_occur = None, None, None
        elif not bgn and i > last_onset:
            break
    return out


def _pedals(frame, offset, offset_shift, frame_threshold=0.5):
    out = []
    bgn = None
    frame_disappear = None
    offset_occur = None
    for i in range(1, frame.shape[0]):
        if frame[i] >= frame_threshold and frame[i] > frame[i - 1] and not bgn:
            bgn = i
        if bgn and i > bgn:
            if frame[i] <= frame_threshold and not frame_disappear:
                frame_disappear = i
            if offset[i] == 1 and not offset_occur:
                offset_occur = i
            if offset_occur:
                out.append([bgn, offset_occur, 0.0, offset_shift[offset_occur]])
                bgn, frame_disappear, offset_occur = None, None, None
            if frame_disappear and i - frame_disappear >= 10:
                out.append([bgn, frame_disappear, 0.0, offset_shift[frame_disappear]])
                bgn, frame_disappear, offset_occur = None, None, None
    return out


def decode(out, onset_threshold=0.3, offset_threshold=0.3, frame_threshold=0.1,
           pedal_offset_threshold=0.2):
    """Model outputs -> ([(start, end, pitch, velocity)], [(down, up)]) in seconds."""
    onset, onset_shift = binarize(out["reg_onset_output"], onset_threshold, 2)
    offset, offset_shift = binarize(out["reg_offset_output"], offset_threshold, 4)
    frame, velocity = out["frame_output"], out["velocity_output"]
    notes = []
    for k in range(frame.shape[1]):
        if not onset[:, k].any():
            continue
        for b, f, osh, fsh, v in _notes_one_key(frame[:, k], onset[:, k], onset_shift[:, k],
                                                offset[:, k], offset_shift[:, k], velocity[:, k],
                                                frame_threshold):
            notes.append(((b + osh) / FPS, (f + fsh) / FPS, k + BEGIN_NOTE,
                          int(np.clip(int(v * 128), 1, 127))))
    notes.sort(key=lambda n: (n[0], n[2]))

    pedals = []
    if "pedal_frame_output" in out:
        p_off, p_shift = binarize(out["reg_pedal_offset_output"], pedal_offset_threshold, 4)
        for b, f, osh, fsh in _pedals(out["pedal_frame_output"][:, 0], p_off[:, 0], p_shift[:, 0]):
            pedals.append(((b + osh) / FPS, (f + fsh) / FPS))
    return notes, pedals


def key_lengths(notes, pedals, reach=12, shortest=0.08, chord=0.04):
    """Cut pedalled notes back to about how long the key itself was held.

    The model was trained on notes stretched to where the sustain pedal
    lifts, so with the pedal down every note comes out as long as it rings,
    not as long as the finger stayed on the key. On real recordings that is
    3 to 4 times too long. The pedal itself is heard well, so for a note that
    ends under the pedal we use the next best clue: the hand lets go when it
    plays its next note. A note is ended at the next onset within `reach`
    semitones (the same hand), notes struck together within `chord` seconds
    count as one chord, and nothing gets shorter than `shortest`. Notes
    played without the pedal keep the length the model heard.
    """
    if not pedals:
        return list(notes)
    notes = sorted(notes, key=lambda n: (n[0], n[2]))
    starts = [n[0] for n in notes]
    downs = np.array([d for d, _ in pedals])
    ups = np.array([u for _, u in pedals])
    out = []
    for s, e, pitch, vel in notes:
        if np.any((downs - 0.05 <= e) & (e <= ups + 0.15) & (downs < e)):
            j = int(np.searchsorted(starts, s + chord, side="right"))
            while j < len(notes) and starts[j] < e:
                if abs(notes[j][2] - pitch) <= reach:
                    e = min(e, max(starts[j], s + shortest))
                    break
                j += 1
        out.append((s, e, pitch, vel))
    return out


def transcribe(audio, on_progress=None, on_status=None, onset_threshold=0.4,
               frame_threshold=0.1, lengths="keys"):
    """16 kHz mono float32 audio -> (notes, pedals). Downloads the model if needed.

    `lengths="keys"` gives notes as long as the key was held (see key_lengths),
    "ring" leaves them as long as they sound with the pedal.
    """
    path = model_path()
    base = 0.0
    if path is None:
        if on_status:
            on_status("Getting the piano model ready (one time download, about 170 MB)…")
        path = download_model(on_progress=(lambda f: on_progress(0.3 * f)) if on_progress else None)
        base = 0.3
    if on_status:
        on_status("Listening for the notes…")
    out = run_model(audio, path, on_progress=(lambda f: on_progress(base + (1 - base) * f))
                    if on_progress else None)
    notes, pedals = decode(out, onset_threshold=onset_threshold, frame_threshold=frame_threshold)
    if lengths == "keys":
        notes = key_lengths(notes, pedals)
    return notes, pedals


def info():
    """What the export recorded about the model, if the json is next to it."""
    p = model_path()
    j = p and os.path.splitext(p)[0] + ".json"
    if j and os.path.exists(j):
        with open(j) as fh:
            return json.load(fh)
    return {}
