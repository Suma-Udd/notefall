"""The NoteFall icon, drawn in code so there's no binary asset to keep in sync."""

from PIL import Image, ImageDraw, ImageFilter


def draw_icon(size=512):
    s = size
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    bg = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(bg)
    d.rounded_rectangle([0, 0, s - 1, s - 1], radius=int(s * 0.22), fill=(12, 16, 30, 255))
    img.alpha_composite(bg)

    glow = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    g = ImageDraw.Draw(glow)
    kb_top = int(s * 0.66)
    blocks = [
        (0.20, 0.30, 0.18, 0.62, (88, 150, 255)),
        (0.455, 0.545, 0.30, 0.66, (72, 222, 160)),
        (0.64, 0.74, 0.10, 0.48, (72, 222, 160)),
    ]
    for x0, x1, y0, y1, col in blocks:
        g.rounded_rectangle([x0 * s, y0 * s, x1 * s, y1 * s], radius=int(s * 0.03), fill=col + (255,))
    halo = glow.filter(ImageFilter.GaussianBlur(s * 0.035))
    img.alpha_composite(halo)
    img.alpha_composite(glow)

    d = ImageDraw.Draw(img)
    inset = int(s * 0.12)
    keys = 7
    kw = (s - 2 * inset) / keys
    for i in range(keys):
        x0 = inset + i * kw
        lit = i == 3
        d.rectangle([x0 + s * 0.006, kb_top, x0 + kw - s * 0.006, s * 0.86],
                    fill=(170, 255, 214, 255) if lit else (240, 240, 246, 255))
    for i in (0, 1, 3, 4, 5):
        cx = inset + (i + 1) * kw
        d.rectangle([cx - kw * 0.3, kb_top, cx + kw * 0.3, kb_top + (s * 0.86 - kb_top) * 0.6],
                    fill=(22, 22, 28, 255))
    d.rectangle([inset, kb_top - s * 0.012, s - inset, kb_top], fill=(200, 60, 70, 255))
    return img


def save_icons(prefix):
    """Write prefix.png, prefix.ico and prefix.icns."""
    big = draw_icon(1024)
    big.resize((512, 512), Image.LANCZOS).save(prefix + ".png")
    big.save(prefix + ".ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
                                     (128, 128), (256, 256)])
    try:
        big.save(prefix + ".icns")
    except Exception:  # pragma: no cover - only matters on the mac build
        pass


if __name__ == "__main__":  # pragma: no cover
    import sys

    save_icons(sys.argv[1] if len(sys.argv) > 1 else "notefall-icon")
