"""Chord names from the notes, for the chord label in the Paper look.

This doesn't try to be a music theory engine. It looks at what is sounding
around each new note, scores the common chord shapes against it and keeps a
name only once it has lasted long enough to read. Arpeggios work because
the window looks a little ahead and behind, and the bass note breaks ties
("C/E" style slash chords are left out on purpose, they're hard to read
while a video is moving).
"""

from .keyboard import NOTE_NAMES

# suffix, intervals from the root. Simple shapes first so they win ties.
SHAPES = (
    ("", (0, 4, 7)),
    ("m", (0, 3, 7)),
    ("7", (0, 4, 7, 10)),
    ("maj7", (0, 4, 7, 11)),
    ("m7", (0, 3, 7, 10)),
    ("sus4", (0, 5, 7)),
    ("sus2", (0, 2, 7)),
    ("dim", (0, 3, 6)),
    ("aug", (0, 4, 8)),
    ("6", (0, 4, 7, 9)),
    ("m6", (0, 3, 7, 9)),
    ("m7b5", (0, 3, 6, 10)),
    ("dim7", (0, 3, 6, 9)),
)

BEHIND = 0.3
AHEAD = 0.6
MIN_HOLD = 1.0
CLUSTER = 0.05


def name(weights, bass=None):
    """Best chord name for {pitch_class: weight}, or None if it isn't a chord."""
    pcs = {pc for pc, w in weights.items() if w > 0}
    if len(pcs) < 3:
        return None
    total = sum(weights.values())
    best, best_score = None, 0.0
    for root in pcs:
        for k, (suffix, shape) in enumerate(SHAPES):
            tones = {(root + i) % 12 for i in shape}
            # every tone has to be there, except the fifth which is often left out
            missing = [i for i in shape if (root + i) % 12 not in pcs and i != 7]
            if missing:
                continue
            inside = sum(weights.get(pc, 0.0) for pc in tones)
            outside = total - inside
            score = (inside - 1.5 * outside) / total - 0.02 * k - 0.03 * len(shape)
            if bass is not None and bass == root:
                score += 0.12
            if score > best_score:
                best, best_score = NOTE_NAMES[root] + suffix, score
    return best


def timeline(notes):
    """[(time, name)] for each chord change. `notes` are (start, end, pitch, ...)."""
    if not notes:
        return []
    notes = sorted(notes, key=lambda n: n[0])
    onsets = []
    for n in notes:
        if not onsets or n[0] - onsets[-1] > CLUSTER:
            onsets.append(n[0])

    labels = []
    j0 = 0
    for t in onsets:
        a, b = t - BEHIND, t + AHEAD
        while j0 < len(notes) and notes[j0][1] < a - 30:
            j0 += 1
        weights, low = {}, None
        for n in notes[j0:]:
            if n[0] > b:
                break
            s, e, p = n[0], n[1], n[2]
            overlap = min(e, b) - max(s, a)
            if overlap <= 0:
                continue
            # notes from before only count if they keep ringing, and for less than fresh ones
            if s < a:
                if e <= t + 0.05:
                    continue
                overlap *= 0.4
            weights[p % 12] = weights.get(p % 12, 0.0) + overlap
            if low is None or p < low:
                low = p
        labels.append((t, name(weights, None if low is None else low % 12)))

    # glue runs of the same name together, a missing name keeps the last one
    runs = []
    for t, label in labels:
        if label is None or (runs and runs[-1][1] == label):
            continue
        runs.append([t, label])
    # names that flash past are hard to read: fold the shortest away until none are left
    end = max(n[1] for n in notes)
    while len(runs) > 1:
        lens = [(runs[k + 1][0] if k + 1 < len(runs) else end) - runs[k][0] for k in range(len(runs))]
        k = min(range(len(runs)), key=lambda k: lens[k])
        if lens[k] >= MIN_HOLD:
            break
        if k == 0:
            runs[1][0] = runs[0][0]
        del runs[k]
        if 0 < k < len(runs) and runs[k - 1][1] == runs[k][1]:
            del runs[k]
    return [(t, label) for t, label in runs]


def at(line, t):
    """Index of the chord sounding at `t` in a timeline, or -1 before the first."""
    lo, hi = 0, len(line)
    while lo < hi:
        mid = (lo + hi) // 2
        if line[mid][0] <= t:
            lo = mid + 1
        else:
            hi = mid
    return lo - 1
