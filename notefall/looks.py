"""More hand-made looks, built on the Paper renderer.

Each look keeps everything Paper does (hands, chords, the keyboard layout,
frame-pure drawing) and swaps the page, the keys and the note blocks.
"""

import math
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import render as R
from .hands import _lerp, ease_out
from .paper import SS, PaperRenderer, note_label

FONTS = os.path.join(R.ASSETS, "fonts")


def font(name, size, var=None):
    f = ImageFont.truetype(os.path.join(FONTS, name), max(8, int(size)))
    if var:
        try:
            f.set_variation_by_name(var)
        except (OSError, ValueError):
            pass
    return f


def value_noise(h, w, cell, rng, octaves=3):
    """Smooth noise in about -1..1, `cell` px per blob at the coarsest octave."""
    out = np.zeros((h, w), np.float32)
    amp, tot = 1.0, 0.0
    for _ in range(octaves):
        gh, gw = max(2, int(h / cell) + 2), max(2, int(w / cell) + 2)
        g = Image.fromarray(((rng.random((gh, gw)) * 255)).astype(np.uint8))
        out += (np.asarray(g.resize((w, h), Image.BICUBIC), np.float32) / 127.5 - 1) * amp
        tot += amp
        amp *= 0.5
        cell = max(1.0, cell / 2.2)
    return out / tot


def grain_page(W, H, top, bottom, rng, fine=0.6, coarse=0.08, vignette=0.5, edge=None):
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    ramp = (yy / max(1, H - 1))[..., None]
    base = np.array(top, np.float32) * (1 - ramp) + np.array(bottom, np.float32) * ramp
    if edge is not None and vignette:
        dx, dy = (xx / W - 0.5) * 2, (yy / H - 0.45) * 2
        v = np.clip((dx * dx * 0.6 + dy * dy * 0.5), 0, 1)[..., None] * vignette
        base = base * (1 - v) + np.array(edge, np.float32) * v
    n = rng.normal(0, 1, (H, W)).astype(np.float32) * fine
    n += value_noise(H, W, 10, rng, 2) * coarse * 128
    base += n[..., None]
    return Image.fromarray(np.clip(base, 0, 255).astype(np.uint8))


def round_rect_pts(x0, y0, x1, y1, r, step):
    pts = []

    def arc(cx, cy, a0, a1):
        for k in range(7):
            a = math.radians(_lerp(a0, a1, k / 6))
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))

    def edge(xa, ya, xb, yb):
        n = max(1, int(math.hypot(xb - xa, yb - ya) / step))
        for k in range(1, n):
            pts.append((_lerp(xa, xb, k / n), _lerp(ya, yb, k / n)))

    arc(x1 - r, y0 + r, -90, 0); edge(x1, y0 + r, x1, y1 - r)
    arc(x1 - r, y1 - r, 0, 90); edge(x1 - r, y1, x0 + r, y1)
    arc(x0 + r, y1 - r, 90, 180); edge(x0, y1 - r, x0, y0 + r)
    arc(x0 + r, y0 + r, 180, 270); edge(x0 + r, y0, x1 - r, y0)
    return pts


def wobble(pts, amp, seed):
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    out = []
    for j, (x, y) in enumerate(pts):
        dx, dy = x - cx, y - cy
        ln = math.hypot(dx, dy) or 1
        o = amp * (math.sin(j * 0.55 + seed) + 0.5 * math.sin(j * 1.7 + seed * 2.3))
        out.append((x + dx / ln * o, y + dy / ln * o))
    return out


class LookRenderer(PaperRenderer):
    """Paper with the colours, fonts and key style coming from the class."""

    TITLE_FONT = ("Kalam-Bold.ttf", None)
    CHORD_FONT = ("Kalam-Bold.ttf", None)
    LABEL_FONT = ("Kalam-Bold.ttf", None)
    KEY_FONT = ("Kalam-Bold.ttf", None)
    key_line = (52, 42, 38)
    key_line_a = 230
    key_lw = 0.045
    key_wob = 0.5
    black_line = None
    black_hi = (150, 144, 138, 200)
    hit_line = (52, 42, 38, 255)
    label_col = (52, 42, 38)
    title_case = None

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        unit = min(self.W, self.H)
        self.f_label = font(self.LABEL_FONT[0], self.note_w * 0.6 * SS, self.LABEL_FONT[1])
        self.f_label_b = font(self.LABEL_FONT[0], self.note_w_black * 0.58 * SS, self.LABEL_FONT[1])
        self.f_title = font(self.TITLE_FONT[0], unit * 0.05, self.TITLE_FONT[1])
        self.f_chord = font(self.CHORD_FONT[0], unit * 0.085, self.CHORD_FONT[1])
        self.f_next = font(self.CHORD_FONT[0], unit * 0.05, self.CHORD_FONT[1])
        self.f_pedal = font(self.TITLE_FONT[0], unit * 0.03, self.TITLE_FONT[1])
        self.f_key = font(self.KEY_FONT[0], min(self.ww * 0.42, self.white_h * 0.14), self.KEY_FONT[1])
        # the keys were drawn by Paper's init with its fonts, draw them again with ours
        self._draw_paper_keys()

    # page --------------------------------------------------------------

    def _page(self, rng):
        raise NotImplementedError

    def _build_paper(self):
        rng = np.random.default_rng(11)
        self.paper = self._page(rng)
        self.paper_arr = np.asarray(self.paper, np.float32)
        # keys are drawn in __init__ once our fonts are loaded

    # keys --------------------------------------------------------------

    def _draw_paper_keys(self):
        W, kb_h, ww = self.W, self.kb_h, self.ww
        rng = np.random.default_rng(3)
        big = self.paper.crop((0, self.kb_top, W, self.H)).resize((W * SS, kb_h * SS))
        d = ImageDraw.Draw(big, "RGBA")
        wh, bh = self.white_h * SS, self.black_h * SS
        lw = max(2, int(ww * self.key_lw * SS))
        line = self.key_line + (self.key_line_a,)
        amp = SS * self.key_wob
        for pitch in self.whites:
            x0, x1, _ = self.geo[pitch]
            d.rectangle([x0 * SS, 0, x1 * SS, wh], fill=self.c_key_white)
        self._white_extra(d, wh)
        for pitch in self.whites:
            x0, x1, _ = self.geo[pitch]
            self._wobbly(d, [(x0 * SS, 0), (x0 * SS, wh)], rng, lw, line, amp)
        x_end = self.geo[self.whites[-1]][1] * SS
        x_beg = self.geo[self.whites[0]][0] * SS
        self._wobbly(d, [(x_end, 0), (x_end, wh)], rng, lw, line, amp)
        self._wobbly(d, [(x_beg, wh), (x_end, wh)], rng, lw, line, amp * 1.2)
        d.rectangle([x_beg, wh + lw, x_end, wh + lw * 3], fill=(0, 0, 0, 22))
        self.kb_white = big.resize((W, kb_h), Image.LANCZOS)
        kd = ImageDraw.Draw(self.kb_white, "RGBA")
        if self.f_key is not None:
            self._labels(kd)

        black = Image.new("RGBA", (W * SS, kb_h * SS), (0, 0, 0, 0))
        bd = ImageDraw.Draw(black)
        bl = self.black_line or self.key_line
        for pitch, (x0, x1, is_black) in self.geo.items():
            if not is_black:
                continue
            r = (x1 - x0) * SS * 0.14
            bd.rounded_rectangle([x0 * SS, -r, x1 * SS, bh], radius=r, fill=self.c_key_black + (255,),
                                 outline=bl + (255,), width=lw)
            if self.black_hi:
                hx = _lerp(x0, x1, 0.28) * SS
                self._wobbly(bd, [(hx, bh * 0.08), (hx, bh * 0.8)], rng, max(1, lw // 2),
                             self.black_hi, SS * 0.4)
        self.kb_black = black.resize((W, kb_h), Image.LANCZOS)
        self._hit_line(ImageDraw.Draw(self.kb_black, "RGBA"))
        self._tints = {}

    def _white_extra(self, d, wh):
        pass

    def _hit_line(self, d):
        d.line([0, 0, self.W, 0], fill=self.hit_line, width=max(2, int(self.ww * 0.05)))

    def _labels(self, d):
        for pitch in self.whites:
            x0, x1, _ = self.geo[pitch]
            label = "C%d" % (pitch // 12 - 1) if pitch % 12 == 0 else note_label(pitch)
            tw = d.textlength(label, font=self.f_key)
            if tw > (x1 - x0) * 0.95:
                label = note_label(pitch)
                tw = d.textlength(label, font=self.f_key)
            y = self.white_h - self.f_key.size * 1.35
            d.text(((x0 + x1 - tw) / 2, y), label, font=self.f_key, fill=self.key_line + (190,))

    # notes -------------------------------------------------------------

    def _note_sprite(self, i, playing):
        key = (i, playing)
        got = self._notes_cache.get(key)
        if got is not None:
            return got
        s, e, p, v, right = self.notes[i]
        black = self.geo[p][2]
        w = self.note_w_black if black else self.note_w
        h = max(int(self.ww * 0.35), int(round((e - s) * self.pps)))
        pad = self._pad(w)
        rng = np.random.default_rng(i * 7919 + 17)
        img = self._block(w, h, pad, right, playing, black, rng, v)
        font_ = self.f_label_b if black else self.f_label
        label = note_label(p)
        d = ImageDraw.Draw(img)
        tw = d.textlength(label, font=font_)
        y1 = (pad + h) * SS
        if h * SS > font_.size * 1.25 and tw < w * SS * 1.05:
            self._label(d, ((img.width - tw) / 2, y1 - font_.size * 1.22), label, font_, right, playing)
        sprite = img.resize((w + 2 * pad, h + 2 * pad), Image.LANCZOS)
        got = (sprite, pad, w)
        self._notes_cache[key] = got
        return got

    def _pad(self, w):
        return max(3, int(w * 0.12))

    def _label(self, d, xy, label, font_, right, playing):
        d.text(xy, label, font=font_, fill=self.label_col + (235,))

    def _draw_title(self, d):
        tx, ty = int(min(self.W, self.H) * 0.055), int(min(self.W, self.H) * 0.045)
        d.text((tx, ty), self.title, font=self.f_title, fill=self.c_ink)


# 1. Watercolour --------------------------------------------------------------

class WatercolourRenderer(LookRenderer):
    TITLE_FONT = ("DMSerifDisplay-Italic.ttf", None)
    CHORD_FONT = ("DMSerifDisplay-Italic.ttf", None)
    LABEL_FONT = ("Caveat.ttf", "Bold")
    KEY_FONT = ("Caveat.ttf", "Bold")
    key_line = (96, 92, 96)
    key_line_a = 170
    key_lw = 0.03
    key_wob = 0.35
    black_line = (70, 72, 86)
    black_hi = (150, 156, 176, 120)
    hit_line = (96, 92, 96, 150)
    label_col = (70, 62, 66)

    def _page(self, rng):
        W, H = self.W, self.H
        img = grain_page(W, H, (248, 244, 236), (241, 235, 224), rng, fine=0.9, coarse=0.05,
                         vignette=0.45, edge=(232, 224, 210))
        arr = np.asarray(img, np.float32)
        # cold press tooth: a soft emboss of blotchy noise
        n = value_noise(H, W, 3.5, rng, 2)
        emb = np.roll(n, 1, axis=0) - n
        arr += (emb * 22)[..., None]
        # two pale washes bleeding in from the top corners
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        for (cx, cy, col, rad) in ((0.08, -0.05, (236, 196, 196), 0.55), (0.95, -0.08, (190, 208, 226), 0.6)):
            dd = np.hypot((xx / W - cx) * W / H, yy / H - cy) / rad
            m = np.clip(1 - dd, 0, 1) ** 1.6
            m *= 0.55 + 0.45 * np.clip(value_noise(H, W, 60, rng, 3) + 0.5, 0, 1)
            m = m[..., None] * 0.5
            arr = arr * (1 - m) + np.array(col, np.float32) * m
        return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))

    def _pad(self, w):
        return max(4, int(w * 0.25))

    def _block(self, w, h, pad, right, playing, black, rng, vel):
        Wc, Hc = (w + 2 * pad) * SS, (h + 2 * pad) * SS
        x0, y0, x1, y1 = pad * SS, pad * SS, (pad + w) * SS, (pad + h) * SS
        r = min(w * 0.3, h * 0.45) * SS
        m = Image.new("L", (Wc, Hc), 0)
        ImageDraw.Draw(m).rounded_rectangle([x0, y0, x1, y1], radius=r, fill=255)
        blur = max(2, w * SS * 0.08)
        soft = np.asarray(m.filter(ImageFilter.GaussianBlur(blur)), np.float32) / 255
        edge_n = value_noise(Hc, Wc, w * SS * 0.35, rng, 3)
        mask = np.clip((soft - 0.5 + edge_n * 0.22) * 9 + 0.5, 0, 1)
        # edge darkening, where the pigment dried
        inner = Image.fromarray((mask * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(w * SS * 0.07))
        rim = np.clip(mask - np.asarray(inner, np.float32) / 255, 0, 1) * 2.2
        pool = value_noise(Hc, Wc, w * SS * 0.5, rng, 4)
        gran = rng.normal(0, 1, (Hc, Wc)).astype(np.float32)
        base = 0.6 if not playing else 0.8
        alpha = np.clip(mask * (base + pool * (0.16 if not playing else 0.08) + gran * 0.035) + rim * 0.38 * mask, 0, 1)
        c1 = np.array(self._colour(right, playing), np.float32)
        c2 = np.array(self.pal["right_2" if right else "left_2"], np.float32)
        mix = np.clip(0.5 + value_noise(Hc, Wc, w * SS * 1.6, rng, 2) * (0.9 if not playing else 0.5), 0, 1)[..., None]
        rgb = c1 * (1 - mix) + c2 * mix
        rgb = rgb * (1 - rim[..., None] * 0.25)
        if black:
            rgb *= 0.86
        out = np.dstack([np.clip(rgb, 0, 255), alpha * 255]).astype(np.uint8)
        return Image.fromarray(out, "RGBA")

    def _draw_marks(self, img, d, marks):
        # a few soft drops of colour splash up where a note lands
        ww, top = self.ww, self.kb_top
        for cx, w, age, vel in marks:
            f = age / 0.3
            a = int(150 * (1 - f))
            rng = np.random.default_rng(int(cx * 7))
            for k in range(5):
                ang = math.radians(-160 + rng.random() * 140)
                dist = w * 0.5 + ww * (0.3 + 0.7 * rng.random()) * ease_out(f)
                rr = ww * (0.05 + 0.07 * rng.random()) * (1 - 0.4 * f)
                x, y = cx + math.cos(ang) * dist, top + math.sin(ang) * dist * 0.7
                d.ellipse([x - rr, y - rr, x + rr, y + rr], fill=(120, 110, 130, a))

    def _draw_title(self, d):
        tx, ty = int(min(self.W, self.H) * 0.055), int(min(self.W, self.H) * 0.045)
        d.text((tx, ty), self.title, font=self.f_title, fill=self.c_ink)
        # a thin pencil rule under it
        tw = d.textlength(self.title, font=self.f_title)
        y = ty + self.f_title.size * 1.25
        d.line([tx, y, tx + tw * 0.6, y], fill=self.c_pencil + (150,), width=max(1, int(self.ww * 0.03)))


# 2. Washi journal -------------------------------------------------------------

class WashiRenderer(LookRenderer):
    TITLE_FONT = ("Caveat.ttf", "Bold")
    CHORD_FONT = ("Caveat.ttf", "Bold")
    LABEL_FONT = ("PatrickHand-Regular.ttf", None)
    KEY_FONT = ("PatrickHand-Regular.ttf", None)
    key_line = (70, 66, 70)
    key_line_a = 210
    key_lw = 0.035
    key_wob = 0.25
    black_hi = (120, 118, 124, 160)
    label_col = (60, 54, 56)

    def _page(self, rng):
        W, H = self.W, self.H
        img = grain_page(W, H, (251, 249, 244), (246, 243, 236), rng, fine=0.7, coarse=0.03,
                         vignette=0.3, edge=(236, 232, 222))
        d = ImageDraw.Draw(img, "RGBA")
        step = self.ww * 0.75
        rr = max(1.0, self.ww * 0.045)
        y = step * 0.6
        while y < self.kb_top - step * 0.3:
            x = step * 0.5
            while x < W:
                d.ellipse([x - rr, y - rr, x + rr, y + rr], fill=(150, 146, 140, 110))
                x += step
            y += step
        return img

    def _pad(self, w):
        return max(4, int(w * 0.22))

    def _block(self, w, h, pad, right, playing, black, rng, vel):
        Wc, Hc = (w + 2 * pad) * SS, (h + 2 * pad) * SS
        x0, y0, x1, y1 = pad * SS, pad * SS, (pad + w) * SS, (pad + h) * SS
        col = self._colour(right, playing)
        if black:
            col = R._scale(col, 0.9)
        # torn ends: little irregular teeth across the top and bottom
        tooth = max(2, w * SS * 0.11)
        pts = [(x0, y0)]
        n = max(3, int(w * SS / tooth))
        for k in range(1, n):
            pts.append((_lerp(x0, x1, k / n), y0 + (rng.random() * 0.9 + 0.1) * tooth * (k % 2)))
        pts += [(x1, y0), (x1, y1)]
        for k in range(n - 1, 0, -1):
            pts.append((_lerp(x0, x1, k / n), y1 - (rng.random() * 0.9 + 0.1) * tooth * (k % 2)))
        pts.append((x0, y1))
        mask = Image.new("L", (Wc, Hc), 0)
        ImageDraw.Draw(mask).polygon(pts, fill=255)

        tape = Image.new("RGBA", (Wc, Hc), col + (255,))
        td = ImageDraw.Draw(tape, "RGBA")
        deep = R._scale(col, 0.82)
        if right:
            # diagonal stripes
            stp = max(6, int(w * SS * 0.32))
            for k in range(-Hc, Wc + Hc, stp):
                td.line([(k, Hc), (k + Hc, 0)], fill=deep + (150,), width=max(2, stp // 3))
        else:
            # polka dots
            stp = w * SS * 0.36
            rr = stp * 0.17
            row = 0
            y = stp * 0.5
            while y < Hc:
                x = stp * (0.25 + 0.5 * (row % 2))
                while x < Wc:
                    td.ellipse([x - rr, y - rr, x + rr, y + rr], fill=(255, 255, 255, 170))
                    x += stp
                y += stp * 0.6
                row += 1
        # paper fibre: the tape is a little see-through and uneven
        fib = value_noise(Hc, Wc, w * SS * 0.2, rng, 3)
        a = np.clip((0.86 if playing else 0.78) + fib * 0.08, 0, 1)
        arr = np.asarray(tape, np.float32)
        arr[..., :3] = arr[..., :3] * (1 + fib[..., None] * 0.05)
        arr[..., 3] = np.asarray(mask, np.float32) * a
        tape = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGBA")
        # a soft shadow so it sits on the page
        sh = mask.filter(ImageFilter.GaussianBlur(w * SS * 0.06)).point(lambda v: int(v * 0.16))
        out = Image.new("RGBA", (Wc, Hc), (60, 50, 40, 0))
        out.putalpha(Image.fromarray(np.roll(np.asarray(sh), (int(SS * 1.5), int(SS * 1)), (0, 1))))
        out.alpha_composite(tape)
        if playing:
            # a sheen across the tape
            sd = ImageDraw.Draw(out, "RGBA")
            sd.line([(x0 + w * SS * 0.2, y0 + tooth), (x0 + w * SS * 0.2, y1 - tooth)],
                    fill=(255, 255, 255, 110), width=max(2, int(w * SS * 0.1)))
        return out

    def _label(self, d, xy, label, font_, right, playing):
        # a tiny white sticker with the note name
        x, y = xy
        tw = d.textlength(label, font=font_)
        pad = font_.size * 0.12
        d.rounded_rectangle([x - pad * 1.4, y + font_.size * 0.12, x + tw + pad * 1.4, y + font_.size * 1.1],
                            radius=font_.size * 0.22, fill=(255, 253, 248, 235))
        d.text((x, y - font_.size * 0.05), label, font=font_, fill=self.label_col + (240,))

    def _hit_line(self, d):
        # a strip of mustard washi tape along the top of the keys
        W, ww = self.W, self.ww
        h = max(4, int(ww * 0.32))
        col = self.pal["tape"]
        strip = Image.new("RGBA", (W, h), col + (230,))
        sd = ImageDraw.Draw(strip, "RGBA")
        stp = max(5, int(ww * 0.5))
        for x in range(0, W + h, stp):
            sd.line([(x, h), (x + h, 0)], fill=R._scale(col, 0.86) + (200,), width=max(1, stp // 4))
        base = self.kb_black
        base.paste(strip, (0, 0), strip)
        d.line([0, h, W, h], fill=(0, 0, 0, 30), width=1)

    def _draw_marks(self, img, d, marks):
        # little doodled sparkles
        ww, top = self.ww, self.kb_top
        lw = max(1, int(ww * 0.05))
        for cx, w, age, vel in marks:
            f = age / 0.3
            a = int(230 * (1 - f))
            for side in (-1, 1):
                x = cx + side * (w * 0.6 + ww * 0.35 * ease_out(f))
                y = top - ww * (0.5 + 0.4 * ease_out(f))
                s = ww * 0.24 * (1 - 0.3 * f)
                d.line([x - s, y, x + s, y], fill=self.c_ink + (a,), width=lw)
                d.line([x, y - s, x, y + s], fill=self.c_ink + (a,), width=lw)


# 3. Risograph ---------------------------------------------------------------

class RisoRenderer(LookRenderer):
    TITLE_FONT = ("Fredoka.ttf", "SemiBold")
    CHORD_FONT = ("Fredoka.ttf", "SemiBold")
    LABEL_FONT = ("Nunito.ttf", "Black")
    KEY_FONT = ("Nunito.ttf", "ExtraBold")
    key_line = (34, 74, 168)
    key_line_a = 255
    key_lw = 0.045
    key_wob = 0.0
    black_line = (34, 74, 168)
    black_hi = None
    hit_line = (255, 92, 150, 255)
    label_col = (247, 240, 228)

    def _page(self, rng):
        W, H = self.W, self.H
        img = grain_page(W, H, (245, 239, 226), (240, 232, 216), rng, fine=1.6, coarse=0.04,
                         vignette=0.2, edge=(232, 222, 202))
        # specks of stray ink, like a real riso print
        d = ImageDraw.Draw(img, "RGBA")
        for _ in range(int(W * H / 9000)):
            x, y = rng.random() * W, rng.random() * self.kb_top
            r = rng.random() * 1.4 + 0.3
            col = (255, 92, 150) if rng.random() < 0.5 else (34, 74, 168)
            d.ellipse([x - r, y - r, x + r, y + r], fill=col + (60,))
        # halftone sun in the corner
        cx, cy, R0 = W * 0.86, self.kb_top * 0.28, min(W, H) * 0.22
        stp = max(6, int(self.ww * 0.42))
        for y in range(int(cy - R0), int(cy + R0), stp):
            for x in range(int(cx - R0), int(cx + R0), stp):
                dist = math.hypot(x - cx, y - cy) / R0
                if dist < 1:
                    rr = stp * 0.46 * (1 - dist) ** 0.6
                    d.ellipse([x - rr, y - rr, x + rr, y + rr], fill=(255, 196, 70, 120))
        return img

    def _pad(self, w):
        return max(4, int(w * 0.18))

    def _ink(self, mask, col, rng, density):
        Hc, Wc = mask.shape
        g = rng.random((Hc, Wc)).astype(np.float32)
        blot = value_noise(Hc, Wc, 18, rng, 2)
        a = mask * np.clip(density + blot * 0.12 - (g > 0.985) * 0.6, 0, 1)
        out = np.zeros((Hc, Wc, 4), np.float32)
        out[..., :3] = col
        out[..., 3] = a * 255
        return Image.fromarray(out.astype(np.uint8), "RGBA")

    def _block(self, w, h, pad, right, playing, black, rng, vel):
        Wc, Hc = (w + 2 * pad) * SS, (h + 2 * pad) * SS
        x0, y0, x1, y1 = pad * SS, pad * SS, (pad + w) * SS, (pad + h) * SS
        r = min(w * 0.5, h * 0.5) * SS
        main = self.pal["right"] if right else self.pal["left"]
        other = self.pal["left"] if right else self.pal["right"]
        m = Image.new("L", (Wc, Hc), 0)
        ImageDraw.Draw(m).rounded_rectangle([x0, y0, x1, y1], radius=r, fill=255)
        mask = np.asarray(m, np.float32) / 255
        out = Image.new("RGBA", (Wc, Hc), (0, 0, 0, 0))
        if playing:
            # second ink, knocked out of register, overprinting
            off = int(w * SS * 0.1)
            m2 = np.roll(np.roll(mask, off, 1), -off, 0)
            out.alpha_composite(self._ink(m2, other, rng, 0.85))
            ink = self._ink(mask, main, rng, 0.9)
            arr = np.asarray(ink, np.float32)
            arr[..., 3] *= 0.92
            out.alpha_composite(Image.fromarray(arr.astype(np.uint8), "RGBA"))
        elif h < w * 2.5:
            out.alpha_composite(self._ink(mask, main, rng, 0.92))
        else:
            # halftone fade towards the top of the block
            ink = self._ink(mask, main, rng, 0.92)
            arr = np.asarray(ink, np.float32)
            fade_h = min(h * SS * 0.5, w * SS * 1.6)
            yy = np.arange(Hc, dtype=np.float32)[:, None]
            f = np.clip((yy - y0) / max(1, fade_h), 0, 1)
            stp = max(4, w * SS * 0.16)
            gx = (np.arange(Wc)[None, :] % stp) / stp - 0.5
            gy = ((yy + (np.arange(Wc)[None, :] // stp % 2) * stp / 2) % stp) / stp - 0.5
            dot = np.hypot(gx, gy) < (0.2 + 0.5 * f)
            keep = np.where(f >= 1, 1.0, dot.astype(np.float32))
            arr[..., 3] *= keep
            out.alpha_composite(Image.fromarray(arr.astype(np.uint8), "RGBA"))
        return out

    def _draw_marks(self, img, d, marks):
        # a halftone burst
        ww, top = self.ww, self.kb_top
        for cx, w, age, vel in marks:
            f = age / 0.3
            a = int(220 * (1 - f))
            for k in range(9):
                ang = math.radians(-170 + k * 20)
                for j in range(3):
                    dist = w * 0.5 + ww * (0.25 + 0.3 * j) * (0.4 + 0.6 * ease_out(f))
                    rr = ww * 0.07 * (1 - j * 0.25)
                    x, y = cx + math.cos(ang) * dist, top + math.sin(ang) * dist * 0.75
                    d.ellipse([x - rr, y - rr, x + rr, y + rr], fill=(255, 196, 70, a))

    def _draw_title(self, d):
        tx, ty = int(min(self.W, self.H) * 0.055), int(min(self.W, self.H) * 0.045)
        o = max(2, int(self.f_title.size * 0.05))
        d.text((tx + o, ty + o), self.title, font=self.f_title, fill=self.pal["left"] + (230,))
        d.text((tx, ty), self.title, font=self.f_title, fill=self.pal["right"] + (235,))

    def _draw_chord(self, d, t):
        from . import chords
        line = self.chords
        k = chords.at(line, t)
        if k < 0:
            return
        unit = min(self.W, self.H)
        x = int(unit * 0.055)
        y = int(unit * 0.045 + (self.f_title.size * 1.6 if self.title else 0))
        g = ease_out((t - line[k][0]) / 0.25)
        dy = (1 - g) * self.f_chord.size * 0.35
        name = line[k][1]
        o = max(2, int(self.f_chord.size * 0.045))
        d.text((x + o, y + dy + o), name, font=self.f_chord, fill=self.pal["right"] + (int(220 * g),),
               stroke_width=max(2, self.f_chord.size // 16), stroke_fill=self.c_paper + (int(200 * g),))
        d.text((x, y + dy), name, font=self.f_chord, fill=self.pal["left"] + (int(240 * g),))
        if k + 1 < len(line):
            nxt_t, nxt = line[k + 1]
            soon = nxt_t - t
            if soon < self.lookahead * 0.7:
                a = int(170 * ease_out((self.lookahead * 0.7 - soon) / 0.3))
                tw = d.textlength(name, font=self.f_chord)
                d.text((x + tw + self.f_chord.size * 0.35, y + self.f_chord.size * 0.32),
                       "then " + nxt, font=self.f_next, fill=self.pal["right"] + (a,),
                       stroke_width=max(2, self.f_next.size // 10), stroke_fill=self.c_paper + (a,))


# 4. Moonlit ink ---------------------------------------------------------------

class MoonlitRenderer(LookRenderer):
    TITLE_FONT = ("DMSerifDisplay-Italic.ttf", None)
    CHORD_FONT = ("DMSerifDisplay-Italic.ttf", None)
    LABEL_FONT = ("Caveat.ttf", "Bold")
    KEY_FONT = ("Caveat.ttf", "Bold")
    key_line = (40, 44, 72)
    key_line_a = 220
    key_lw = 0.035
    key_wob = 0.35
    black_line = (40, 44, 72)
    black_hi = (120, 128, 170, 160)
    hit_line = (240, 214, 150, 255)
    label_col = (32, 34, 58)

    def _page(self, rng):
        W, H = self.W, self.H
        img = grain_page(W, H, (22, 26, 48), (34, 36, 62), rng, fine=1.2, coarse=0.05,
                         vignette=0.4, edge=(14, 16, 32))
        arr = np.asarray(img, np.float32)
        # a soft moon glow up in the corner
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        cx, cy = W * 0.84, H * 0.16
        dd = np.hypot(xx - cx, yy - cy) / (min(W, H) * 0.55)
        glow = np.clip(1 - dd, 0, 1) ** 2.2 * 0.22
        arr = arr * (1 - glow[..., None]) + np.array((120, 120, 170), np.float32) * glow[..., None]
        img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
        d = ImageDraw.Draw(img, "RGBA")
        r = min(W, H) * 0.045
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(244, 232, 200, 235))
        d.ellipse([cx - r * 0.55, cy - r * 1.15, cx + r * 1.4, cy + r * 0.8], fill=(0, 0, 0, 0))
        # cut the crescent with the page colour
        page = tuple(int(v) for v in arr[int(cy), int(cx - r * 2)])
        d.ellipse([cx - r * 0.45, cy - r * 1.1, cx + r * 1.45, cy + r * 0.75], fill=page + (255,))
        for _ in range(int(W * self.kb_top / 5200)):
            x, y = rng.random() * W, rng.random() * self.kb_top * 0.9
            s = rng.random()
            rr = 0.5 + s * 1.3
            d.ellipse([x - rr, y - rr, x + rr, y + rr], fill=(240, 230, 210, int(60 + 150 * s * s)))
        # a few drawn four point stars
        for _ in range(7):
            x, y = rng.random() * W, rng.random() * self.kb_top * 0.6
            while x < W * 0.3 and y < H * 0.32:
                x, y = rng.random() * W, rng.random() * self.kb_top * 0.6
            s = self.ww * (0.15 + 0.2 * rng.random())
            lw = max(1, int(self.ww * 0.035))
            d.line([x - s, y, x + s, y], fill=(240, 222, 170, 170), width=lw)
            d.line([x, y - s, x, y + s], fill=(240, 222, 170, 170), width=lw)
        return img

    def _pad(self, w):
        return max(4, int(w * 0.3))

    def _block(self, w, h, pad, right, playing, black, rng, vel):
        Wc, Hc = (w + 2 * pad) * SS, (h + 2 * pad) * SS
        x0, y0, x1, y1 = pad * SS, pad * SS, (pad + w) * SS, (pad + h) * SS
        r = min(w * 0.3, h * 0.45) * SS
        col = np.array(self._colour(right, playing), np.float32)
        if black:
            col = col * 0.9
        pts = wobble(round_rect_pts(x0, y0, x1, y1, r, 10 * SS), SS * 0.45, rng.random() * 6)
        m = Image.new("L", (Wc, Hc), 0)
        ImageDraw.Draw(m).polygon(pts, fill=255)
        mask = np.asarray(m, np.float32) / 255
        yy = np.arange(Hc, dtype=np.float32)[:, None]
        # lighter at the bottom where it meets the keys
        f = np.clip((yy - y0) / max(1, y1 - y0), 0, 1)[..., None]
        rgb = col * (0.82 + 0.18 * f) + np.zeros((1, Wc, 1), np.float32)
        chalk = rng.normal(0, 1, (Hc, Wc)).astype(np.float32)
        a = mask * np.clip(0.92 + chalk * 0.05, 0, 1)
        out = Image.fromarray(np.dstack([np.clip(rgb, 0, 255), a * 255]).astype(np.uint8), "RGBA")
        if playing:
            glow = m.filter(ImageFilter.GaussianBlur(w * SS * 0.18)).point(lambda v: int(v * 0.8))
            g = Image.new("RGBA", (Wc, Hc), tuple(int(v) for v in col) + (0,))
            g.putalpha(glow)
            g.alpha_composite(out)
            out = g
        top = Image.new("RGBA", (Wc, Hc), (0, 0, 0, 0))
        d = ImageDraw.Draw(top)
        lw = max(2, int(w * 0.06 * SS))
        if h > w * 0.9:
            d.line([(x0 + w * SS * 0.24, y0 + r), (x0 + w * SS * 0.24, y1 - r)],
                   fill=(255, 255, 255, 70), width=max(1, int(w * SS * 0.08)))
        d.line(pts + [pts[0]], fill=(250, 240, 214, 230), width=lw, joint="curve")
        out.alpha_composite(top)
        return out

    def _draw_marks(self, img, d, marks):
        ww, top = self.ww, self.kb_top
        lw = max(1, int(ww * 0.045))
        for cx, w, age, vel in marks:
            f = age / 0.3
            a = int(230 * (1 - f))
            for ang in (-150, -115, -65, -30):
                ra = math.radians(ang)
                r0 = w * 0.55 + ww * 0.15 * ease_out(f)
                ln = ww * (0.25 + 0.35 * ease_out(f))
                sx, sy = cx + math.cos(ra) * r0, top + math.sin(ra) * r0 * 0.7
                d.line([sx, sy, sx + math.cos(ra) * ln * 0.5, sy + math.sin(ra) * ln * 0.5],
                       fill=(244, 222, 160, a), width=lw)


LOOKS = {
    "watercolour": WatercolourRenderer,
    "washi": WashiRenderer,
    "riso": RisoRenderer,
    "moonlit": MoonlitRenderer,
}
