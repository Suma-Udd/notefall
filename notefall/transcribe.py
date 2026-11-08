"""Audio or video to MIDI, using Spotify's basic-pitch."""

import os
import subprocess
import tempfile

from .render import ffmpeg_bin


def extract_audio(media_path, out_wav=None):
    """Pull a mono 22050 Hz wav out of any audio or video file."""
    if out_wav is None:
        fd, out_wav = tempfile.mkstemp(prefix="notefall-", suffix=".wav")
        os.close(fd)
    subprocess.run(
        [ffmpeg_bin(), "-y", "-loglevel", "error", "-i", media_path,
         "-vn", "-ac", "1", "-ar", "22050", out_wav],
        check=True,
    )
    return out_wav


def transcribe(media_path, midi_out=None, onset_threshold=0.65,
               frame_threshold=0.3, minimum_note_length=58.0,
               minimum_frequency=None, maximum_frequency=None):
    """Transcribe a recording to MIDI. Returns the path to the .mid file.

    Thresholds matter. A pedaled acoustic piano blurs note boundaries, so
    raise `onset_threshold` if you get ghost notes and lower it if real
    notes are missing. `minimum_note_length` is in milliseconds.
    """
    try:
        from basic_pitch.inference import predict
        import pretty_midi
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "audio transcription needs the extra: pip install 'notefall[transcribe]'\n"
            "(%s)" % exc
        )

    wav = extract_audio(media_path)
    try:
        _, midi_data, _ = predict(
            wav,
            onset_threshold=onset_threshold,
            frame_threshold=frame_threshold,
            minimum_note_length=minimum_note_length,
            minimum_frequency=minimum_frequency,
            maximum_frequency=maximum_frequency,
        )
    finally:
        try:
            os.unlink(wav)
        except OSError:
            pass

    if midi_out is None:
        fd, midi_out = tempfile.mkstemp(prefix="notefall-", suffix=".mid")
        os.close(fd)
    midi_data.write(midi_out)
    return midi_out
