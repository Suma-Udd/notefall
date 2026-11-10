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

import bisect
import math
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from . import chords, keyboard
from . import render as R

HAND_FONT = os.path.join(R.ASSETS, "fonts", "Kalam-Bold.ttf")

PAPER = (240, 235, 224)
PAPER_EDGE = (222, 214, 199)
INK = (52, 42, 38)
PENCIL = (120, 110, 100)
KEY_WHITE = (252, 249, 242)
KEY_BLACK = (44, 40, 38)
SKIN = (244, 208, 180)
SKIN_SHADE = (226, 178, 148)
SKIN_LINE = (150, 96, 72)
NAIL = (250, 226, 214)

HAND_SCALE = 1.1
SS = 3  # supersampling for drawn sprites


# easing ------------------------------------------------------------------

def _c01(x):
    return 0.0 if x <= 0 else 1.0 if x >= 1 else x


def ease_out(x):
    x = _c01(x)
    return 1 - (1 - x) ** 3


def ease_in(x):
    x = _c01(x)
    return x * x * x


def ease_in_out(x):
    x = _c01(x)
    return 4 * x ** 3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2


def _lerp(a, b, f):
    return a + (b - a) * f


def note_label(pitch):
    return keyboard.NOTE_NAMES[pitch % 12]


# hands -------------------------------------------------------------------

# finger 0 is the thumb, 4 the pinky. Offsets are in white keys from the
# hand's centre, measured towards the pinky.
REST_U = (-2.2, -1.05, 0.0, 1.0, 2.0)
KNUCKLE_U = (-1.75, -1.05, -0.02, 0.92, 1.72)
KNUCKLE_V = (1.25, 0.16, 0.0, 0.1, 0.34)   # how far below the knuckle line, in keys
LENGTH = (1.05, 0.95, 1.05, 0.98, 0.78)    # finger length relative to the middle finger
WIDTH = (0.70, 0.56, 0.58, 0.55, 0.48)     # finger width in white keys

ANTICIPATE = 0.16   # a finger starts moving to its key this long before the note
STRIKE = 0.05       # the last bit of the way down
RELEASE = 0.12
RETURN = 0.28
REACH = 2.2         # how far a finger reaches from the centre before the hand moves


class HandPlan:
    """Where one hand is, and which finger plays which note, over the whole song."""

    def __init__(self, notes, geo, ww, right, x_min, x_max):
        self.dir = 1 if right else -1
        self.ww = ww
        self.fingers = [[] for _ in range(5)]
        self.seg_t, self.seg_c = [], []
        clusters = []
        for i, n in enumerate(notes):
            if n[4] != right:
                continue
            if clusters and n[0] - clusters[-1][0] < 0.05:
                clusters[-1][1].append(i)
            else:
                clusters.append((n[0], [i]))
        self.used = bool(clusters)
        c = None
        for start, members in clusters:
            xs = [(geo[notes[i][2]][0] + geo[notes[i][2]][1]) / 2 for i in members]
            lo, hi = min(xs), max(xs)
            reach = REACH * ww
            if c is None or hi - lo > 2 * reach:
                c = (lo + hi) / 2
            else:
                # a real hand only moves as far as it has to
                c = min(max(c, hi - reach), lo + reach)
            c = min(max(c, x_min), x_max)
            self.seg_t.append(start)
            self.seg_c.append(c)
            self._assign(notes, geo, members, xs, c)
        for f in self.fingers:
            f.sort()
        self.f_starts = [[n[0] for n in f] for f in self.fingers]

    def _assign(self, notes, geo, members, xs, c):
        order = sorted(range(len(members)), key=lambda k: xs[k] * self.dir)
        us = [(xs[k] - c) / self.ww * self.dir for k in order]
        fs = [min(range(5), key=lambda f: abs(REST_U[f] - u)) for u in us]
        for k in range(1, len(fs)):
            fs[k] = max(fs[k], fs[k - 1] + 1)
        over = fs[-1] - 4 if fs else 0
        if over > 0:
            fs = [f - over for f in fs]
        fs = [min(4, max(0, f)) for f in fs]
        for k, f in zip(order, fs):
            s, e, p, v, _ = notes[members[k]]
            x0, x1, black = geo[p]
            self.fingers[f].append((s, e, (x0 + x1) / 2, black, v))

    def center(self, t):
        """(x, lift) of the hand at t. Lift is 0..1 while it travels."""
        k = bisect.bisect_right(self.seg_t, t) - 1
        if k < 0:
            return self.seg_c[0], 0.0
        if k + 1 >= len(self.seg_t):
            return self.seg_c[k], 0.0
        c0, c1 = self.seg_c[k], self.seg_c[k + 1]
        if c0 == c1:
            return c0, 0.0
        arrive = self.seg_t[k + 1] - 0.03
        dur = min(0.42, max(0.12, 0.1 + 0.05 * abs(c1 - c0) / self.ww))
        go = max(self.seg_t[k] + 0.06, arrive - dur)
        if t <= go:
            return c0, 0.0
        if go >= arrive:
            return c1, 0.0
        f = (t - go) / (arrive - go)
        lift = math.sin(math.pi * _c01(f)) * min(1.0, abs(c1 - c0) / (self.ww * 3))
        return _lerp(c0, c1, ease_in_out(f)), lift

    def finger(self, f, t, rest_x):
        """(x, press, black) for finger f. press is -1..1: negative lifted, 1 down."""
        notes = self.fingers[f]
        j = bisect.bisect_right(self.f_starts[f], t + ANTICIPATE) - 1
        if j < 0:
            return rest_x, 0.0, 0.0
        s, e, kx, black, vel = notes[j]
        a0 = s - ANTICIPATE
        # where the finger comes from: the key it just played, or its resting spot
        frm = rest_x
        if j > 0:
            ps, pe, px, pblack, _ = notes[j - 1]
            if pe + RETURN > a0:
                frm = _lerp(px, rest_x, ease_out((a0 - pe) / RETURN)) if a0 > pe else px
        lift_h = 0.35 + 0.45 * vel / 127.0
        if t < s - STRIKE:
            g = ease_in_out((t - a0) / (s - STRIKE - a0))
            x = _lerp(frm, kx, g)
            press = -lift_h * ease_out((t - a0) / (s - STRIKE - a0))
            blk = float(black) * g
        elif t < s:
            x = kx
            press = _lerp(-lift_h, 1.0, ease_in((t - (s - STRIKE)) / STRIKE))
            blk = float(black)
        elif t <= e:
            x = kx
            press = 1.0 - 0.12 * ease_out((t - s) / 0.35)
            blk = float(black)
        else:
            r = (t - e) / RETURN
            x = _lerp(kx, rest_x, ease_in_out(r))
            press = _lerp(0.88, 0.0, ease_out((t - e) / RELEASE))
            blk = float(black) * (1 - ease_in_out(r))
        return x, press, blk


def _catmull(points, steps=6):
    """Closed Catmull-Rom spline through `points`."""
    out = []
    n = len(points)
    for i in range(n):
        p0, p1, p2, p3 = points[i - 1], points[i], points[(i + 1) % n], points[(i + 2) % n]
        for s in range(steps):
            t = s / steps
            t2, t3 = t * t, t * t * t
            out.append(tuple(
                0.5 * (2 * p1[k] + (-p0[k] + p2[k]) * t + (2 * p0[k] - 5 * p1[k] + 4 * p2[k] - p3[k]) * t2
                       + (-p0[k] + 3 * p1[k] - 3 * p2[k] + p3[k]) * t3)
                for k in range(2)))
    return out


# (u, v) in white keys: u towards the pinky, v down from the knuckles
PALM = ((-1.42, 0.30), (-0.62, -0.16), (0.40, -0.14), (1.30, 0.02), (2.02, 0.42),
        (2.18, 1.25), (2.0, 2.2), (1.62, 3.05), (1.52, 7.0), (-1.30, 7.0),
        (-1.38, 3.05), (-1.82, 2.15), (-2.05, 1.45), (-1.78, 0.78))


def _taper(p0, p1, w0, w1):
    """Polygon for a segment that narrows from w0 to w1, with round ends drawn separately."""
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    ln = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / ln, dx / ln
    return [(p0[0] + nx * w0 / 2, p0[1] + ny * w0 / 2), (p1[0] + nx * w1 / 2, p1[1] + ny * w1 / 2),
            (p1[0] - nx * w1 / 2, p1[1] - ny * w1 / 2), (p0[0] - nx * w0 / 2, p0[1] - ny * w0 / 2)]


class PaperRenderer(R.Renderer):
    """Same inputs as Renderer, drawn as a sketchbook page with hands."""

    def __init__(self, *args, hands=True, **kw):
        super().__init__(*args, **kw)
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

        self.hands = []
        if hands:
            lo_x, hi_x = ww * 2.4, W - ww * 2.4
            for right in (False, True):
                plan = HandPlan(self.notes, self.geo, ww, right, lo_x, hi_x)
                if plan.used:
                    self.hands.append(plan)
        self.tip_white = self.white_h * 0.72
        self.tip_black = self.black_h * 0.78
        self.knuckle_y = min(self.tip_white + ww * 1.85, self.kb_h - self.bar_h - ww * 0.8)
        self.finger_len = self.knuckle_y - self.tip_white

        self._notes_cache = {}
        self._skin_cache = {}
        self._build_paper()

    # the shared Renderer builds its own layers first, these replace them
    def _build_static(self):
        pass

    def shift(self, lead_in, downbeats, duration):
        super().shift(lead_in, downbeats, duration)
        self.chords = [(t + lead_in, c) for t, c in self.chords]
        for plan in self.hands:
            plan.seg_t = [t + lead_in for t in plan.seg_t]
            plan.fingers = [[(s + lead_in, e + lead_in, x, b, v) for (s, e, x, b, v) in f]
                            for f in plan.fingers]
            plan.f_starts = [[n[0] for n in f] for f in plan.fingers]
        self._notes_cache.clear()

    # static ----------------------------------------------------------------

    def _build_paper(self):
        W, H = self.W, self.H
        rng = np.random.default_rng(11)
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        # soft vignette towards the edges, like light falling on a page
        dx, dy = (xx / W - 0.5) * 2, (yy / H - 0.45) * 2
        v = np.clip((dx * dx * 0.6 + dy * dy * 0.5), 0, 1)[..., None]
        base = np.array(PAPER, np.float32) * (1 - v * 0.6) + np.array(PAPER_EDGE, np.float32) * v * 0.6
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
                    d.line([x, y, x, min(self.kb_top, y + 7)], fill=PENCIL + (a,), width=1)
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
            d.rectangle([x0 * SS, 0, x1 * SS, wh], fill=KEY_WHITE)
        for pitch in self.whites:
            x0, x1, _ = self.geo[pitch]
            self._wobbly(d, [(x0 * SS, 0), (x0 * SS, wh)], rng, lw, INK + (230,), SS * 0.5)
        x_end = self.geo[self.whites[-1]][1] * SS
        x_beg = self.geo[self.whites[0]][0] * SS
        self._wobbly(d, [(x_end, 0), (x_end, wh)], rng, lw, INK + (230,), SS * 0.5)
        self._wobbly(d, [(x_beg, wh), (x_end, wh)], rng, lw, INK + (230,), SS * 0.6)
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
            bd.rounded_rectangle([x0 * SS, -r, x1 * SS, bh], radius=r, fill=KEY_BLACK + (255,),
                                 outline=INK + (255,), width=lw)
            # a sketched highlight stroke down the key
            hx = _lerp(x0, x1, 0.28) * SS
            self._wobbly(bd, [(hx, bh * 0.08), (hx, bh * 0.8)], rng, max(1, lw // 2),
                         (150, 144, 138, 200), SS * 0.4)
        self.kb_black = black.resize((W, kb_h), Image.LANCZOS)
        # the line the notes land on
        top = ImageDraw.Draw(self.kb_black)
        top.line([0, 0, W, 0], fill=INK + (255,), width=max(2, int(ww * 0.05)))
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
            d.text(((x0 + x1 - tw) / 2, y), label, font=self.f_key, fill=INK + (200,))

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
        d.line(outline + [outline[0]], fill=INK + (255,), width=lw, joint="curve")
        # a second, lighter pass, the way a pencil never quite lands on the same line
        d.line(wob(pts, 2) + [outline[0]], fill=INK + (90,), width=max(1, lw // 2), joint="curve")

        font = self.f_label_b if black else self.f_label
        label = note_label(p)
        tw = d.textlength(label, font=font)
        if h * SS > font.size * 1.25 and tw < w * SS * 1.05:
            d.text(((Wc - tw) / 2, y1 - font.size * 1.22), label, font=font, fill=INK + (235,))

        sprite = img.resize((w + 2 * pad, h + 2 * pad), Image.LANCZOS)
        got = (sprite, pad, w)
        self._notes_cache[key] = got
        return got

    # hands -------------------------------------------------------------

    def _centres(self, t):
        """Each hand's (x, lift), nudged apart so the two hands don't sit on top of each other."""
        got = [list(plan.center(t)) for plan in self.hands]
        if len(got) == 2:
            (cl, _), (cr, _) = got
            need = 4.4 * self.ww * HAND_SCALE
            gap = cr - cl
            if 0 < gap < need:
                push = min(1.3 * self.ww, (need - gap) / 2)
                got[0][0] -= push
                got[1][0] += push
        return got

    def _hand_shapes(self, plan, t, c, lift):
        """Shapes (in screen px) for one hand at t."""
        ww = self.ww
        sc = ww * HAND_SCALE * (1.0 + 0.035 * lift)
        dirn = plan.dir
        top = self.kb_top
        ky = top + self.knuckle_y
        wig = 0.035 * ww
        fingers = []
        for f in range(5):
            rest = c + dirn * REST_U[f] * sc + wig * math.sin(t * 1.9 + f * 1.3 + (dirn > 0))
            x, press, blk = plan.finger(f, t, rest)
            kx = c + dirn * KNUCKLE_U[f] * sc
            kv = ky + KNUCKLE_V[f] * sc
            if f == 0:
                kv = ky + KNUCKLE_V[0] * sc
                tip_y = top + _lerp(self.tip_white + ww * 0.55, self.tip_black + ww * 0.3, blk)
            else:
                rest_tip = kv - self.finger_len * LENGTH[f]
                tip_y = _lerp(rest_tip, top + self.tip_black, blk * 0.85)
            tip_y += press * 0.1 * self.finger_len
            fingers.append((f, (kx, kv), (x, tip_y), press))
        return c, lift, sc, fingers

    def _draw_hand(self, img, plan, t, c, lift):
        ww, W, H = self.ww, self.W, self.H
        c, lift, sc, fingers = self._hand_shapes(plan, t, c, lift)
        dirn = plan.dir
        ky = self.kb_top + self.knuckle_y
        palm = [(c + dirn * u * sc, ky + v * sc) for u, v in PALM]
        palm = _catmull(palm)
        xs = [p[0] for p in palm] + [fg[2][0] for fg in fingers]
        ys = [fg[2][1] for fg in fingers]
        bx0 = int(min(xs) - ww * 1.2)
        bx1 = int(max(xs) + ww * 1.2)
        by0 = int(min(ys) - ww * 0.8)
        by1 = H
        if bx1 <= 0 or bx0 >= W:
            return
        bw, bh = bx1 - bx0, by1 - by0
        S = 2

        def L(p):
            return ((p[0] - bx0) * S, (p[1] - by0) * S)

        # shapes: thumb and fingers as two tapered segments with a joint
        pieces = []
        for f, kn, tip, press in fingers:
            wb = WIDTH[f] * sc
            wt = wb * 0.86 * (1.0 + 0.08 * max(0.0, -press))
            mid = (_lerp(kn[0], tip[0], 0.5), _lerp(kn[1], tip[1], 0.5))
            pieces.append((f, kn, mid, tip, wb, wt, press))

        def draw_set(d, grow, fill, shift=None):
            for f, kn, mid, tip, wb, wt, press in pieces:
                off = (0, 0) if shift is None else shift(press)
                a, b, cc = [(p[0] + off[0], p[1] + off[1]) for p in (kn, mid, tip)]
                for p0, p1, w0, w1 in ((a, b, wb, (wb + wt) / 2), (b, cc, (wb + wt) / 2, wt)):
                    d.polygon([L(q) for q in _taper(p0, p1, w0 + grow, w1 + grow)], fill=fill)
                    for q, w in ((p0, w0), (p1, w1)):
                        rr = (w + grow) / 2 * S
                        qx, qy = L(q)
                        d.ellipse([qx - rr, qy - rr, qx + rr, qy + rr], fill=fill)
            off = (0, 0) if shift is None else shift(-0.2 - lift)
            pl = [L((p[0] + off[0], p[1] + off[1])) for p in palm]
            d.polygon(pl, fill=fill)
            if grow:
                d.line(pl + [pl[0]], fill=fill, width=int(grow * S), joint="curve")

        # soft shadow on the keys, further away from the parts held higher
        sh_s = 4
        shadow = Image.new("L", (bw * S // sh_s + 2, bh * S // sh_s + 2), 0)
        sd = ImageDraw.Draw(shadow)

        def shift(press):
            h = 0.5 - 0.5 * press
            return (ww * (0.12 + 0.3 * h), ww * (0.18 + 0.38 * h))

        class _Small:
            def __init__(self, d):
                self.d = d

            def polygon(self, pts, fill):
                self.d.polygon([(x / sh_s, y / sh_s) for x, y in pts], fill=fill)

            def ellipse(self, box, fill):
                self.d.ellipse([v / sh_s for v in box], fill=fill)

            def line(self, pts, fill, width, joint=None):
                pass

        draw_set(_Small(sd), 0, 255, shift)
        shadow = shadow.filter(ImageFilter.GaussianBlur(ww * S / sh_s * 0.22))
        shadow = shadow.resize((bw, bh), Image.BILINEAR).point(lambda v: int(v * 0.32))
        dark = Image.new("RGB", (bw, bh), (70, 50, 40))
        img.paste(dark, (bx0, by0), shadow)

        # outline mask (a bit bigger) and fill mask, so the outline goes round the whole hand
        ol = max(1.5, ww * 0.055)
        outer = Image.new("L", (bw * S, bh * S), 0)
        inner = Image.new("L", (bw * S, bh * S), 0)
        draw_set(ImageDraw.Draw(outer), ol * 2, 255)
        draw_set(ImageDraw.Draw(inner), 0, 255)

        skin = self._skin(bw * S, bh * S, (c - bx0) * S, (ky - by0) * S, sc * S, dirn)
        layer = Image.new("RGBA", (bw * S, bh * S), SKIN_LINE + (0,))
        layer.putalpha(outer)
        layer.paste(skin, (0, 0), inner)

        d = ImageDraw.Draw(layer, "RGBA")
        lwid = max(1, int(ww * 0.03 * S))
        for f, kn, mid, tip, wb, wt, press in pieces:
            # knuckle crease, a nail, and a flush of colour on a pressed fingertip
            jx, jy = L(mid)
            jw = (wb + wt) / 2 * S * 0.32
            d.arc([jx - jw, jy - jw * 0.6, jx + jw, jy + jw * 0.6], 200, 340,
                  fill=SKIN_LINE + (150,), width=lwid)
            tx, ty = L(tip)
            nw, nh = wt * S * 0.30, wt * S * 0.36
            ny = ty + nh * 0.15
            if press > 0.2:
                rr = wt * S * 0.45
                d.ellipse([tx - rr, ty - rr, tx + rr, ty + rr], fill=(236, 150, 140, int(70 * press)))
            d.ellipse([tx - nw, ny - nh, tx + nw, ny + nh], fill=NAIL + (230,),
                      outline=SKIN_LINE + (140,), width=lwid)
        # a few knuckle bumps and a tendon hint on the back of the hand
        for f in (1, 2, 3, 4):
            kn = pieces[f][1]
            kx, kyy = L((kn[0], kn[1] + sc * 0.28))
            r = WIDTH[f] * sc * S * 0.22
            d.arc([kx - r, kyy - r * 0.5, kx + r, kyy + r * 0.5], 190, 350,
                  fill=SKIN_LINE + (90,), width=lwid)
        small = layer.reduce(S)
        img.paste(small, (bx0, by0), small)

    def _skin(self, w, h, cx, ky, sc, dirn):
        """Skin colour with soft light from the top left, a bit deeper towards the wrist.

        Drawn once per hand side on a big canvas and cropped, so a frame only pays for a crop.
        """
        S = 2
        key = ("skin", dirn)
        big = self._skin_cache.get(key)
        if big is None:
            ww = self.ww * HAND_SCALE * S
            bw, bh = int(ww * 16), int(self.H * S)
            ox, oy = bw // 2, int((self.kb_top + self.knuckle_y) * S)
            xs = (np.arange(bw, dtype=np.float32)[None, :] - ox) / (ww * 4.5) * dirn
            yy = (np.arange(bh, dtype=np.float32)[:, None] - oy) / (ww * 4.0)
            f = np.clip(0.35 + 0.35 * xs + 0.35 * yy, 0, 1)[..., None]
            rgb = np.array(SKIN, np.float32) * (1 - f) + np.array(SKIN_SHADE, np.float32) * f
            big = (Image.fromarray(rgb.astype(np.uint8)).convert("RGBA"), ox, oy)
            self._skin_cache[key] = big
        img, ox, oy = big
        x0, y0 = int(ox - cx), int(oy - ky)
        return img.crop((x0, y0, x0 + w, y0 + h))

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
                    d.line([x, y, x + 9, y], fill=PENCIL + (70,), width=1)

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

        # little pencil strokes where a note lands
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
                       fill=INK + (a,), width=max(1, int(ww * 0.04)))

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

        for plan, (c, lift) in zip(self.hands, self._centres(t)):
            self._draw_hand(img, plan, t, c, lift)

        d = ImageDraw.Draw(img, "RGBA")
        self._draw_chord(d, t)
        if self.pedal:
            self._draw_pedal(d, t)
        if self.title:
            tx, ty = int(min(W, H) * 0.055), int(min(W, H) * 0.045)
            d.text((tx, ty), self.title, font=self.f_title, fill=INK)
        if self.progress:
            y = H - self.bar_h
            d.rectangle([0, y, W, H], fill=PAPER_EDGE)
            d.rectangle([0, y, int(W * min(1.0, t / self.duration)), H], fill=INK)

        fade = min(1.0, t / R.FADE_IN, (self.duration - t) / R.FADE_OUT)
        if fade < 1.0:
            f = max(0.0, fade)
            arr = np.asarray(img, np.float32) * f + self.paper_arr * (1 - f)
            img = Image.fromarray(arr.astype(np.uint8))
        return img

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
        d.text((x, y + dy), name, font=self.f_chord, fill=INK + (int(255 * g),),
               stroke_width=max(2, self.f_chord.size // 14), stroke_fill=PAPER + (int(220 * g),))
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
                d.line([ax, ay, ax + al, ay], fill=PENCIL + (a,), width=lw)
                d.line([ax + al * 0.62, ay - al * 0.3, ax + al, ay, ax + al * 0.62, ay + al * 0.3],
                       fill=PENCIL + (a,), width=lw, joint="curve")
                d.text((ax + al * 1.35, ay - self.f_next.size * 0.72), nxt, font=self.f_next,
                       fill=PENCIL + (a,))

    def _draw_pedal(self, d, t):
        down = any(a <= t < b for a, b in self.pedal)
        f = self.f_pedal
        label = "Sustain"
        tw = d.textlength(label, font=f)
        x = self.W - min(self.W, self.H) * 0.055 - tw
        y = min(self.W, self.H) * 0.05
        d.text((x, y), label, font=f, fill=INK + ((235,) if down else (90,)))
        if down:
            uy = y + f.size * 1.25
            d.line([x, uy, x + tw * 0.5, uy + 2, x + tw, uy - 1], fill=INK + (200,),
                   width=max(2, f.size // 12), joint="curve")
