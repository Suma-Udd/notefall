"""Draw the little picture of each look that the app's look picker shows.

Run again after adding or changing a look:  python scripts/make_look_thumbs.py
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PIL import Image  # noqa: E402

from notefall import render, theme  # noqa: E402

OUT = os.path.join(ROOT, "notefall", "assets", "looks")
SONG = os.path.join(ROOT, "examples", "prelude_in_c.mid")


def main():
    os.makedirs(OUT, exist_ok=True)
    for name in theme.THEMES:
        # a tall frame, so the keys and the hands are big enough to read in a small tile
        W, H = 640, 860
        img = render.preview(SONG, W, H, theme_name=name, at=30.2, hands=True)
        w, h = 330, 510
        x = int(W * 0.47 - w / 2)
        img = img.crop((x, H - 8 - h, x + w, H - 8)).resize((176, 272), Image.LANCZOS)
        img.save(os.path.join(OUT, name + ".png"), optimize=True)
        print(name)


if __name__ == "__main__":
    main()
