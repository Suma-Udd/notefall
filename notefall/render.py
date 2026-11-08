"""Frame rendering and encoding."""

import math
import os
import shutil
import subprocess
import tempfile

import numpy as np
from PIL import Image, ImageDraw, ImageFont
import pretty_midi

from . import keyboard, theme

FONT_DIRS = [
    "/usr/share/fonts/truetype/dejavu",
    "/usr/share/fonts/TTF",
    "/Library/Fonts",
    "/System/Library/Fonts/Supplemental",
]


def ffmpeg_bin():
    found = shutil.which("ffmpeg")
    if found:
        return found
    for cand in (
        os.path.expanduser("~/.hermes/tools/ffmpeg-9.0.1-linux-x64/bin/ffmpeg"),
        "/usr/local/bin/ffmpeg",
    ):
        if os.path.exists(cand):
            return cand
    raise SystemExit("ffmpeg not found on PATH. Install it first: apt install ffmpeg")


def ffprobe_bin():
    found = shutil.which("ffprobe")
    if found:
        return found
    guess = os.path.join(os.path.dirname(ffmpeg_bin()), "ffprobe")
    return guess if os.path.exists(guess) else found


def audio_duration(path):
    probe = ffprobe_bin()
    if not probe:
        return 0.0
    out = subprocess.run(
        [probe, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", path],
        capture_output=True, text=True,
    ).stdout.strip()
    try:
        return float(out)
    except ValueError:
        return 0.0


def load_font(size, index=0):
    """Pick a bold sans font, fall back to PIL's bitmap font."""
    names = ["DejaVuSans-Bold.ttf", "DejaVuSans.ttf", "Arial Bold.ttf", "Arial.ttf"]
    for d in FONT_DIRS:
        if not os.path.isdir(d):
            continue
        for name in names:
            for fp in (os.path.join(d, name), os.path.join(d, name.replace(" ", ""))):
                if os.path.exists(fp):
                    try:
                        return ImageFont.truetype(fp, size)
                    except OSError:
                        continue
    return ImageFont.load_default()


def _gradient(width, height, top, bottom):
    ramp = np.linspace(0.0, 1.0, height, dtype=np.float32)[:, None]
    top_a = np.array(top, dtype=np.float32)
    bot_a = np.array(bottom, dtype=np.float32)
    rows = top_a + (bot_a - top_a) * ramp
    img = np.repeat(rows[:, None, :], width, axis=1).astype(np.uint8)
    return Image.fromarray(img)


def collect_notes(pm):
    """Return [(start, end, pitch, velocity, is_right_hand)] sorted by start.

    Hand is decided per instrument when the MIDI has two tracks, which is how
    piano MIDIs are normally written. A pitch threshold is only the fallback
    because a low melody note on the right hand would otherwise turn blue.
    """
    by_instrument = keyboard.split_by_instrument(pm.instruments)
    notes = []
    for ins in pm.instruments:
        if ins.is_drum:
            continue
        hand = by_instrument.get(id(ins)) if by_instrument else None
        for n in ins.notes:
            if n.end - n.start < 0.01:
                continue
            notes.append((n.start, n.end, n.pitch, n.velocity, hand))
    notes.sort(key=lambda x: x[0])
    if by_instrument is None:
        cut = keyboard.percentile_split(notes)
        notes = [(s, e, p, v, p > cut) for (s, e, p, v, _) in notes]
    return notes


def render(
    midi,
    out,
    width=1080,
    height=1920,
    fps=30,
    lookahead=4.0,
    theme_name=theme.DEFAULT_THEME,
    title=None,
    audio=None,
    progress=True,
):
    """Render `midi` (path or PrettyMIDI) to `out` as an mp4."""
    pm = pretty_midi.PrettyMIDI(midi) if isinstance(midi, (str, bytes, os.PathLike)) else midi
    pal = theme.get(theme_name)
    notes = collect_notes(pm)
    if not notes:
        raise SystemExit("no notes found in that MIDI")

    lo, hi = keyboard.snap_range([n[2] for n in notes])

    note_end = max(n[1] for n in notes)
    duration = note_end + 0.9
    if audio:
        duration = max(duration, audio_duration(audio) + 0.25)

    kb_h = int(height * 0.14)
    kb_top = height - kb_h
    kb_x0, kb_x1 = int(width * 0.015), int(width * 0.985)
    geo, ww, whites = keyboard.build_keys(width, kb_x0, kb_x1, lo, hi)
    pps = kb_top / lookahead
    white_h = kb_h * 0.86
    black_h = kb_h * 0.52

    base = _gradient(width, height, pal["bg_top"], pal["bg_bottom"])
    f_title = load_font(max(14, int(height * 0.021)))
    f_note = load_font(max(10, int(white_h * 0.30)))
    radius = max(2, int(ww * 0.14))
    pad = ww * 0.10

    total = int(math.ceil(duration * fps))
    tmpdir = tempfile.mkdtemp(prefix="notefall-")
    raw_path = os.path.join(tmpdir, "raw.mp4")
    encoder = subprocess.Popen(
        [ffmpeg_bin(), "-y", "-loglevel", "error",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "%dx%d" % (width, height),
         "-r", str(fps), "-i", "-", "-an",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
         "-pix_fmt", "yuv420p", raw_path],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )

    try:
        for fi in range(total):
            t = fi / fps
            img = base.copy()
            d = ImageDraw.Draw(img, "RGBA")
            d.rectangle([0, kb_top - int(height * 0.05), width, kb_top],
                        fill=(255, 255, 255, 6))

            active = {}
            for (start, end, pitch, vel, right) in notes:
                if pitch not in geo:
                    continue
                if end < t - 0.02 or start > t + lookahead:
                    continue
                x0, x1, _ = geo[pitch]
                bottom = kb_top - (start - t) * pps
                if bottom < 0:
                    continue
                top = bottom - max(6.0, (end - start) * pps)
                bx0, bx1 = x0 + pad, x1 - pad
                by0, by1 = max(-40.0, top), min(float(kb_top), bottom)
                if by1 - by0 < 3:
                    continue

                col = pal["right"] if right else pal["left"]
                hi_col = pal["right_hi"] if right else pal["left_hi"]
                playing = start <= t <= end
                # brighter for harder hits
                strength = 0.78 + 0.22 * (vel / 127.0)

                glow_alpha = (70 if playing else 26) * strength
                d.rounded_rectangle(
                    [bx0 - 3, by0 - 2, bx1 + 3, by1 + 3],
                    radius=radius + 2,
                    fill=(col[0], col[1], col[2], int(glow_alpha)),
                )
                body_alpha = 255 if playing else 208
                d.rounded_rectangle(
                    [bx0, by0, bx1, by1], radius=radius,
                    fill=(int(col[0] * strength), int(col[1] * strength),
                          int(col[2] * strength), body_alpha),
                )
                cap_h = max(3.0, (by1 - by0) * 0.10)
                d.rounded_rectangle(
                    [bx0, by0, bx1, by0 + cap_h], radius=max(1, radius - 2),
                    fill=(hi_col[0], hi_col[1], hi_col[2], 240),
                )
                if playing:
                    active[pitch] = right

            # keyboard panel
            d.rectangle([0, kb_top, width, height], fill=pal["panel"])
            lip = int(kb_h * 0.10)
            d.rectangle([0, kb_top, width, kb_top + lip], fill=pal["panel_lip"])
            d.line([0, kb_top, width, kb_top], fill=(72, 76, 92), width=2)

            for pitch in whites:
                x0, x1, _ = geo[pitch]
                lit = active.get(pitch)
                if lit is True:
                    fill = pal["right_hi"]
                elif lit is False:
                    fill = pal["left_hi"]
                else:
                    fill = pal["white"]
                d.rectangle([x0 + 1, kb_top, x1 - 1, kb_top + white_h], fill=fill)
                d.rectangle([x0 + 1, kb_top + white_h - 3, x1 - 1, kb_top + white_h],
                            fill=pal["white_edge"])

            for pitch, (x0, x1, is_black) in geo.items():
                if not is_black:
                    continue
                lit = active.get(pitch)
                if lit is True:
                    fill = pal["right"]
                elif lit is False:
                    fill = pal["left"]
                else:
                    fill = pal["black"]
                d.rectangle([x0, kb_top, x1, kb_top + black_h], fill=fill)

            for pitch in whites:
                if pitch % 12 != 0:
                    continue
                x0, x1, _ = geo[pitch]
                label = "C%d" % (pitch // 12 - 1)
                tw = d.textlength(label, font=f_note)
                d.text((x0 + (x1 - x0 - tw) / 2,
                        kb_top + white_h - f_note.size * 1.3),
                       label, font=f_note, fill=pal["label"])

            if title:
                d.text((width * 0.05, height * 0.03), title, font=f_title, fill=pal["text"])

            if progress:
                d.rectangle([0, height - 5, width, height], fill=pal["track"])
                d.rectangle([0, height - 5, int(width * min(1.0, t / duration)), height],
                            fill=pal["right"])

            encoder.stdin.write(img.tobytes())
    except BrokenPipeError:
        pass
    finally:
        try:
            encoder.stdin.close()
        except Exception:
            pass
        err = encoder.stderr.read().decode(errors="replace")
        encoder.wait()

    if not os.path.exists(raw_path) or os.path.getsize(raw_path) == 0:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise SystemExit("ffmpeg failed while encoding frames:\n" + err[-1500:])

    if audio:
        subprocess.run(
            [ffmpeg_bin(), "-y", "-loglevel", "error", "-i", raw_path, "-i", audio,
             "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
             out],
            check=True,
        )
    else:
        shutil.copy(raw_path, out)
    shutil.rmtree(tmpdir, ignore_errors=True)
    return out
