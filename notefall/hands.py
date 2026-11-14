"""Two drawn hands that play the notes, for any look.

The motion is planned once for the whole song (where each hand sits, which
finger plays which note) and every frame reads that plan at its own time,
because frames are drawn on several processes in any order. Travel uses an
ease-in-out curve and settling an ease-out, so nothing starts or stops dead.

A renderer mixes in HandsMixin, calls _init_hands() once its keyboard
layout is known, _shift_hands() when the song is moved, and draw_hands()
after drawing the keyboard.
"""

import bisect
import math

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter

SKIN = (244, 208, 180)
SKIN_SHADE = (226, 178, 148)
SKIN_LINE = (150, 96, 72)
NAIL = (250, 226, 214)
HAND_SCALE = 1.1


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


class HandsMixin:
    """Hand drawing shared by every look. Needs W, H, ww, kb_top, kb_h, bar_h, notes, geo."""

    def _init_hands(self, enabled, key_y, white_h, black_h):
        ww = self.ww
        self.hands = []
        if enabled:
            lo_x, hi_x = ww * 2.4, self.W - ww * 2.4
            for right in (False, True):
                plan = HandPlan(self.notes, self.geo, ww, right, lo_x, hi_x)
                if plan.used:
                    self.hands.append(plan)
        self.tip_white = key_y + white_h * 0.72
        self.tip_black = key_y + black_h * 0.78
        self.knuckle_y = min(self.tip_white + ww * 1.85, self.H - self.kb_top - self.bar_h - ww * 0.8)
        self.finger_len = self.knuckle_y - self.tip_white
        self._skin_cache = {}

    def _shift_hands(self, lead_in):
        for plan in self.hands:
            plan.seg_t = [t + lead_in for t in plan.seg_t]
            plan.fingers = [[(s + lead_in, e + lead_in, x, b, v) for (s, e, x, b, v) in f]
                            for f in plan.fingers]
            plan.f_starts = [[n[0] for n in f] for f in plan.fingers]

    def draw_hands(self, img, t):
        for plan, (c, lift) in zip(self.hands, self._centres(t)):
            self._draw_hand(img, plan, t, c, lift)


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
        dark = Image.new("RGB", (bw, bh), self.pal.get("hand_shadow", (70, 50, 40)))
        img.paste(dark, (bx0, by0), shadow)

        # outline mask (a bit bigger) and fill mask, so the outline goes round the whole hand
        ol = max(1.5, ww * 0.055)
        outer = Image.new("L", (bw * S, bh * S), 0)
        inner = Image.new("L", (bw * S, bh * S), 0)
        draw_set(ImageDraw.Draw(outer), ol * 2, 255)
        draw_set(ImageDraw.Draw(inner), 0, 255)

        skin = self._skin(bw * S, bh * S, (c - bx0) * S, (ky - by0) * S, sc * S, dirn)
        SKIN_LINE = self.pal.get("skin_line", globals()["SKIN_LINE"])
        NAIL = self.pal.get("nail", globals()["NAIL"])
        layer = Image.new("RGBA", (bw * S, bh * S), SKIN_LINE + (0,))
        layer.putalpha(outer)
        layer.paste(skin, (0, 0), inner)

        # details go on their own layer, clipped to the hand so nothing spills past the outline
        det = Image.new("RGBA", layer.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(det, "RGBA")
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
        layer.alpha_composite(Image.merge("RGBA", (*det.split()[:3], ImageChops.multiply(det.split()[3], inner))))
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
            rgb = (np.array(self.pal.get("skin", SKIN), np.float32) * (1 - f)
                   + np.array(self.pal.get("skin_shade", SKIN_SHADE), np.float32) * f)
            big = (Image.fromarray(rgb.astype(np.uint8)).convert("RGBA"), ox, oy)
            self._skin_cache[key] = big
        img, ox, oy = big
        x0, y0 = int(ox - cx), int(oy - ky)
        return img.crop((x0, y0, x0 + w, y0 + h))
