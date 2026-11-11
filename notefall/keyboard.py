"""Keyboard geometry and hand assignment.

Everything that positions a key or a note block comes from one mapping:
`pitch -> (x0, x1, is_black)`. Keys and blocks both read it, so alignment
can never drift.
"""

import numpy as np

SEMITONES = (0, 2, 4, 5, 7, 9, 11)
BLACK = frozenset((1, 3, 6, 8, 10))

# full piano range
A0, C8 = 21, 108

# Real pianos don't centre black keys on the gap. C# and F# sit a bit left,
# D# and A# a bit right. Fractions of the black key width.
BLACK_OFFSET = {1: -0.12, 3: 0.12, 6: -0.15, 8: 0.0, 10: 0.15}

NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


def note_name(pitch):
    return "%s%d" % (NOTE_NAMES[pitch % 12], pitch // 12 - 1)


def parse_note(text):
    """'C4' -> 60, 'F#3' -> 54, 'Bb2' -> 46, '60' -> 60."""
    s = str(text).strip()
    if s.lstrip("-").isdigit():
        return int(s)
    s = s[0].upper() + s[1:]
    flats = {"Db": "C#", "Eb": "D#", "Gb": "F#", "Ab": "G#", "Bb": "A#"}
    for flat, sharp in flats.items():
        if s.startswith(flat):
            s = sharp + s[2:]
    name = s[:2] if len(s) > 1 and s[1] == "#" else s[:1]
    if name not in NOTE_NAMES:
        raise ValueError("not a note name: %r" % text)
    octave = int(s[len(name):])
    return NOTE_NAMES.index(name) + (octave + 1) * 12


def white_keys(lo, hi):
    return [p for p in range(lo, hi + 1) if p % 12 in SEMITONES]


def snap_range(pitches, pad=2, lo=A0, hi=C8, min_white=15):
    """Crop the drawn keyboard to the pitches actually played.

    An 88 key board across 1080 px gives 20 px white keys, which is
    unreadable on a phone. Cropping to the used range plus a small margin
    makes blocks 2 to 4 times wider. Both ends snap outwards to a white
    key so the board never starts or ends on half a black key. Very
    narrow songs are widened to at least `min_white` white keys so a
    three note melody doesn't get keys the size of a door.
    """
    low = max(lo, min(pitches) - pad)
    high = min(hi, max(pitches) + pad)

    while len(white_keys(low, high)) < min_white and (low > lo or high < hi):
        if low > lo:
            low -= 1
        if high < hi and len(white_keys(low, high)) < min_white:
            high += 1

    while low > lo and low % 12 not in SEMITONES:
        low -= 1
    while high < hi and high % 12 not in SEMITONES:
        high += 1
    return low, high


def build_keys(x0, x1, lo, hi, black_ratio=0.6):
    """Return (geometry, white_key_width, white_key_pitches)."""
    whites = white_keys(lo, hi)
    ww = (x1 - x0) / len(whites)
    bw = ww * black_ratio

    geo = {}
    for i, pitch in enumerate(whites):
        geo[pitch] = (x0 + i * ww, x0 + (i + 1) * ww, False)
    for i, pitch in enumerate(whites):
        black = pitch + 1
        if black % 12 in BLACK and black <= hi and i < len(whites) - 1:
            cx = x0 + (i + 1) * ww + BLACK_OFFSET[black % 12] * bw
            geo[black] = (cx - bw / 2, cx + bw / 2, True)
    return geo, ww, whites


LEFT_NAMES = ("left", "lh", "l.h", "bass", "links", "gauche", "sinistra", "izquierda")
RIGHT_NAMES = ("right", "rh", "r.h", "treble", "melody", "rechts", "droite", "destra", "derecha")


def _named_hand(name):
    n = (name or "").strip().lower()
    if any(word == n or n.startswith(word + " ") or (" " + word) in n for word in LEFT_NAMES):
        return False
    if any(word == n or n.startswith(word + " ") or (" " + word) in n for word in RIGHT_NAMES):
        return True
    return None


def split_by_instrument(instruments):
    """Map id(instrument) -> True for the right hand, or None if unsure.

    Track names win when they say "left"/"right"/"bass"/"treble". Otherwise
    two tracks is the normal case for a piano MIDI and the one with the
    higher mean pitch is the right hand. Anything else returns None, which
    tells the caller to fall back to a pitch split.
    """
    real = [ins for ins in instruments if not ins.is_drum and ins.notes]
    if not real:
        return None

    named = {id(ins): _named_hand(getattr(ins, "name", "")) for ins in real}
    if all(v is not None for v in named.values()) and len(set(named.values())) == 2:
        return named

    if len(real) != 2:
        return None
    means = sorted((sum(n.pitch for n in ins.notes) / len(ins.notes), i)
                   for i, ins in enumerate(real))
    return {id(real[means[-1][1]]): True, id(real[means[0][1]]): False}


def percentile_split(notes, frac=0.42, lo=55, hi=64):
    """Pitch above which a note counts as the right hand.

    Starts from a low percentile of the played pitches (most piano music
    has more right hand notes) and clamps it near middle C so a melody-only
    song doesn't get half its notes painted blue.
    """
    pitches = sorted(n[2] for n in notes)
    if not pitches:
        return 60
    return min(hi, max(lo, pitches[int(len(pitches) * frac)]))


def hand_split(notes, chord=0.04, reach=11, window=1.0, near=0.4):
    """Which hand plays each note, for music that doesn't say: [True for the right hand].

    `notes` are (start, end, pitch, ...) sorted by start. One fixed split
    pitch gets about 85% of notes right on real piano music, because both
    hands wander. Here the split point moves with the music: at every chord
    it wants to sit in the gap between what the two hands just played, it
    is pushed away from a place that would make one hand stretch more than
    `reach` semitones within a moment, and it doesn't like to jump. The best
    path through the whole piece is found in one pass (Viterbi). That gets
    about 92% right on 311 classical pieces with the hands written out.
    """
    n = len(notes)
    if n == 0:
        return []
    st = np.array([x[0] for x in notes], dtype=float)
    pt = np.array([x[2] for x in notes], dtype=int)
    gid = np.zeros(n, int)          # notes struck together are one chord
    g, g0 = 0, st[0]
    for i in range(1, n):
        if st[i] - g0 > chord:
            g, g0 = g + 1, st[i]
        gid[i] = g
    gt = st[np.r_[0, np.nonzero(np.diff(gid))[0] + 1]]
    G = len(gt)

    cuts = np.arange(28, 97)        # the right hand is every pitch >= cut
    kernel = np.exp(-np.abs(np.arange(128)[None, :] - cuts[:, None] + 0.5) / 2.0)
    cost = np.tile(0.002 * (cuts - 60.0) ** 2, (G, 1))   # all else equal, near middle C
    a, b = np.searchsorted(st, gt - window), np.searchsorted(st, gt + window)
    c, d = np.searchsorted(st, gt - near), np.searchsorted(st, gt + near)
    for k in range(G):
        w = 1 - np.abs(st[a[k]:b[k]] - gt[k]) / window
        hist = np.bincount(pt[a[k]:b[k]], weights=w, minlength=128)[:128]
        cost[k] += 2.0 * (kernel @ hist) / max(1.0, w.sum())   # stay out of the notes
        q = np.sort(pt[c[k]:d[k]])
        if len(q) > 1:
            i = np.searchsorted(q, cuts)
            right = np.where(i < len(q), q[-1] - q[np.minimum(i, len(q) - 1)], 0)
            left = np.where(i > 0, q[np.maximum(i - 1, 0)] - q[0], 0)
            cost[k] += 1.2 * (np.maximum(0, right - reach) + np.maximum(0, left - reach))

    jump = np.abs(cuts[:, None] - cuts[None, :]).astype(float)
    back = np.zeros((G, len(cuts)), np.int16)
    acc = cost[0].copy()
    for k in range(1, G):
        step = acc[None, :] + jump / (1 + 2 * (gt[k] - gt[k - 1]))
        back[k] = step.argmin(1)
        acc = step.min(1) + cost[k]
    path = np.zeros(G, int)
    path[-1] = acc.argmin()
    for k in range(G - 1, 0, -1):
        path[k - 1] = back[k, path[k]]
    return (pt >= cuts[path][gid]).tolist()


def pedal_intervals(instruments, threshold=64):
    """[(down, up)] times the sustain pedal (CC 64) is held, merged across tracks."""
    spans = []
    for ins in instruments:
        if ins.is_drum:
            continue
        down = None
        for cc in sorted(ins.control_changes, key=lambda c: c.time):
            if cc.number != 64:
                continue
            if cc.value >= threshold and down is None:
                down = cc.time
            elif cc.value < threshold and down is not None:
                spans.append((down, cc.time))
                down = None
        if down is not None:
            end = max((n.end for n in ins.notes), default=down) + 0.5
            spans.append((down, max(end, down)))
    spans.sort()
    merged = []
    for s, e in spans:
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


def sustained_end(end, pedal):
    """When a note actually stops sounding: at key release, or later if the pedal is down."""
    for s, e in pedal:
        if s <= end < e:
            return e
        if s > end:
            break
    return end
