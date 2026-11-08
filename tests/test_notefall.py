import os
import subprocess
import sys

import pretty_midi
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from notefall import keyboard, render  # noqa: E402


def test_snap_range_crops_and_lands_on_white_and_c():
    lo, hi = keyboard.snap_range([60, 64, 67])
    assert lo <= 60 and lo % 12 in keyboard.SEMITONES
    assert hi >= 67 and hi % 12 == 0


def test_snap_range_never_leaves_the_piano():
    lo, hi = keyboard.snap_range([21, 108], pad=40)
    assert lo >= keyboard.A0 and hi <= keyboard.C8


def test_keyboard_covers_every_black_and_white_key():
    geo, ww, whites = keyboard.build_keys(1080, 0, 1080, 48, 72)
    for pitch in range(48, 73):
        assert pitch in geo, "missing pitch %d" % pitch
    for pitch in whites:
        x0, x1, is_black = geo[pitch]
        assert not is_black and x1 > x0
    assert ww > 0


def test_black_keys_sit_between_white_keys():
    geo, _, _ = keyboard.build_keys(1080, 0, 1080, 48, 72)
    c4 = geo[60]
    c4_sharp = geo[61]
    assert c4[0] < c4_sharp[0] < c4[1]
    assert c4_sharp[2] is True


def test_hand_split_follows_instrument_not_pitch():
    class FakeNote:
        def __init__(self, pitch):
            self.pitch = pitch

    class FakeInstrument:
        is_drum = False

        def __init__(self, pitches):
            self.notes = [FakeNote(p) for p in pitches]

    # deliberately give the right hand a low note: pitch thresholds get this wrong
    right = FakeInstrument([50, 72, 74, 76])
    left = FakeInstrument([36, 40, 43])
    mapping = keyboard.split_by_instrument([right, left])
    assert mapping[id(right)] is True
    assert mapping[id(left)] is False


def test_hand_split_gives_up_on_three_tracks():
    class FakeNote:
        def __init__(self, pitch):
            self.pitch = pitch

    class FakeInstrument:
        is_drum = False

        def __init__(self, pitches):
            self.notes = [FakeNote(p) for p in pitches]

    ins = [FakeInstrument([60]), FakeInstrument([64]), FakeInstrument([67])]
    assert keyboard.split_by_instrument(ins) is None


@pytest.fixture()
def tiny_midi(tmp_path):
    pm = pretty_midi.PrettyMIDI(initial_tempo=120)
    piano = pretty_midi.Instrument(program=0)
    for i, pitch in enumerate([60, 62, 64]):
        piano.notes.append(pretty_midi.Note(velocity=90, pitch=pitch,
                                            start=i * 0.25, end=i * 0.25 + 0.2))
    pm.instruments.append(piano)
    path = tmp_path / "tiny.mid"
    pm.write(str(path))
    return str(path)


def test_render_produces_an_mp4(tiny_midi, tmp_path):
    out = tmp_path / "out.mp4"
    render.render(tiny_midi, str(out), width=270, height=480, fps=10, lookahead=1.5)
    assert out.exists() and out.stat().st_size > 1000


def test_render_muxes_audio(tiny_midi, tmp_path):
    from notefall.synth import synth

    wav = tmp_path / "a.wav"
    synth(tiny_midi, str(wav))
    out = tmp_path / "out_audio.mp4"
    render.render(tiny_midi, str(out), width=270, height=480, fps=10,
                  lookahead=1.5, audio=str(wav))
    assert out.exists()
    probe = subprocess.run(
        [render.ffprobe_bin(), "-v", "error", "-select_streams", "a",
         "-show_entries", "stream=codec_name", "-of", "csv=p=0", str(out)],
        capture_output=True, text=True,
    ).stdout.strip()
    assert probe == "aac"
