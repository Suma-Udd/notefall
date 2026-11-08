"""Keyboard geometry.

Everything that positions a key or a note block comes from one mapping:
`pitch -> (x0, x1, is_black)`. Keys and blocks both read it, so alignment
can never drift.
"""

SEMITONES = (0, 2, 4, 5, 7, 9, 11)
BLACK = frozenset((1, 3, 6, 8, 10))

# full piano range
A0, C8 = 21, 108


def white_keys(lo, hi):
    return [p for p in range(lo, hi + 1) if p % 12 in SEMITONES]


def snap_range(pitches, pad=4, lo=A0, hi=C8):
    """Crop the drawn keyboard to the pitches actually played.

    An 88 key board across 1080 px gives 20 px white keys, which is
    unreadable on a phone. Cropping to the used range plus a small margin
    makes blocks 2 to 4 times wider. The low end snaps down to a white key,
    the high end snaps up to a C so the octave labels stay honest.
    """
    low = max(lo, min(pitches) - pad)
    high = min(hi, max(pitches) + pad)

    while low > lo and low % 12 not in SEMITONES:
        low -= 1
    while high < hi and (high % 12 != 0):
        high += 1
    return low, high


def build_keys(width, x0, x1, lo, hi):
    """Return (geometry, white_key_width, white_key_pitches)."""
    whites = white_keys(lo, hi)
    ww = (x1 - x0) / len(whites)
    bw = ww * 0.62

    geo = {}
    for i, pitch in enumerate(whites):
        geo[pitch] = (x0 + i * ww, x0 + (i + 1) * ww, False)
    for i, pitch in enumerate(whites):
        if (pitch + 1) % 12 in BLACK and i < len(whites) - 1:
            cx = x0 + (i + 1) * ww
            geo[pitch + 1] = (cx - bw / 2, cx + bw / 2, True)
    return geo, ww, whites


def split_by_instrument(instruments):
    """Map id(instrument) -> True for the right hand.

    Two tracks is the normal case for a piano MIDI: the one with the higher
    mean pitch is the right hand. Returns None when this cannot be decided,
    which tells the caller to fall back to a pitch threshold.
    """
    real = [ins for ins in instruments if not ins.is_drum and ins.notes]
    if len(real) != 2:
        return None
    means = [(sum(n.pitch for n in ins.notes) / len(ins.notes), id(ins)) for ins in real]
    means.sort()
    return {means[-1][1]: True, means[0][1]: False}


def percentile_split(notes, frac=0.42):
    """Pitch above which a note counts as the right hand."""
    pitches = sorted(n[2] for n in notes)
    if not pitches:
        return 0
    return pitches[int(len(pitches) * frac)]
