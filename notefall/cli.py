"""Command line interface."""

import argparse
import os
import sys

from . import __version__, render as render_mod, synth as synth_mod, theme
from .transcribe import transcribe

MIDI_EXT = {".mid", ".midi"}


def build_parser():
    p = argparse.ArgumentParser(
        prog="notefall",
        description="Turn a MIDI file or a piano recording into a falling notes video.",
    )
    p.add_argument("input", help="MIDI file, or an audio/video recording to transcribe")
    p.add_argument("-o", "--out", default="notefall.mp4", help="output mp4 (default: notefall.mp4)")
    p.add_argument("--audio", help="audio track to mux in (defaults to the input audio)")
    p.add_argument("--title", help="text in the top left corner")
    p.add_argument("--size", default="1080x1920", help="WxH, default 1080x1920 (vertical)")
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--lookahead", type=float, default=4.0,
                   help="seconds of notes visible above the keyboard (default 4)")
    p.add_argument("--theme", default=theme.DEFAULT_THEME,
                   choices=sorted(theme.THEMES), help="colour palette")
    p.add_argument("--no-progress", action="store_true", help="hide the bottom progress bar")
    p.add_argument("--keep-midi", help="where to save the transcribed MIDI")
    p.add_argument("--synth", action="store_true",
                   help="synthesise piano audio from the MIDI when there is no recording")
    # transcription tuning
    g = p.add_argument_group("transcription")
    g.add_argument("--onset-threshold", type=float, default=0.65)
    g.add_argument("--frame-threshold", type=float, default=0.3)
    g.add_argument("--min-note-ms", type=float, default=58.0)
    g.add_argument("--min-hz", type=float, default=None)
    g.add_argument("--max-hz", type=float, default=None)
    p.add_argument("--version", action="version", version="notefall " + __version__)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)

    try:
        width, height = (int(v) for v in args.size.lower().split("x"))
    except ValueError:
        raise SystemExit("--size must look like 1080x1920")

    if not os.path.exists(args.input):
        raise SystemExit("no such file: %s" % args.input)

    ext = os.path.splitext(args.input)[1].lower()
    audio = args.audio

    if ext in MIDI_EXT:
        midi_path = args.input
        if args.synth and not audio:
            audio = os.path.join(os.path.dirname(os.path.abspath(args.out)) or ".",
                                 "_notefall_audio.wav")
            synth_mod.synth(midi_path, audio)
            print("synthesised audio ->", audio)
    else:
        print("transcribing", args.input, "...")
        midi_path = transcribe(
            args.input,
            midi_out=args.keep_midi,
            onset_threshold=args.onset_threshold,
            frame_threshold=args.frame_threshold,
            minimum_note_length=args.min_note_ms,
            minimum_frequency=args.min_hz,
            maximum_frequency=args.max_hz,
        )
        if args.keep_midi:
            print("midi saved ->", midi_path)
        if not audio:
            audio = args.input

    print("rendering %s -> %s" % (midi_path, args.out))
    render_mod.render(
        midi_path,
        args.out,
        width=width,
        height=height,
        fps=args.fps,
        lookahead=args.lookahead,
        theme_name=args.theme,
        title=args.title,
        audio=audio,
        progress=not args.no_progress,
    )
    print("done:", args.out, "(%.1f MB)" % (os.path.getsize(args.out) / 1e6))
    return 0


if __name__ == "__main__":
    sys.exit(main())
