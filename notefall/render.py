"""Frame rendering and encoding.

Frames are drawn with Pillow and piped as raw rgb24 straight into x264, so
there's no PNG per frame and no temp clutter. Glow is drawn on a quarter
size layer, blurred, scaled back up and screen-blended on top, which looks
expensive but costs a few milliseconds per frame.
"""

import math
import multiprocessing
import os
import subprocess
import sys

import numpy as np
import pretty_midi
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from . import keyboard, media, theme

FORMATS = {
    "phone": (1080, 1920),
    "youtube": (1920, 1080),
    "square": (1080, 1080),
}

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
TITLE_FONT = os.path.join(ASSETS, "fonts", "InterDisplay-SemiBold.ttf")
UI_FONT = os.path.join(ASSETS, "fonts", "Inter-SemiBold.ttf")

FONT_FILES = [
    # Linux
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    # macOS
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    # Windows
    os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "segoeuib.ttf"),
    os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "arialbd.ttf"),
]

GLOW_SCALE = 4
LEAD_FRACTION = 0.75
TAIL = 1.6
MIN_KEY_PX = 80
FADE_IN = 0.4
FADE_OUT = 1.0


def load_font(size, path=UI_FONT):
    """Inter (bundled) at `size` px, then a system sans, then Pillow's own."""
    size = max(8, int(size))
    for fp in [path] + FONT_FILES:
        if os.path.exists(fp):
            try:
                return ImageFont.truetype(fp, size)
            except OSError:
                continue
    try:
        return ImageFont.load_default(size=size)  # Pillow >= 10.1
    except TypeError:  # pragma: no cover
        return ImageFont.load_default()


def _vgradient(width, height, top, bottom):
    ramp = np.linspace(0.0, 1.0, max(1, height), dtype=np.float32)[:, None]
    top_a = np.array(top, dtype=np.float32)
    bot_a = np.array(bottom, dtype=np.float32)
    rows = top_a + (bot_a - top_a) * ramp
    img = np.repeat(rows[:, None, :], max(1, width), axis=1)
    return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))


def _mix(a, b, f):
    return tuple(int(round(x + (y - x) * f)) for x, y in zip(a, b))


def _scale(c, f):
    return tuple(int(min(255, max(0, x * f))) for x in c)


def collect_notes(pm, split=None, sustain="keys"):
    """Return [(start, end, pitch, velocity, is_right_hand)] sorted by start.

    Hand is decided per track when the MIDI has a left and a right hand
    track, which is how piano MIDIs are normally written. A pitch split is
    only the fallback because a low melody note on the right hand would
    otherwise turn blue. `split` forces a pitch split at that MIDI note.

    `sustain="keys"` draws each block as long as the key was held, which is
    what you copy when learning a piece. `sustain="pedal"` stretches blocks
    to when the sustain pedal lifts, which is how long the note rings.
    """
    by_instrument = None if split is not None else keyboard.split_by_instrument(pm.instruments)
    notes = []
    for ins in pm.instruments:
        if ins.is_drum:
            continue
        hand = by_instrument.get(id(ins)) if by_instrument else None
        for n in ins.notes:
            if n.end - n.start < 0.01 or not (keyboard.A0 <= n.pitch <= keyboard.C8):
                continue
            notes.append((float(n.start), float(n.end), int(n.pitch), int(n.velocity), hand))
    notes.sort(key=lambda x: (x[0], x[2]))
    if sustain == "pedal":
        pedal = keyboard.pedal_intervals(pm.instruments)
        if pedal:
            next_start = {}
            stretched = []
            for (s, e, p, v, h) in reversed(notes):
                e2 = keyboard.sustained_end(e, pedal)
                # a re-struck key cuts the ringing note off
                if p in next_start:
                    e2 = min(e2, next_start[p] - 0.01)
                stretched.append((s, max(e, e2), p, v, h))
                next_start[p] = s
            notes = stretched[::-1]
    if by_instrument is None:
        cut = split if split is not None else keyboard.percentile_split(notes)
        notes = [(s, e, p, v, p >= cut if split is not None else p > cut)
                 for (s, e, p, v, _) in notes]
    return notes


def default_lookahead(fall_height):
    """Seconds of music visible above the keys, so blocks fall at a comfy speed."""
    return float(min(5.0, max(2.2, fall_height / 380.0)))


class _Particles:
    """Deterministic sparks, so the same MIDI always renders the same video."""

    BURST = 7
    EMBER_EVERY = 0.085
    TABLE = 32

    def __init__(self, n_notes, ww, seed=7):
        rng = np.random.default_rng(seed)
        self.ww = ww
        self.burst = rng.random((n_notes, self.BURST, 5))
        self.embers = rng.random((self.TABLE, 5))
        self.g = ww * 11.0

    def _one(self, r, age, cx, base_y, power, life_scale):
        life = (0.45 + 0.5 * r[2]) * life_scale
        if age < 0 or age >= life:
            return None
        vx = (r[0] - 0.5) * self.ww * 3.2
        vy = (0.55 + 0.9 * r[1]) * self.ww * 6.5 * power
        x = cx + vx * age
        y = base_y - (vy * age - 0.5 * self.g * age * age)
        fade = 1.0 - age / life
        size = self.ww * (0.05 + 0.07 * r[3]) * (0.4 + 0.6 * fade)
        return x, y, size, fade

    def sparks(self, idx, t, start, end, cx, kb_top, vel):
        power = 0.65 + 0.5 * vel / 127.0
        for r in self.burst[idx]:
            p = self._one(r, t - start, cx, kb_top, power, 1.0)
            if p:
                yield p
        held = min(t, end) - start
        if held <= 0:
            return
        k_last = int(held / self.EMBER_EVERY)
        for k in range(max(0, k_last - 6), k_last + 1):
            r = self.embers[(idx * 7 + k) % self.TABLE]
            spawn = start + k * self.EMBER_EVERY
            p = self._one(r, t - spawn, cx + (r[4] - 0.5) * self.ww * 0.5, kb_top, 0.45, 0.6)
            if p:
                yield p


def kb_top_band(kb_top, ww):
    """Highest y the hit flare and sparks can reach."""
    return kb_top - ww * 6.5


VEL_STEPS = 6


class Renderer:
    """Holds everything that stays the same between frames."""

    def __init__(self, notes, width, height, fps, lookahead, pal, title, progress,
                 downbeats, particles, duration, pedal=()):
        self.notes = notes
        self.pedal = list(pedal)
        self.W, self.H = width, height
        self.fps = fps
        self.pal = pal
        self.title = title
        self.progress = progress
        self.duration = duration
        self.downbeats = downbeats
        self.lookahead_arg = lookahead

        self.starts = np.array([n[0] for n in notes])
        self.ends = np.array([n[1] for n in notes])

        lo, hi = keyboard.snap_range([n[2] for n in notes],
                                     min_white=max(15, int(width / MIN_KEY_PX)))
        margin = int(width * 0.012)
        self.geo, self.ww, self.whites = keyboard.build_keys(margin, width - margin, lo, hi)
        ww = self.ww

        self.bar_h = max(4, int(height * 0.0035)) if progress else 0
        self.kb_h = int(min(height * 0.2, max(height * 0.1, ww * 4.4)))
        self.kb_top = height - self.kb_h
        self.lookahead = lookahead or default_lookahead(self.kb_top)
        self.pps = self.kb_top / self.lookahead

        self.felt_h = max(3, int(self.kb_h * 0.045))
        self.white_h = self.kb_h - self.felt_h - self.bar_h - max(2, int(self.kb_h * 0.02))
        self.black_h = int(self.white_h * 0.63)
        self.radius = max(2, int(ww * 0.16))
        self.pad = ww * 0.09
        self.outline_w = max(1, int(round(ww * 0.035)))

        self.particles = _Particles(len(notes), ww) if particles else None
        self.f_title = load_font(min(width, height) * 0.042, TITLE_FONT)
        self.f_key = load_font(min(ww * 0.34, self.kb_h * 0.1))
        self.f_pedal = load_font(min(width, height) * 0.022)

        # note blocks are pre-drawn, anti-aliased sprites (caps + a 1 px body strip)
        self.note_w = max(3, int(round(ww - 2 * self.pad)))
        self.note_w_black = max(3, int(round(ww * 0.6 - 2 * self.pad * 0.6)))
        self.glow_m = max(2, int(ww * 0.28))
        self._sprites = {}
        # the glow layer only needs to cover the strip around the hit line
        self.band_top = max(0, int(kb_top_band(self.kb_top, ww)))

        self._lit_cache = {}
        self._build_static()

    # static layers -------------------------------------------------------

    def shift(self, lead_in, downbeats, duration):
        """Move every note later by `lead_in` seconds."""
        self.pedal = [(a + lead_in, b + lead_in) for a, b in self.pedal]
        self.notes = [(s + lead_in, e + lead_in, p, v, rh) for (s, e, p, v, rh) in self.notes]
        self.starts = self.starts + lead_in
        self.ends = self.ends + lead_in
        self.downbeats = downbeats
        self.duration = duration

    def _build_static(self):
        W, H, pal = self.W, self.H, self.pal
        bg = _vgradient(W, H, pal["bg_top"], pal["bg_bottom"])
        d = ImageDraw.Draw(bg, "RGBA")
        lane = pal["lane"]
        for pitch in self.whites:
            if pitch % 12 in (0, 5):
                x0 = int(self.geo[pitch][0])
                alpha = 16 if pitch % 12 == 0 else 8
                d.line([x0, 0, x0, self.kb_top], fill=lane + (alpha,), width=1)
        # soft light pooling just above the keys
        pool = _vgradient(1, int(H * 0.12), (0, 0, 0), _scale(pal["accent"], 0.10))
        pool = pool.resize((W, pool.height))
        bg.paste(ImageChops.add(bg.crop((0, self.kb_top - pool.height, W, self.kb_top)), pool),
                 (0, self.kb_top - pool.height))
        # a whisper of noise stops the dark gradient from banding after compression
        arr = np.asarray(bg, dtype=np.int16)
        noise = np.random.default_rng(5).integers(-1, 2, size=arr.shape[:2], dtype=np.int16)
        arr = np.clip(arr + noise[:, :, None], 0, 255).astype(np.uint8)
        self.background = Image.fromarray(arr)

        self.kb_base = self._draw_keyboard()
        self.black_layer = self._draw_black_keys()

    def _white_box(self, pitch):
        x0, x1, _ = self.geo[pitch]
        gap = max(1, int(round(self.ww * 0.03)))
        return int(round(x0)) + gap // 2 + 1, self.felt_h, int(round(x1)) - (gap - gap // 2), \
            self.felt_h + self.white_h

    def _draw_keyboard(self):
        W, pal = self.W, self.pal
        kb = Image.new("RGB", (W, self.kb_h), pal["panel"])
        white = _vgradient(1, self.white_h, pal["white"], pal["white_bottom"])
        for pitch in self.whites:
            x0, y0, x1, y1 = self._white_box(pitch)
            kb.paste(white.resize((max(1, x1 - x0), self.white_h)), (x0, y0))
        d = ImageDraw.Draw(kb, "RGBA")
        for pitch in self.whites:
            x0, y0, x1, y1 = self._white_box(pitch)
            d.rectangle([x0, y1 - max(2, int(self.white_h * 0.025)), x1, y1],
                        fill=_scale(pal["white_bottom"], 0.82))
        # shadow under the felt
        sh = max(3, int(self.kb_h * 0.05))
        for i in range(sh):
            d.line([0, self.felt_h + i, W, self.felt_h + i],
                   fill=(0, 0, 0, int(110 * (1 - i / sh) ** 2)))
        self._draw_labels(d, None)
        d.rectangle([0, 0, W, self.felt_h], fill=pal["felt"])
        d.line([0, self.felt_h - 1, W, self.felt_h - 1], fill=_scale(pal["felt"], 0.6))
        return kb

    def _draw_labels(self, d, only):
        for pitch in self.whites:
            if pitch % 12 != 0 or (only is not None and pitch not in only):
                continue
            x0, y0, x1, y1 = self._white_box(pitch)
            label = "C%d" % (pitch // 12 - 1)
            tw = d.textlength(label, font=self.f_key)
            if tw > (x1 - x0) * 0.92:
                continue
            fill = self.pal["key_label"] if only is None else (40, 44, 56)
            d.text((x0 + (x1 - x0 - tw) / 2, y1 - self.f_key.size * 1.45), label,
                   font=self.f_key, fill=fill)

    def _black_box(self, x0, x1):
        return int(round(x0)), self.felt_h, int(round(x1)), self.felt_h + self.black_h

    def _draw_black_keys(self):
        layer = Image.new("RGBA", (self.W, self.kb_h), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        pal = self.pal
        for pitch, (x0, x1, is_black) in self.geo.items():
            if not is_black:
                continue
            bx0, by0, bx1, by1 = self._black_box(x0, x1)
            d.rectangle([bx0 - 1, by0, bx1 + 1, by1 + 2], fill=(0, 0, 0, 140))
            d.rectangle([bx0, by0, bx1, by1], fill=pal["black"] + (255,))
            inset = max(1, int((bx1 - bx0) * 0.14))
            face = _vgradient(max(1, bx1 - bx0 - 2 * inset), max(1, int(self.black_h * 0.86)),
                              pal["black_top"], pal["black"]).convert("RGBA")
            layer.paste(face, (bx0 + inset, by0))
        return layer

    def _draw_pedal(self, d, t):
        """A small 'Sustain' pill above the right end of the keys, lit while the pedal is down."""
        down = any(a <= t < b for a, b in self.pedal)
        f = self.f_pedal
        label = "Sustain"
        tw = d.textlength(label, font=f)
        h = f.size * 1.7
        x1 = self.W - self.W * 0.03
        x0 = x1 - tw - h
        y1 = self.kb_top - h * 0.6
        y0 = y1 - h
        accent = self.pal["accent"]
        if down:
            d.rounded_rectangle([x0, y0, x1, y1], radius=h / 2, fill=accent + (210,))
            fill = (16, 18, 26)
        else:
            d.rounded_rectangle([x0, y0, x1, y1], radius=h / 2, outline=accent + (90,),
                                width=max(1, int(h / 14)))
            fill = accent + (110,)
        d.text((x0 + h / 2, y0 + (h - f.size) / 2 - f.size * 0.08), label, font=f, fill=fill)

    def _sprite(self, right, black, playing, vb):
        """(top cap, body strip, bottom cap, full) for one kind of note block."""
        key = (right, black, playing, vb)
        got = self._sprites.get(key)
        if got:
            return got
        pal = self.pal
        col = pal["right"] if right else pal["left"]
        hi = pal["right_hi"] if right else pal["left_hi"]
        if black:
            col, hi = _scale(col, 0.78), _scale(hi, 0.85)
        strength = 0.8 + 0.2 * vb / (VEL_STEPS - 1)
        body = _mix(_scale(col, strength), hi, 0.38) if playing else _scale(col, strength)

        S = 4
        w = self.note_w_black if black else self.note_w
        m, r = self.glow_m, min(self.radius, max(1, (self.note_w_black if black else self.note_w) // 2))
        cap = r + m + 1
        h = 2 * cap + 1
        W, Hh = (w + 2 * m) * S, h * S
        box = [m * S, m * S, (m + w) * S - 1, (h - m) * S - 1]

        glow = Image.new("L", (W, Hh), 0)
        ImageDraw.Draw(glow).rounded_rectangle(box, radius=r * S, fill=255)
        glow = glow.filter(ImageFilter.GaussianBlur(m * S * 0.45))
        glow = glow.point(lambda v: int(v * (0.55 if playing else 0.22)))

        shape = Image.new("L", (W, Hh), 0)
        ImageDraw.Draw(shape).rounded_rectangle(box, radius=r * S, fill=255)

        # rounded, slightly lit from the left, with a crisp lighter rim
        xs = np.linspace(0, 1, W, dtype=np.float32)[None, :, None]
        base = np.array(body, dtype=np.float32)[None, None, :]
        lit = 1.0 + 0.16 * (1 - xs) - 0.10 * xs
        fill = np.clip(base * lit, 0, 255) * np.ones((Hh, 1, 1), dtype=np.float32)
        rgb = Image.fromarray(fill.astype(np.uint8))
        rim = Image.new("L", (W, Hh), 0)
        rw = max(1, self.outline_w) * S
        ImageDraw.Draw(rim).rounded_rectangle(box, radius=r * S, outline=200 if playing else 140,
                                              width=rw)
        rgb = Image.composite(Image.new("RGB", (W, Hh), hi), rgb, rim)

        glow_rgb = Image.new("RGB", (W, Hh), hi if playing else col)
        out = Image.merge("RGBA", (*glow_rgb.split(), glow))
        note = rgb.convert("RGBA")
        note.putalpha(shape)
        out.alpha_composite(note)
        out = out.resize((w + 2 * m, h), Image.LANCZOS)

        full = out
        top = out.crop((0, 0, out.width, cap))
        strip = out.crop((0, cap, out.width, cap + 1))
        bottom = out.crop((0, h - cap, out.width, h))
        got = (top, strip, bottom, full, cap, m, w)
        self._sprites[key] = got
        return got

    def _paste_note(self, img, cx, y0, y1, sprite):
        top, strip, bottom, full, cap, m, w = sprite
        x = int(round(cx - w / 2)) - m
        y = int(round(y0)) - m
        ht = int(round(y1)) - int(round(y0)) + 2 * m
        if ht >= 2 * cap + 1:
            img.paste(top, (x, y), top)
            mid = strip.resize((strip.width, ht - 2 * cap), Image.NEAREST)
            img.paste(mid, (x, y + cap), mid)
            img.paste(bottom, (x, y + ht - cap), bottom)
        elif ht > 2 * m:
            small = full.resize((full.width, ht), Image.BILINEAR)
            img.paste(small, (x, y), small)

    def _lit(self, right, w, h, black):
        key = (right, w, h, black)
        img = self._lit_cache.get(key)
        if img is None:
            pal = self.pal
            col = pal["right"] if right else pal["left"]
            hi = pal["right_hi"] if right else pal["left_hi"]
            if black:
                img = _vgradient(1, h, _scale(col, 0.95), _scale(col, 0.55))
            else:
                img = _vgradient(1, h, hi, col)
            img = img.resize((max(1, w), h))
            self._lit_cache[key] = img
        return img

    # per frame ------------------------------------------------------------

    def frame(self, t):
        W, H, pal = self.W, self.H, self.pal
        kb_top, pps, ww = self.kb_top, self.pps, self.ww
        img = self.background.copy()
        d = ImageDraw.Draw(img, "RGBA")
        gs = GLOW_SCALE
        oy = self.band_top
        glow = Image.new("RGB", (W // gs + 1, (H - oy) // gs + 1), (0, 0, 0))
        g = ImageDraw.Draw(glow)

        def gbox(x0, y0, x1, y1):
            return [x0 / gs, (y0 - oy) / gs, x1 / gs, (y1 - oy) / gs]

        for b in self.downbeats:
            y = kb_top - (b - t) * pps
            if 0 <= y < kb_top:
                d.line([0, y, W, y], fill=pal["lane"] + (14,), width=1)

        visible = np.nonzero((self.starts <= t + self.lookahead) & (self.ends >= t - 0.02))[0]
        active = {}
        sparks = []
        # white key notes first, black key notes on top
        order = sorted(visible, key=lambda i: self.geo[self.notes[i][2]][2])
        for i in order:
            start, end, pitch, vel, right = self.notes[i]
            x0, x1, is_black = self.geo[pitch]
            bottom = kb_top - (start - t) * pps
            top = bottom - max(ww * 0.25, (end - start) * pps)
            by0, by1 = max(-40.0, top), min(float(kb_top), bottom)
            if by1 - by0 < 2:
                continue
            playing = start <= t <= end
            vb = int(round(vel / 127.0 * (VEL_STEPS - 1)))
            cx = (x0 + x1) / 2
            self._paste_note(img, cx, by0, by1, self._sprite(right, is_black, playing, vb))

            hi = pal["right_hi"] if right else pal["left_hi"]
            if playing:
                active[pitch] = right
                col = pal["right"] if right else pal["left"]
                g.rectangle(gbox(cx - ww * 0.35, max(by0, kb_top - ww * 3), cx + ww * 0.35, kb_top),
                            fill=_scale(col, 0.55))
                rx, ry = ww * 1.0, ww * 0.55
                g.ellipse(gbox(cx - rx, kb_top - ry, cx + rx, kb_top + ry), fill=hi)

            if self.particles and t - start < 1.0:
                sparks.append((i, start, end, cx, vel, hi))

        for (i, start, end, cx, vel, hi) in sparks:
            spark = _mix(hi, (255, 255, 255), 0.4)
            for (px, py, size, fade) in self.particles.sparks(i, t, start, end, cx, kb_top, vel):
                if py > kb_top or py < oy:
                    continue
                d.ellipse([px - size, py - size, px + size, py + size],
                          fill=spark + (int(255 * fade),))
                gsz = size * 2.2
                g.ellipse(gbox(px - gsz, py - gsz, px + gsz, py + gsz), fill=_scale(hi, fade))

        # keyboard
        kb = self.kb_base.copy()
        kd = ImageDraw.Draw(kb)
        lit_c = []
        for pitch, right in active.items():
            x0, x1, is_black = self.geo[pitch]
            if is_black:
                continue
            bx0, by0, bx1, by1 = self._white_box(pitch)
            kb.paste(self._lit(right, bx1 - bx0, by1 - by0, False), (bx0, by0))
            g.rectangle(gbox(bx0, kb_top + by0, bx1, kb_top + by0 + self.white_h * 0.5),
                        fill=_scale(pal["right"] if right else pal["left"], 0.5))
            if pitch % 12 == 0:
                lit_c.append(pitch)
        if lit_c:
            self._draw_labels(kd, set(lit_c))
        kb.paste(self.black_layer, (0, 0), self.black_layer)
        for pitch, right in active.items():
            x0, x1, is_black = self.geo[pitch]
            if not is_black:
                continue
            bx0, by0, bx1, by1 = self._black_box(x0, x1)
            kb.paste(self._lit(right, bx1 - bx0, by1 - by0, True), (bx0, by0))
            g.rectangle(gbox(bx0, kb_top + by0, bx1, kb_top + by1),
                        fill=_scale(pal["right"] if right else pal["left"], 0.6))
        img.paste(kb, (0, kb_top))

        # the line notes land on
        d.line([0, kb_top, W, kb_top], fill=_mix(pal["accent"], (255, 255, 255), 0.3) + (200,), width=2)
        g.line([0, (kb_top - oy) / gs, W / gs, (kb_top - oy) / gs], fill=_scale(pal["accent"], 0.35),
               width=max(1, int(ww / gs * 0.12)))

        blur = max(2.0, ww / gs * 0.45)
        bh = H - oy
        glow = glow.filter(ImageFilter.GaussianBlur(blur)).resize(
            (glow.width * gs, glow.height * gs), Image.BILINEAR).crop((0, 0, W, bh))
        img.paste(ImageChops.screen(img.crop((0, oy, W, H)), glow), (0, oy))
        d = ImageDraw.Draw(img, "RGBA")

        if self.pedal:
            self._draw_pedal(d, t)

        if self.title:
            tx, ty = int(min(W, H) * 0.055), int(min(W, H) * 0.05)
            sh = max(2, self.f_title.size // 16)
            d.text((tx + sh, ty + sh), self.title, font=self.f_title, fill=(0, 0, 0, 160))
            d.text((tx, ty), self.title, font=self.f_title, fill=pal["text"])

        if self.progress:
            d.rectangle([0, H - self.bar_h, W, H], fill=pal["track"])
            d.rectangle([0, H - self.bar_h, int(W * min(1.0, t / self.duration)), H],
                        fill=pal["right"])

        fade = min(1.0, t / FADE_IN, (self.duration - t) / FADE_OUT)
        if fade < 1.0:
            arr = np.asarray(img, dtype=np.float32) * max(0.0, fade)
            img = Image.fromarray(arr.astype(np.uint8))
        return img


_WORKER = None


def _worker_init(renderer):
    global _WORKER
    _WORKER = renderer


def _worker_frame(t):
    return _WORKER.frame(t).tobytes()


def make_renderer(notes, width, height, fps, lookahead, pal, title, progress, downbeats,
                  particles, duration, pedal=(), hands=True):
    """The right Renderer for the theme: the glowing default or the Paper look."""
    if pal.get("style") == "paper":
        from .paper import PaperRenderer

        return PaperRenderer(notes, width, height, fps, lookahead, pal, title, progress,
                             downbeats, particles, duration, pedal=pedal, hands=hands)
    return Renderer(notes, width, height, fps, lookahead, pal, title, progress, downbeats,
                    particles, duration, pedal=pedal)


def default_workers():
    return max(1, min(8, (os.cpu_count() or 2) - 1))


def render(
    midi,
    out,
    width=1080,
    height=1920,
    fps=60,
    lookahead=None,
    theme_name=theme.DEFAULT_THEME,
    title=None,
    audio=None,
    progress=True,
    lead_in=None,
    bar_lines=True,
    particles=True,
    split=None,
    sustain="keys",
    hands=True,
    on_progress=None,
    cancel=None,
    crf=17,
    workers=None,
):
    """Render `midi` (path or PrettyMIDI) to `out` as an mp4.

    `on_progress(fraction)` is called as frames are written. `cancel` is
    anything with an `is_set()` method, checked every frame. Frames are drawn
    on `workers` processes (default: CPU count minus one, at most 8).
    """
    if isinstance(midi, (str, bytes, os.PathLike)):
        try:
            pm = pretty_midi.PrettyMIDI(os.fspath(midi))
        except Exception as exc:
            raise media.NotefallError("couldn't read that MIDI file (%s)" % exc)
    else:
        pm = midi
    pal = theme.get(theme_name)
    if sustain not in ("keys", "pedal"):
        raise media.NotefallError("sustain must be 'keys' or 'pedal'")
    notes = collect_notes(pm, split=split, sustain=sustain)
    pedal = keyboard.pedal_intervals(pm.instruments)
    if not notes:
        raise media.NotefallError("no piano notes found in that MIDI")

    # yuv420p needs even dimensions
    width, height = max(64, int(width) // 2 * 2), max(64, int(height) // 2 * 2)

    first = notes[0][0]
    note_end = max(n[1] for n in notes)

    downbeats = []
    if bar_lines:
        try:
            downbeats = [float(b) for b in pm.get_downbeats()]
        except Exception:
            downbeats = []

    # probe the audio before deciding how long the video is
    audio_len = media.duration(audio) if audio else 0.0

    r = make_renderer(notes, width, height, fps, lookahead, pal, title, progress, [],
                      particles, 1.0, pedal=pedal, hands=hands)
    # shift everything so the first notes fall in from the top of the screen
    if lead_in is None:
        lead_in = max(0.0, r.lookahead * LEAD_FRACTION - first)
    lead_in = max(0.0, float(lead_in))
    duration = max(note_end + lead_in + TAIL, audio_len + lead_in + 0.3)
    r.shift(lead_in, [b + lead_in for b in downbeats if b <= note_end], duration)

    total = int(math.ceil(duration * fps))
    out = os.fspath(out)
    part = out + ".part" + (os.path.splitext(out)[1] or ".mp4")
    log_path = media.temp_path(".log")

    cmd = [media.ffmpeg_bin(), "-y", "-hide_banner", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "%dx%d" % (width, height),
           "-r", str(fps), "-i", "-"]
    if audio:
        cmd += ["-i", audio, "-map", "0:v:0", "-map", "1:a:0"]
        filters = []
        if lead_in > 0:
            filters.append("adelay=%d:all=1" % int(round(lead_in * 1000)))
        filters.append("apad")
        filters.append("afade=t=out:st=%.3f:d=%.3f" % (max(0.0, duration - FADE_OUT), FADE_OUT))
        cmd += ["-af", ",".join(filters), "-c:a", "aac", "-b:a", "192k"]
    else:
        cmd += ["-an"]
    # aq-mode 3 keeps the dark gradients clean, a 2 s GOP keeps seeking snappy
    cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
            "-x264-params", "aq-mode=3:keyint=%d" % (fps * 2),
            "-pix_fmt", "yuv420p", "-colorspace", "bt709", "-color_primaries", "bt709",
            "-color_trc", "bt709", "-movflags", "+faststart", "-t", "%.3f" % duration, part]

    ok = False
    with open(log_path, "wb") as log:
        encoder = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                   stderr=log, **media.NO_WINDOW)
        if workers is None:
            workers = default_workers() if total > 90 else 1
        pool = None
        try:
            times = (fi / fps for fi in range(total))
            if workers > 1:
                pool = multiprocessing.get_context("spawn").Pool(
                    workers, initializer=_worker_init, initargs=(r,))
                frames = pool.imap(_worker_frame, times, chunksize=4)
            else:
                frames = (r.frame(t).tobytes() for t in times)
            for fi, data in enumerate(frames):
                if cancel is not None and cancel.is_set():
                    raise media.NotefallError("cancelled")
                encoder.stdin.write(data)
                if on_progress and (fi % 5 == 0 or fi == total - 1):
                    on_progress((fi + 1) / total)
            ok = True
        except BrokenPipeError:
            pass
        finally:
            if pool is not None:
                pool.terminate()
                pool.join()
            try:
                encoder.stdin.close()
            except Exception:
                pass
            if not ok:
                encoder.kill()
            encoder.wait()
            if not ok or encoder.returncode != 0:
                try:
                    os.unlink(part)
                except OSError:
                    pass

    if not ok or encoder.returncode != 0 or not os.path.exists(part):
        with open(log_path, "rb") as fh:
            err = fh.read().decode(errors="replace")
        raise media.NotefallError("ffmpeg failed while encoding:\n" + err[-1500:])
    os.replace(part, out)
    return out


def preview_frames(midi, width=270, height=480, theme_name=theme.DEFAULT_THEME, title=None,
                   sustain="keys", split=None, at=None, count=1, fps=20, particles=True,
                   hands=True):
    """A few frames from a moment in the song, for a live preview."""
    pm = pretty_midi.PrettyMIDI(os.fspath(midi)) if isinstance(midi, (str, os.PathLike)) else midi
    notes = collect_notes(pm, split=split, sustain=sustain)
    if not notes:
        raise media.NotefallError("no piano notes found in that MIDI")
    width, height = max(64, int(width) // 2 * 2), max(64, int(height) // 2 * 2)
    pedal = keyboard.pedal_intervals(pm.instruments)
    r = make_renderer(notes, width, height, fps, None, theme.get(theme_name), title, True, [],
                      particles, 1.0, pedal=pedal, hands=hands)
    end = max(n[1] for n in notes)
    r.shift(0.0, [], end + TAIL)
    if at is None:
        # land a little into the song, on a moment where something is playing
        target = notes[0][0] + min(6.0, (end - notes[0][0]) * 0.3)
        playing = [n[0] for n in notes if n[0] >= target]
        at = (playing[0] - 0.1) if playing else target
    at = max(FADE_IN, at)
    return [r.frame(at + i / fps) for i in range(count)]


def preview(midi, width=270, height=480, **kw):
    """One still frame, for picking colours and sizes before a full render."""
    return preview_frames(midi, width, height, count=1, **kw)[0]


def _cli_progress(frac):
    width = 30
    done = int(frac * width)
    sys.stderr.write("\r  [%s%s] %3d%%" % ("#" * done, "." * (width - done), int(frac * 100)))
    if frac >= 1.0:
        sys.stderr.write("\n")
    sys.stderr.flush()
