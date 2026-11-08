"""Colour palettes."""

THEMES = {
    "default": {
        "bg_top": (8, 10, 18),
        "bg_bottom": (16, 20, 34),
        "panel": (10, 10, 14),
        "panel_lip": (24, 24, 30),
        "white": (238, 238, 242),
        "white_shade": (206, 208, 216),
        "white_edge": (170, 172, 182),
        "black": (26, 26, 32),
        "black_lit": (62, 62, 74),
        "right": (86, 226, 168),
        "right_hi": (156, 255, 212),
        "left": (92, 160, 255),
        "left_hi": (156, 204, 255),
        "label": (150, 154, 168),
        "text": (235, 238, 245),
        "track": (30, 34, 48),
    },
    "sunset": {
        "bg_top": (20, 8, 16),
        "bg_bottom": (44, 16, 24),
        "panel": (16, 9, 12),
        "panel_lip": (38, 20, 26),
        "white": (250, 240, 236),
        "white_shade": (222, 205, 200),
        "white_edge": (186, 160, 156),
        "black": (28, 18, 22),
        "black_lit": (74, 46, 52),
        "right": (255, 138, 92),
        "right_hi": (255, 205, 160),
        "left": (232, 84, 132),
        "left_hi": (255, 168, 196),
        "label": (176, 150, 148),
        "text": (255, 242, 236),
        "track": (56, 26, 34),
    },
    "ocean": {
        "bg_top": (4, 14, 22),
        "bg_bottom": (6, 30, 46),
        "panel": (4, 10, 14),
        "panel_lip": (14, 30, 40),
        "white": (232, 244, 250),
        "white_shade": (196, 216, 228),
        "white_edge": (158, 182, 196),
        "black": (14, 28, 38),
        "black_lit": (40, 70, 88),
        "right": (94, 234, 255),
        "right_hi": (190, 250, 255),
        "left": (116, 130, 255),
        "left_hi": (180, 190, 255),
        "label": (140, 168, 184),
        "text": (232, 246, 252),
        "track": (18, 44, 60),
    },
}

DEFAULT_THEME = "default"


def get(name):
    try:
        return THEMES[name]
    except KeyError:
        raise SystemExit(
            "unknown theme %r, pick one of: %s" % (name, ", ".join(THEMES))
        )
