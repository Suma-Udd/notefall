"""The Paper look.

A warm sketchbook page, hand drawn note blocks with the note name on them,
a keyboard with every key labelled, the chord that's playing, and two
drawn hands that move along the keyboard and press the keys.

Every frame is worked out from its time alone, nothing is carried from one
frame to the next. Frames are drawn on several processes in any order, so
the hands follow a plan made once up front (where each hand sits, which
finger plays which note) and each frame just reads that plan at time t.
Motion uses eased curves (ease-in-out for travel, ease-out for settling)
so nothing starts or stops dead.
"""

import math
import os

import numpy as np
from PIL import Image, ImageDraw

from . import chords, keyboard
from . import render as R
from .hands import _lerp, ease_out

HAND_FONT = os.path.join(R.ASSETS, "fonts", "Kalam-Bold.ttf")

PAPER = (240, 235, 224)
PAPER_EDGE = (222, 214, 199)
INK = (52, 42, 38)
PENCIL = (120, 110, 100)
KEY_WHITE = (252, 249, 242)
KEY_BLACK = (44, 40, 38)

SS = 3  # supersampling for drawn sprites


def note_label(pitch):
    return keyboard.NOTE_NAMES[pitch % 12]


class PaperRenderer(R.Renderer):
    """Same inputs as Renderer, drawn as a sketchbook page with hands."""

    def __init__(self, *args, hands=True, **kw):
        super().__init__(*args, **kw)
        pal = self.pal
        self.c_paper = pal.get("paper", PAPER)
        self.c_edge = pal.get("paper_edge", PAPER_EDGE)
        self.c_ink = pal.get("ink", INK)
        self.c_pencil = pal.get("pencil", PENCIL)
        self.c_key_white = pal.get("key_white", KEY_WHITE)
        self.c_key_black = pal.get("key_black", KEY_BLACK)
        W, H, ww = self.W, self.H, self.ww
        portrait = H > W * 1.2
        self.white_h = int(min(H * (0.2 if portrait else 0.17), max(H * 0.1, ww * 4.2)))
        self.black_h = int(self.white_h * 0.62)
        self.below_h = int(ww * (2.6 if portrait else 1.5)) if hands else int(ww * 0.4)
        self.kb_top = H - self.bar_h - self.below_h - self.white_h
        self.kb_h = H - self.kb_top
        self.lookahead = self.lookahead_arg or R.default_lookahead(self.kb_top)
        self.pps = self.kb_top / self.lookahead

        self.note_w = max(3, int(round(ww * 0.78)))
        self.note_w_black = max(3, int(round(ww * 0.52)))
        self.f_label = R.load_font(self.note_w * 0.62 * SS, HAND_FONT)
        self.f_label_b = R.load_font(self.note_w_black * 0.6 * SS, HAND_FONT)
        self.f_key = R.load_font(min(ww * 0.42, self.white_h * 0.14), HAND_FONT)
        unit = min(W, H)
        self.f_title = R.load_font(unit * 0.05, HAND_FONT)
        self.f_chord = R.load_font(unit * 0.085, HAND_FONT)
        self.f_next = R.load_font(unit * 0.05, HAND_FONT)
        self.f_pedal = R.load_font(unit * 0.03, HAND_FONT)
        self.chords = chords.timeline(self.notes)

        self._init_hands(hands, 0, self.white_h, self.black_h)
        self._notes_cache = {}
        self._build_paper()

    # the shared Renderer builds its own layers first, these replace them
    def _build_static(self):
        pass

    def shift(self, lead_in, downbeats, duration):
        super().shift(lead_in, downbeats, duration)
        self.chords = [(t + lead_in, c) for t, c in self.chords]
        self._notes_cache.clear()

    # static ----------------------------------------------------------------

    def _build_paper(self):
        W, H = self.W, self.H
        rng = np.random.default_rng(11)
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        # soft vignette towards the edges, like light falling on a page
        dx, dy = (xx / W - 0.5) * 2, (yy / H - 0.45) * 2
        v = np.clip((dx * dx * 0.6 + dy * dy * 0.5), 0, 1)[..., None]
        base = np.array(self.c_paper, np.float32) * (1 - v * 0.6) + np.array(self.c_edge, np.float32) * v * 0.6
        # paper grain at two scales
        fine = rng.normal(0, 1, (H, W)).astype(np.float32)
        coarse = np.asarray(Image.fromarray(
            (rng.normal(128, 40, (H // 8 + 1, W // 8 + 1))).clip(0, 255).astype(np.uint8)
        ).resize((W, H), Image.BICUBIC), np.float32) - 128
        base += (fine * 0.5 + coarse * 0.07)[..., None]
        bg = Image.fromarray(np.clip(base, 0, 255).astype(np.uint8))
        d = ImageDraw.Draw(bg, "RGBA")
        # faint pencil guides at every C and F, dashed like a ruled page
        for pitch in self.whites:
            if pitch % 12 in (0, 5):
                x = int(self.geo[pitch][0])
                a = 46 if pitch % 12 == 0 else 26
                for y in range(0, self.kb_top, 14):
                    d.line([x, y, x, min(self.kb_top, y + 7)], fill=self.c_pencil + (a,), width=1)
        self.paper = bg
        self.paper_arr = np.asarray(bg, np.float32)
        self._draw_paper_keys()

    def _wobbly(self, d, pts, rng, width, fill, amp):
        """A pencil line through pts with a little hand tremble."""
        out = []
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            n = max(2, int(math.hypot(x1 - x0, y1 - y0) / (12 * SS)))
            for k in range(n):
                f = k / n
                out.append((_lerp(x0, x1, f), _lerp(y0, y1, f)))
        out.append(pts[-1])
        ph = rng.random() * 6.28
        jit = [(x + amp * math.sin(i * 0.9 + ph), y + amp * math.cos(i * 0.7 + ph)) for i, (x, y) in enumerate(out)]
        d.line(jit, fill=fill, width=width, joint="curve")

    def _draw_paper_keys(self):
        W, kb_h, ww = self.W, self.kb_h, self.ww
        rng = np.random.default_rng(3)
        big = self.paper.crop((0, self.kb_top, W, self.H)).resize((W * SS, kb_h * SS))
        d = ImageDraw.Draw(big, "RGBA")
        wh, bh = self.white_h * SS, self.black_h * SS
        lw = max(2, int(ww * 0.045 * SS))
        # white keys: paper white, pencil outlines, labels at the bottom
        for pitch in self.whites:
            x0, x1, _ = self.geo[pitch]
            d.rectangle([x0 * SS, 0, x1 * SS, wh], fill=self.c_key_white)
        for pitch in self.whites:
            x0, x1, _ = self.geo[pitch]
            self._wobbly(d, [(x0 * SS, 0), (x0 * SS, wh)], rng, lw, self.c_ink + (230,), SS * 0.5)
        x_end = self.geo[self.whites[-1]][1] * SS
        x_beg = self.geo[self.whites[0]][0] * SS
        self._wobbly(d, [(x_end, 0), (x_end, wh)], rng, lw, self.c_ink + (230,), SS * 0.5)
        self._wobbly(d, [(x_beg, wh), (x_end, wh)], rng, lw, self.c_ink + (230,), SS * 0.6)
        # a thin shadow line under the keys
        d.rectangle([x_beg, wh + lw, x_end, wh + lw * 3], fill=(0, 0, 0, 22))
        self.kb_white = big.resize((W, kb_h), Image.LANCZOS)
        kd = ImageDraw.Draw(self.kb_white, "RGBA")
        self._labels(kd)

        black = Image.new("RGBA", (W * SS, kb_h * SS), (0, 0, 0, 0))
        bd = ImageDraw.Draw(black)
        for pitch, (x0, x1, is_black) in self.geo.items():
            if not is_black:
                continue
            r = (x1 - x0) * SS * 0.14
            bd.rounded_rectangle([x0 * SS, -r, x1 * SS, bh], radius=r, fill=self.c_key_black + (255,),
                                 outline=self.c_ink + (255,), width=lw)
            # a sketched highlight stroke down the key
            hx = _lerp(x0, x1, 0.28) * SS
            self._wobbly(bd, [(hx, bh * 0.08), (hx, bh * 0.8)], rng, max(1, lw // 2),
                         (150, 144, 138, 200), SS * 0.4)
        self.kb_black = black.resize((W, kb_h), Image.LANCZOS)
        # the line the notes land on
        top = ImageDraw.Draw(self.kb_black)
        top.line([0, 0, W, 0], fill=self.c_ink + (255,), width=max(2, int(ww * 0.05)))
        self._tints = {}

    def _labels(self, d):
        for pitch in self.whites:
            x0, x1, _ = self.geo[pitch]
            label = "C%d" % (pitch // 12 - 1) if pitch % 12 == 0 else note_label(pitch)
            tw = d.textlength(label, font=self.f_key)
            if tw > (x1 - x0) * 0.95:
                label = note_label(pitch)
                tw = d.textlength(label, font=self.f_key)
            y = self.white_h - self.f_key.size * 1.35
            d.text(((x0 + x1 - tw) / 2, y), label, font=self.f_key, fill=self.c_ink + (200,))

    def _colour(self, right, playing):
        pal = self.pal
        if playing:
            return pal["right_hi"] if right else pal["left_hi"]
        return pal["right"] if right else pal["left"]

    def _tint(self, right, w, h):
        key = (right, w, h)
        img = self._tints.get(key)
        if img is None:
            img = Image.new("RGBA", (max(1, w), max(1, h)), self._colour(right, True) + (150,))
            self._tints[key] = img
        return img

    # note blocks -------------------------------------------------------

    def _note_sprite(self, i, playing):
        key = (i, playing)
        got = self._notes_cache.get(key)
        if got is not None:
            return got
        s, e, p, v, right = self.notes[i]
        black = self.geo[p][2]
        w = self.note_w_black if black else self.note_w
        h = max(int(self.ww * 0.35), int(round((e - s) * self.pps)))
        pad = max(3, int(w * 0.12))
        Wc, Hc = (w + 2 * pad) * SS, (h + 2 * pad) * SS
        rng = np.random.default_rng(i * 7919 + 17)
        col = self._colour(right, playing)
        if black:
            col = R._scale(col, 0.86)

        # a rounded box traced with a slight wobble
        x0, y0, x1, y1 = pad * SS, pad * SS, (pad + w) * SS, (pad + h) * SS
        r = min(w * 0.24, h * 0.45) * SS
        pts = []
        def arc(cx, cy, a0, a1):
            for k in range(7):
                a = math.radians(_lerp(a0, a1, k / 6))
                pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
        def edge(xa, ya, xb, yb):
            n = max(1, int(math.hypot(xb - xa, yb - ya) / (10 * SS)))
            for k in range(1, n):
                pts.append((_lerp(xa, xb, k / n), _lerp(ya, yb, k / n)))
        arc(x1 - r, y0 + r, -90, 0); edge(x1, y0 + r, x1, y1 - r)
        arc(x1 - r, y1 - r, 0, 90); edge(x1 - r, y1, x0 + r, y1)
        arc(x0 + r, y1 - r, 90, 180); edge(x0, y1 - r, x0, y0 + r)
        arc(x0 + r, y0 + r, 180, 270); edge(x0 + r, y0, x1 - r, y0)
        amp = SS * 0.45
        ph = rng.random(4) * 6.28
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        def wob(pts, k):
            out = []
            for j, (x, y) in enumerate(pts):
                dx, dy = x - cx, y - cy
                ln = math.hypot(dx, dy) or 1
                o = amp * (math.sin(j * 0.55 + ph[k]) + 0.5 * math.sin(j * 1.7 + ph[k + 1]))
                out.append((x + dx / ln * o, y + dy / ln * o))
            return out
        outline = wob(pts, 0)

        mask = Image.new("L", (Wc, Hc), 0)
        ImageDraw.Draw(mask).polygon(outline, fill=255)
        img = Image.new("RGBA", (Wc, Hc), col + (0,))
        fill = Image.new("RGBA", (Wc, Hc), col + (255,))
        fd = ImageDraw.Draw(fill)
        # pencil hatching in a darker shade of the block's colour
        hatch = R._scale(col, 0.78) + (110,)
        step = max(4, int(w * 0.22)) * SS
        hw = max(1, int(SS * 0.9))
        for k in range(-Hc, Wc + Hc, step):
            fd.line([(k, Hc), (k + Hc, 0)], fill=hatch, width=hw)
        # a lighter streak down the left, the paper showing through
        fd.line([(x0 + w * SS * 0.22, y0 + r), (x0 + w * SS * 0.22, y1 - r)],
                fill=(255, 255, 255, 70), width=max(1, int(w * SS * 0.1)))
        img.paste(fill, (0, 0), mask)
        d = ImageDraw.Draw(img)
        lw = max(2, int(w * 0.075 * SS))
        d.line(outline + [outline[0]], fill=self.c_ink + (255,), width=lw, joint="curve")
        # a second, lighter pass, the way a pencil never quite lands on the same line
        d.line(wob(pts, 2) + [outline[0]], fill=self.c_ink + (90,), width=max(1, lw // 2), joint="curve")

        font = self.f_label_b if black else self.f_label
        label = note_label(p)
        tw = d.textlength(label, font=font)
        if h * SS > font.size * 1.25 and tw < w * SS * 1.05:
            d.text(((Wc - tw) / 2, y1 - font.size * 1.22), label, font=font, fill=self.c_ink + (235,))

        sprite = img.resize((w + 2 * pad, h + 2 * pad), Image.LANCZOS)
        got = (sprite, pad, w)
        self._notes_cache[key] = got
        return got

    # per frame ---------------------------------------------------------

    def frame(self, t):
        W, H, ww = self.W, self.H, self.ww
        kb_top, pps = self.kb_top, self.pps
        img = self.paper.copy()
        d = ImageDraw.Draw(img, "RGBA")

        for b in self.downbeats:
            y = kb_top - (b - t) * pps
            if 0 <= y < kb_top:
                for x in range(0, W, 18):
                    d.line([x, y, x + 9, y], fill=self.c_pencil + (70,), width=1)

        visible = np.nonzero((self.starts <= t + self.lookahead) & (self.ends >= t - 0.02))[0]
        keep = set()
        active = {}
        order = sorted(visible, key=lambda i: self.geo[self.notes[i][2]][2])
        marks = []
        for i in order:
            start, end, pitch, vel, right = self.notes[i]
            x0, x1, is_black = self.geo[pitch]
            playing = start <= t <= end
            keep.add((int(i), playing))
            sprite, pad, w = self._note_sprite(int(i), playing)
            bottom = kb_top - (start - t) * pps
            h = sprite.height - 2 * pad
            cx = (x0 + x1) / 2
            img.paste(sprite, (int(round(cx - w / 2)) - pad, int(round(bottom - h)) - pad), sprite)
            if playing:
                active[pitch] = right
            if self.particles and 0 <= t - start < 0.3:
                marks.append((cx, w, t - start, vel))
        for k in [k for k in self._notes_cache if k not in keep]:
            del self._notes_cache[k]

        self._draw_marks(img, d, marks)

        # keyboard
        kb = self.kb_white.copy()
        for pitch, right in active.items():
            x0, x1, is_black = self.geo[pitch]
            if is_black:
                continue
            bx0, bx1 = int(round(x0)) + 1, int(round(x1)) - 1
            tint = self._tint(right, bx1 - bx0, self.white_h - 2)
            kb.paste(tint, (bx0, 1), tint)
        kb.paste(self.kb_black, (0, 0), self.kb_black)
        kd = ImageDraw.Draw(kb, "RGBA")
        for pitch, right in active.items():
            x0, x1, is_black = self.geo[pitch]
            if not is_black:
                continue
            inset = max(1, int((x1 - x0) * 0.12))
            kd.rounded_rectangle([x0 + inset, 2, x1 - inset, self.black_h - inset],
                                 radius=inset, fill=self._colour(right, True) + (215,))
        img.paste(kb, (0, kb_top))

        self.draw_hands(img, t)

        d = ImageDraw.Draw(img, "RGBA")
        self._draw_chord(d, t)
        if self.pedal:
            self._draw_pedal(d, t)
        if self.title:
            self._draw_title(d)
        if self.progress:
            y = H - self.bar_h
            d.rectangle([0, y, W, H], fill=self.c_edge)
            d.rectangle([0, y, int(W * min(1.0, t / self.duration)), H], fill=self.c_ink)

        fade = min(1.0, t / R.FADE_IN, (self.duration - t) / R.FADE_OUT)
        if fade < 1.0:
            f = max(0.0, fade)
            arr = np.asarray(img, np.float32) * f + self.paper_arr * (1 - f)
            img = Image.fromarray(arr.astype(np.uint8))
        return img

    def _draw_marks(self, img, d, marks):
        """Little pencil strokes where a note lands."""
        ww, kb_top = self.ww, self.kb_top
        for cx, w, age, vel in marks:
            f = age / 0.3
            a = int(200 * (1 - f))
            ln = ww * (0.25 + 0.35 * ease_out(f)) * (0.7 + 0.5 * vel / 127)
            for k, ang in enumerate((-150, -125, -55, -30)):
                ra = math.radians(ang)
                r0 = w * 0.55 + ww * 0.15 * ease_out(f)
                sx = cx + math.cos(ra) * r0
                sy = kb_top + math.sin(ra) * r0 * 0.7
                d.line([sx, sy, sx + math.cos(ra) * ln * 0.5, sy + math.sin(ra) * ln * 0.5],
                       fill=self.c_ink + (a,), width=max(1, int(ww * 0.04)))


    def _draw_title(self, d):
        tx, ty = int(min(self.W, self.H) * 0.055), int(min(self.W, self.H) * 0.045)
        d.text((tx, ty), self.title, font=self.f_title, fill=self.c_ink)

    def _draw_chord(self, d, t):
        line = self.chords
        k = chords.at(line, t)
        if k < 0:
            return
        W, H = self.W, self.H
        x = int(min(W, H) * 0.055)
        y = int(min(W, H) * 0.045 + (self.f_title.size * 1.6 if self.title else 0))
        age = t - line[k][0]
        g = ease_out(age / 0.25)
        dy = (1 - g) * self.f_chord.size * 0.35
        name = line[k][1].replace("b5", "♭5") if False else line[k][1]
        d.text((x, y + dy), name, font=self.f_chord, fill=self.c_ink + (int(255 * g),),
               stroke_width=max(2, self.f_chord.size // 14), stroke_fill=self.c_paper + (int(220 * g),))
        if k + 1 < len(line):
            nxt_t, nxt = line[k + 1]
            soon = nxt_t - t
            if soon < self.lookahead * 0.7:
                a = int(170 * ease_out((self.lookahead * 0.7 - soon) / 0.3))
                tw = d.textlength(name, font=self.f_chord)
                ax = x + tw + self.f_chord.size * 0.3
                ay = y + self.f_chord.size * 0.62
                al = self.f_next.size * 1.0
                lw = max(2, self.f_next.size // 12)
                d.line([ax, ay, ax + al, ay], fill=self.c_pencil + (a,), width=lw)
                d.line([ax + al * 0.62, ay - al * 0.3, ax + al, ay, ax + al * 0.62, ay + al * 0.3],
                       fill=self.c_pencil + (a,), width=lw, joint="curve")
                d.text((ax + al * 1.35, ay - self.f_next.size * 0.72), nxt, font=self.f_next,
                       fill=self.c_pencil + (a,))

    def _draw_pedal(self, d, t):
        down = any(a <= t < b for a, b in self.pedal)
        f = self.f_pedal
        label = "Sustain"
        tw = d.textlength(label, font=f)
        x = self.W - min(self.W, self.H) * 0.055 - tw
        y = min(self.W, self.H) * 0.05
        d.text((x, y), label, font=f, fill=self.c_ink + ((235,) if down else (90,)))
        if down:
            uy = y + f.size * 1.25
            d.line([x, uy, x + tw * 0.5, uy + 2, x + tw, uy - 1], fill=self.c_ink + (200,),
                   width=max(2, f.size // 12), joint="curve")
