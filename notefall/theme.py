"""Colour palettes.

Each theme only needs a handful of colours. Anything missing is filled in
from the default theme, so adding a palette is five lines.
"""

from . import media

THEMES = {
    "default": {
        "label": "Midnight (green and blue)",
        "bg_top": (6, 8, 16),
        "bg_bottom": (18, 22, 38),
        "right": (72, 222, 160),
        "right_hi": (170, 255, 214),
        "left": (88, 150, 255),
        "left_hi": (170, 206, 255),
        "accent": (120, 200, 255),
    },
    "sunset": {
        "label": "Sunset (orange and pink)",
        "bg_top": (18, 6, 16),
        "bg_bottom": (46, 14, 30),
        "right": (255, 140, 80),
        "right_hi": (255, 214, 168),
        "left": (236, 72, 136),
        "left_hi": (255, 172, 204),
        "accent": (255, 150, 120),
        "felt": (90, 24, 40),
    },
    "ocean": {
        "label": "Ocean (cyan and violet)",
        "bg_top": (2, 12, 22),
        "bg_bottom": (4, 32, 50),
        "right": (70, 228, 255),
        "right_hi": (196, 250, 255),
        "left": (120, 120, 255),
        "left_hi": (190, 190, 255),
        "accent": (80, 220, 255),
        "felt": (10, 46, 70),
    },
    "neon": {
        "label": "Neon (pink and cyan)",
        "bg_top": (8, 2, 18),
        "bg_bottom": (22, 6, 40),
        "right": (255, 64, 200),
        "right_hi": (255, 180, 236),
        "left": (40, 230, 255),
        "left_hi": (180, 246, 255),
        "accent": (255, 80, 220),
        "felt": (60, 10, 70),
    },
    "gold": {
        "label": "Gold (warm and elegant)",
        "bg_top": (10, 8, 6),
        "bg_bottom": (28, 22, 14),
        "right": (255, 200, 90),
        "right_hi": (255, 236, 180),
        "left": (210, 140, 70),
        "left_hi": (246, 200, 150),
        "accent": (255, 210, 120),
        "felt": (70, 40, 16),
    },
    "paper": {
        "label": "Paper (sketchbook with hands)",
        "style": "paper",
        "bg_top": (240, 235, 224),
        "bg_bottom": (226, 218, 203),
        "right": (232, 158, 138),
        "right_hi": (238, 118, 92),
        "left": (146, 176, 212),
        "left_hi": (96, 140, 214),
        "accent": (52, 42, 38),
        "text": (52, 42, 38),
    },
}

_BASE = {
    "style": "glow",
    "panel": (8, 8, 12),
    "felt": (110, 20, 28),
    "white": (242, 242, 246),
    "white_bottom": (214, 216, 224),
    "white_gap": (40, 42, 52),
    "black": (22, 22, 28),
    "black_top": (58, 58, 70),
    "key_label": (140, 144, 160),
    "lane": (255, 255, 255),
    "text": (236, 240, 248),
    "track": (34, 38, 54),
}

DEFAULT_THEME = "default"


def get(name):
    try:
        pal = dict(_BASE)
        pal.update(THEMES[name])
        return pal
    except KeyError:
        raise media.NotefallError(
            "unknown theme %r, pick one of: %s" % (name, ", ".join(THEMES))
        )
