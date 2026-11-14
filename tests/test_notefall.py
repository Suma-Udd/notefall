import os
import sys
import threading

import pretty_midi
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from notefall import chords, cli, hands, keyboard, media, piano, render, synth, theme, transcribe  # noqa: E402


class FakeNote:
    def __init__(self, pitch):
        self.pitch = pitch


class FakeInstrument:
    is_drum = False

    def __init__(self, pitches, name=""):
        self.notes = [FakeNote(p) for p in pitches]
        self.name = name


# keyboard ------------------------------------------------------------------

def test_snap_range_crops_and_lands_on_white_keys():
    lo, hi = keyboard.snap_range([60, 64, 67], min_white=1)
    assert lo <= 60 and lo % 12 in keyboard.SEMITONES
    assert hi >= 67 and hi % 12 in keyboard.SEMITONES


def test_snap_range_widens_tiny_songs():
    lo, hi = keyboard.snap_range([60, 62], min_white=15)
    assert len(keyboard.white_keys(lo, hi)) >= 15


def test_snap_range_never_leaves_the_piano():
    lo, hi = keyboard.snap_range([21, 108], pad=40)
    assert lo >= keyboard.A0 and hi <= keyboard.C8


def test_keyboard_covers_every_black_and_white_key():
    geo, ww, whites = keyboard.build_keys(0, 1080, 48, 72)
    for pitch in range(48, 73):
        assert pitch in geo, "missing pitch %d" % pitch
    for pitch in whites:
        x0, x1, is_black = geo[pitch]
        assert not is_black and x1 > x0
    assert ww > 0


def test_black_keys_sit_between_white_keys():
    geo, _, _ = keyboard.build_keys(0, 1080, 48, 72)
    c4, c4_sharp, d4 = geo[60], geo[61], geo[62]
    assert c4[0] < c4_sharp[0] < c4[1] < c4_sharp[1] < d4[1]
    assert c4_sharp[2] is True


def test_parse_note():
    assert keyboard.parse_note("C4") == 60
    assert keyboard.parse_note("c4") == 60
    assert keyboard.parse_note("F#3") == 54
    assert keyboard.parse_note("Bb2") == 46
    assert keyboard.parse_note("72") == 72
    with pytest.raises(ValueError):
        keyboard.parse_note("H2")


def test_hand_split_follows_instrument_not_pitch():
    # deliberately give the right hand a low note: pitch thresholds get this wrong
    right = FakeInstrument([50, 72, 74, 76])
    left = FakeInstrument([36, 40, 43])
    mapping = keyboard.split_by_instrument([right, left])
    assert mapping[id(right)] is True
    assert mapping[id(left)] is False


def test_hand_split_reads_track_names():
    # names beat pitch: here the "left hand" track is actually higher
    a = FakeInstrument([70, 72], name="Left Hand")
    b = FakeInstrument([40, 43], name="Right hand")
    mapping = keyboard.split_by_instrument([a, b])
    assert mapping[id(a)] is False and mapping[id(b)] is True


def test_hand_split_gives_up_on_three_unnamed_tracks():
    ins = [FakeInstrument([60]), FakeInstrument([64]), FakeInstrument([67])]
    assert keyboard.split_by_instrument(ins) is None


# sustain pedal ---------------------------------------------------------------

def _pedal_midi():
    pm = pretty_midi.PrettyMIDI()
    piano = pretty_midi.Instrument(0)
    piano.notes.append(pretty_midi.Note(80, 60, 0.0, 0.3))
    piano.notes.append(pretty_midi.Note(80, 64, 0.5, 0.8))
    piano.notes.append(pretty_midi.Note(80, 60, 1.0, 1.2))  # C struck again while pedal is down
    piano.notes.append(pretty_midi.Note(80, 67, 3.0, 3.2))  # after the pedal lifts
    piano.control_changes += [pretty_midi.ControlChange(64, 127, 0.1),
                              pretty_midi.ControlChange(64, 0, 2.0)]
    pm.instruments.append(piano)
    return pm


def test_pedal_intervals_and_sustained_end():
    pm = _pedal_midi()
    pedal = keyboard.pedal_intervals(pm.instruments)
    assert pedal == [(0.1, 2.0)]
    assert keyboard.sustained_end(0.3, pedal) == 2.0
    assert keyboard.sustained_end(3.2, pedal) == 3.2


def test_blocks_follow_keys_by_default_and_pedal_when_asked():
    pm = _pedal_midi()
    keys = render.collect_notes(pm)
    assert [round(n[1] - n[0], 2) for n in keys] == [0.3, 0.3, 0.2, 0.2]
    ped = render.collect_notes(pm, sustain="pedal")
    by = {(n[0], n[2]): n[1] for n in ped}
    assert by[(0.0, 60)] == pytest.approx(0.99)  # cut by the re-struck C at 1.0
    assert by[(0.5, 64)] == pytest.approx(2.0)   # rings until the pedal lifts
    assert by[(3.0, 67)] == pytest.approx(3.2)   # no pedal, no change


def test_synth_respects_the_pedal(tmp_path):
    import wave

    pm = _pedal_midi()
    loud = tmp_path / "pedal.wav"
    synth.synth(pm, str(loud))
    with wave.open(str(loud)) as w:
        assert w.getnchannels() == 2
        assert w.getnframes() / w.getframerate() > 3.2


# rendering -------------------------------------------------------------------

@pytest.fixture()
def tiny_midi(tmp_path):
    pm = pretty_midi.PrettyMIDI(initial_tempo=120)
    piano = pretty_midi.Instrument(program=0)
    for i, pitch in enumerate([60, 62, 64, 65, 67]):
        piano.notes.append(pretty_midi.Note(velocity=90, pitch=pitch,
                                            start=i * 0.25, end=i * 0.25 + 0.2))
    pm.instruments.append(piano)
    path = tmp_path / "tiny.mid"
    pm.write(str(path))
    return str(path)


def test_every_theme_has_every_colour():
    keys = set(theme.get("default"))
    for name in theme.THEMES:
        assert set(theme.get(name)) == keys
    with pytest.raises(media.NotefallError):
        theme.get("nope")


def test_frames_have_the_right_size():
    pm = _pedal_midi()
    img = render.preview(pm, width=270, height=480)
    assert img.size == (270, 480)
    img = render.preview(pm, width=480, height=270, theme_name="neon", title="hi")
    assert img.size == (480, 270)


# paper look ------------------------------------------------------------------

def test_chord_names():
    assert chords.name({0: 1, 4: 1, 7: 1}, 0) == "C"
    assert chords.name({1: 1, 4: 1, 8: 1}, 1) == "C#m"
    assert chords.name({7: 1, 11: 1, 2: 1, 5: 1}, 7) == "G7"
    assert chords.name({0: 1, 4: 1}) is None


def test_chord_timeline_ignores_flickers():
    def block(t, pitches, d=1.0):
        return [(t, t + d, p, 90, True) for p in pitches]
    notes = block(0, (48, 52, 55)) + block(1.0, (50, 53, 57), 0.1) + block(1.1, (48, 52, 55))
    line = chords.timeline(sorted(notes))
    assert [name for _, name in line] == ["C"]
    notes = block(0, (48, 52, 55)) + block(1.0, (45, 48, 52))
    assert [name for _, name in chords.timeline(sorted(notes))] == ["C", "Am"]
    assert chords.at(line, -1) == -1 and chords.at(line, 0.5) == 0


def test_paper_frames_in_every_format():
    pm = _pedal_midi()
    for with_hands in (True, False):
        for w, h in render.FORMATS.values():
            img = render.preview(pm, width=w // 4, height=h // 4, theme_name="paper", title="hi",
                                 hands=with_hands)
            assert img.size == (w // 4 // 2 * 2, h // 4 // 2 * 2)


def test_hands_press_the_right_keys():
    notes = [(1.0, 1.5, 60, 100, True), (1.0, 1.5, 64, 100, True), (2.0, 2.4, 72, 100, True),
             (1.0, 2.0, 48, 80, False)]
    geo, ww, _ = keyboard.build_keys(0, 1000, 36, 84)
    plan = hands.HandPlan(notes, geo, ww, True, 0, 1000)
    pressed = []
    for f in range(5):
        x, press, _ = plan.finger(f, 1.2, 500)
        if press > 0.5:
            pressed.append(round(x))
    centre = lambda p: round((geo[p][0] + geo[p][1]) / 2)
    assert sorted(pressed) == [centre(60), centre(64)]
    # nothing is pressed between notes, and the hand has moved up for the C5 by the time it plays
    assert all(plan.finger(f, 1.8, 500)[1] < 0.5 for f in range(5))
    assert abs(plan.center(2.0)[0] - plan.center(1.2)[0]) > ww
    assert sum(len(f) for f in hands.HandPlan(notes, geo, ww, False, 0, 1000).fingers) == 1


def test_paper_frames_are_the_same_in_any_order():
    pm = _pedal_midi()
    notes = render.collect_notes(pm)
    r = render.make_renderer(notes, 270, 480, 30, None, theme.get("paper"), None, True, [], True, 3.0)
    a = r.frame(1.0).tobytes()
    r.frame(2.5)
    assert r.frame(1.0).tobytes() == a


def test_render_produces_an_mp4(tiny_midi, tmp_path):
    out = tmp_path / "out.mp4"
    seen = []
    render.render(tiny_midi, str(out), width=270, height=480, fps=10, workers=1,
                  on_progress=seen.append)
    assert out.exists() and out.stat().st_size > 1000
    assert seen and seen[-1] == 1.0
    assert not (tmp_path / "out.mp4.part.mp4").exists()


def test_render_handles_odd_sizes_and_parallel_workers(tiny_midi, tmp_path):
    out = tmp_path / "odd.mp4"
    render.render(tiny_midi, str(out), width=271, height=481, fps=10, workers=2)
    assert out.exists()


def test_render_muxes_audio_with_lead_in(tiny_midi, tmp_path):
    wav = tmp_path / "a.wav"
    synth.synth(tiny_midi, str(wav))
    out = tmp_path / "out_audio.mp4"
    render.render(tiny_midi, str(out), width=270, height=480, fps=10, workers=1,
                  audio=str(wav), lead_in=1.0)
    assert media.has_audio(str(out))
    # notes end at 1.2 s, plus the 1 s lead-in, plus a tail
    assert media.duration(str(out)) > 2.2


def test_render_can_be_cancelled(tiny_midi, tmp_path):
    stop = threading.Event()
    stop.set()
    out = tmp_path / "never.mp4"
    with pytest.raises(media.NotefallError, match="cancelled"):
        render.render(tiny_midi, str(out), width=270, height=480, fps=10, workers=1, cancel=stop)
    assert not out.exists()


def test_empty_midi_is_a_friendly_error(tmp_path):
    pm = pretty_midi.PrettyMIDI()
    pm.instruments.append(pretty_midi.Instrument(0))
    path = tmp_path / "empty.mid"
    pm.write(str(path))
    with pytest.raises(media.NotefallError, match="no piano notes"):
        render.render(str(path), str(tmp_path / "x.mp4"))


# command line ----------------------------------------------------------------

def test_default_output_sits_next_to_the_input():
    out = cli.default_output(os.path.join("songs", "My Song.mid"))
    assert out.endswith(os.path.join("songs", "My Song-notefall.mp4"))


def test_cli_refuses_to_overwrite_the_input(tmp_path):
    rec = tmp_path / "take.mp4"
    rec.write_bytes(b"x")
    args = cli.build_parser().parse_args([str(rec), "-o", str(rec)])
    with pytest.raises(media.NotefallError, match="overwrite"):
        cli.run(args, log=lambda *a: None)


def test_cli_end_to_end(tiny_midi, tmp_path):
    out = tmp_path / "cli.mp4"
    code = cli.main([tiny_midi, "-o", str(out), "--size", "270x480", "--fps", "10",
                     "--theme", "sunset", "--title", "Test", "--workers", "1"])
    assert code == 0 and out.exists()
    assert media.has_audio(str(out))  # MIDI gets a piano track by default


def test_cli_reports_missing_files(tmp_path, capsys):
    assert cli.main([str(tmp_path / "nope.mid")]) == 1
    assert "can't find" in capsys.readouterr().err


# transcription ----------------------------------------------------------------

def test_recording_round_trip(tmp_path):
    """Play a known MIDI with the built-in piano, listen to it, get the notes back."""
    pm = pretty_midi.PrettyMIDI()
    piano = pretty_midi.Instrument(0)
    melody = [60, 64, 67, 72, 67, 64, 62, 65, 69, 74]
    for i, p in enumerate(melody):
        piano.notes.append(pretty_midi.Note(90, p, 0.5 + i * 0.4, 0.5 + i * 0.4 + 0.35))
    pm.instruments.append(piano)
    wav = str(tmp_path / "take.wav")
    synth.synth(pm, wav)

    midi = transcribe.transcribe(wav, midi_out=str(tmp_path / "heard.mid"), engine="basic")
    heard = [(n.start, n.pitch) for i in pretty_midi.PrettyMIDI(midi).instruments for n in i.notes]
    found = sum(any(abs(s - n.start) < 0.06 and p == n.pitch for s, p in heard)
                for n in piano.notes)
    assert found >= len(melody) - 1


def test_decode_matches_scipy_style_peaks():
    import numpy as np

    frames = np.zeros((60, 88))
    onsets = np.zeros((60, 88))
    frames[10:40, 39] = 0.9   # middle C (60 - 21)
    onsets[10, 39] = 0.95
    notes = transcribe.decode_notes(frames, onsets, onset_thresh=0.5, frame_thresh=0.3,
                                    min_note_len=5)
    assert [(n[0], n[1], n[2]) for n in notes] == [(10, 40, 60)]


def _piano_rolls(n=300):
    import numpy as np

    out = {k: np.zeros((n, 88)) for k in piano.OUTPUTS[:4]}
    out.update({k: np.zeros((n, 1)) for k in piano.OUTPUTS[4:]})
    # middle C from 0.5 s to 1.5 s, hit fairly hard
    k = 60 - piano.BEGIN_NOTE
    out["reg_onset_output"][48:53, k] = [0.2, 0.6, 0.9, 0.6, 0.2]
    out["frame_output"][50:150, k] = 0.9
    out["reg_offset_output"][146:155, k] = [0.1, 0.2, 0.4, 0.7, 0.9, 0.7, 0.4, 0.2, 0.1]
    out["velocity_output"][50, k] = 0.7
    # pedal down at 1 s, up at 2 s
    out["pedal_frame_output"][100:200, 0] = 0.9
    out["reg_pedal_offset_output"][196:205, 0] = [0.1, 0.2, 0.4, 0.7, 0.9, 0.7, 0.4, 0.2, 0.1]
    return out


def test_piano_decode_finds_notes_and_pedal():
    notes, pedals = piano.decode(_piano_rolls())
    assert len(notes) == 1
    s, e, p, v = notes[0]
    assert p == 60 and abs(s - 0.5) < 0.02 and abs(e - 1.5) < 0.02 and v == int(0.7 * 128)
    assert len(pedals) == 1 and abs(pedals[0][0] - 1.0) < 0.02 and abs(pedals[0][1] - 2.0) < 0.02


def test_pedalled_notes_are_cut_to_key_length():
    pedal = [(0.0, 4.0)]
    # a run in one hand under the pedal, and a bass note two octaves below it
    notes = [(0.5, 4.0, 60, 80), (1.0, 4.0, 62, 80), (1.5, 4.0, 64, 80), (0.5, 4.0, 36, 80)]
    cut = {n[2]: n for n in piano.key_lengths(notes, pedal)}
    assert abs(cut[60][1] - 1.0) < 1e-6 and abs(cut[62][1] - 1.5) < 1e-6
    assert cut[64][1] == 4.0      # nothing follows it, so it rings on
    assert cut[36][1] == 4.0      # the other hand's notes don't end it
    # a chord struck together stays together, and no pedal means nothing changes
    chord = [(0.5, 3.0, 60, 80), (0.51, 3.0, 64, 80), (1.2, 3.0, 62, 80)]
    ends = [n[1] for n in piano.key_lengths(chord, pedal)]
    assert ends[0] == ends[1] == 1.2
    assert piano.key_lengths(notes, []) == notes


def test_tuning_is_measured_and_quiet_audio_is_levelled():
    import numpy as np

    sr = 16000
    t = np.arange(sr * 4) / sr

    def tone(cents):
        f = [220.0, 277.18, 329.63, 440.0]
        return sum(np.sin(2 * np.pi * x * 2 ** (cents / 1200) * t) for x in f).astype(np.float32) / 8

    for cents in (0, 25, -35):
        got, sure = transcribe.tuning_cents(tone(cents), sr)
        assert abs(got - cents) < 2 and sure > 0.8
    quiet = tone(0) * 0.01
    levelled = transcribe.level(quiet)
    assert 0.05 < float(np.sqrt(np.mean(levelled ** 2))) < 0.09
    assert transcribe.level(np.zeros(1000, np.float32)).max() == 0


def test_live_preview_player(tiny_midi):
    player = render.preview_player(tiny_midi, width=180, height=320)
    assert player.end > player.first >= 0
    a, b = player.frame(player.first), player.frame(player.first + 0.2)
    assert a.size == (180, 320) and a.tobytes() != b.tobytes()


def test_hands_follow_the_music():
    # the left hand climbs above where the right hand started, the right hand stays above it
    notes = []
    for i in range(24):
        t = i * 0.25
        notes.append((t, t + 0.2, 40 + i, 80))          # left hand walking up to 63
        notes.append((t, t + 0.2, 62 + i, 80))          # right hand walking up from 62
    notes.sort(key=lambda n: (n[0], n[2]))
    hands = keyboard.hand_split(notes)
    wrong = sum(h != (p >= 62 + round(t / 0.25)) for (t, _, p, _), h in zip(notes, hands))
    assert wrong <= 2
    assert keyboard.hand_split([]) == []
    # a wide chord can't be one hand
    assert keyboard.hand_split([(0, 1, 48, 80), (0, 1, 55, 80), (0, 1, 72, 80), (0, 1, 79, 80)]) \
        == [False, False, True, True]


def test_recording_midi_has_two_hand_tracks(tmp_path):
    notes = [(i * 0.5, i * 0.5 + 0.4, p, 80) for i in range(8) for p in (43, 72)]
    pm = pretty_midi.PrettyMIDI(transcribe.write_midi(notes, [(0.0, 2.0)], str(tmp_path / "h.mid")))
    assert [i.name for i in pm.instruments] == ["Right hand", "Left hand"]
    assert {n.pitch for n in pm.instruments[0].notes} == {72}
    assert {n.pitch for n in pm.instruments[1].notes} == {43}
    assert keyboard.pedal_intervals(pm.instruments) == [(0.0, 2.0)]
    hands = {n[2]: n[4] for n in render.collect_notes(pm)}
    assert hands == {72: True, 43: False}


def test_end_jingle_is_dropped_but_a_piano_ending_is_not():
    import numpy as np

    sr = 16000
    clock = np.arange(sr * 4) / sr

    def tone(freq, start, length, harmonics):
        on = (clock >= start) & (clock < start + length)
        return sum(a * np.sin(2 * np.pi * freq * h * clock) for h, a in harmonics) * on

    rich = ((1, 1.0), (2, 0.6), (3, 0.4))     # like a string
    beep = ((1, 1.0),)                         # like a synth
    song = [(0.5, 1.5, 60, 80), (1.5, 2.5, 64, 80)]
    body = tone(261.63, 0.5, 1.0, rich) + tone(329.63, 1.5, 1.0, rich)
    jingle = [(2.8, 2.87, 68, 70), (2.9, 2.97, 71, 90), (3.0, 3.07, 75, 90)]
    beeps = sum(tone(440 * 2 ** ((p - 69) / 12), s, 0.15, beep) for s, _, p, _ in jingle)
    audio = (body + beeps).astype(np.float32) * 0.2
    notes, pedals, end = transcribe.drop_end_jingle(audio, sr, song + jingle,
                                                    [(0.4, 2.6), (2.75, 3.1)])
    assert notes == song and pedals == [(0.4, 2.3)] and abs(end - 2.3) < 1e-6
    # the same three quick notes played on strings are a real ending
    strings = sum(tone(440 * 2 ** ((p - 69) / 12), s, 0.15, rich) for s, _, p, _ in jingle)
    audio = (body + strings).astype(np.float32) * 0.2
    assert transcribe.drop_end_jingle(audio, sr, song + jingle) == (song + jingle, [], None)


def test_listening_summary():
    assert transcribe.summary({"notes": 12, "tuning": 0.0, "clarity": 0.88, "engine": "piano"}) \
        == "Heard 12 notes."
    text = transcribe.summary({"notes": 12, "tuning": 24.6, "clarity": 0.80, "engine": "piano"})
    assert "25 cents sharp" in text and "hard to hear" in text


def test_piano_stitches_overlapping_windows():
    import numpy as np

    class Fake:
        def run(self, _, feed):
            x = feed["audio"]
            # each output frame reports which sample it came from, so stitching is checkable
            t = (np.arange(1001) * 160 / 16000)[None, :, None]
            base = t + x[:, :1, None] * 0
            return [np.repeat(base, 88 if i < 4 else 1, axis=2) for i in range(7)]

    seen = []
    orig = piano._session
    piano._session = lambda path: Fake()
    try:
        audio = np.zeros(16000 * 25, np.float32)
        out = piano.run_model(audio, "x", on_progress=seen.append)
    finally:
        piano._session = orig
    assert seen[-1] == 1.0
    assert out["frame_output"].shape == (2501, 88)


def test_midi_from_notes_keeps_the_pedal(tmp_path):
    path = transcribe.write_midi([(0.5, 1.0, 60, 90), (0.6, 1.2, 64, 70)], [(0.4, 1.5)],
                                 str(tmp_path / "x.mid"))
    pm = pretty_midi.PrettyMIDI(path)
    assert [(n.pitch, n.velocity) for n in pm.instruments[0].notes] == [(60, 90), (64, 70)]
    assert [(c.number, c.value) for c in pm.instruments[0].control_changes] == [(64, 127), (64, 0)]


@pytest.mark.skipif(piano.model_path() is None, reason="piano model not downloaded")
def test_piano_model_hears_a_melody(tmp_path):
    pm = pretty_midi.PrettyMIDI()
    inst = pretty_midi.Instrument(0)
    melody = [60, 64, 67, 72, 67, 64, 62, 65, 69, 74]
    for i, p in enumerate(melody):
        inst.notes.append(pretty_midi.Note(90, p, 0.5 + i * 0.4, 0.5 + i * 0.4 + 0.35))
    pm.instruments.append(inst)
    wav = str(tmp_path / "take.wav")
    synth.synth(pm, wav)
    midi = transcribe.transcribe(wav, midi_out=str(tmp_path / "heard.mid"), engine="piano")
    heard = [(n.start, n.pitch) for i in pretty_midi.PrettyMIDI(midi).instruments for n in i.notes]
    found = sum(any(abs(s - n.start) < 0.06 and p == n.pitch for s, p in heard) for n in inst.notes)
    assert found >= len(melody) - 1


def test_hands_on_a_glow_look():
    pm = _pedal_midi()
    with_hands = render.preview(pm, width=270, height=480, theme_name="default", hands=True)
    without = render.preview(pm, width=270, height=480, theme_name="default", hands=False)
    assert with_hands.size == without.size == (270, 480)
    assert with_hands.tobytes() != without.tobytes()


def test_update_version_compare():
    from notefall.update import is_newer

    assert is_newer("v0.4.0", "0.3.0")
    assert is_newer("v1.0.0", "0.10.2")
    assert not is_newer("v0.3.0", "0.3.0")
    assert not is_newer("v0.2.9", "0.3.0")
    assert not is_newer("nightly", "0.3.0")
