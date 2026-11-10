"""Command line interface.

    notefall                 open the app window
    notefall song.mid        make song-notefall.mp4 next to it
"""

import argparse
import os
import sys

from . import __version__, keyboard, media, render as render_mod, synth as synth_mod, theme

MIDI_EXT = {".mid", ".midi", ".kar", ".smf"}
OUT_EXT = {".mp4", ".mov", ".mkv"}


def default_output(input_path):
    stem, _ = os.path.splitext(os.path.abspath(input_path))
    return stem + "-notefall.mp4"


def parse_size(text):
    try:
        w, h = (int(v) for v in text.lower().replace(" ", "").split("x"))
    except ValueError:
        raise media.NotefallError("--size must look like 1080x1920")
    if w < 64 or h < 64 or w > 7680 or h > 7680:
        raise media.NotefallError("--size must be between 64 and 7680 pixels on each side")
    return w, h


def build_parser():
    p = argparse.ArgumentParser(
        prog="notefall",
        description="Turn a MIDI file or a piano recording into a falling notes video. "
                    "Run it with no arguments to open the app window.",
        epilog="examples:\n"
               "  notefall song.mid\n"
               "  notefall song.mid --format youtube --theme neon --title \"My Song\"\n"
               "  notefall performance.mp4\n"
               "  notefall song.mid --audio recording.wav",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("input", nargs="?",
                   help="a MIDI file, or an audio/video recording of a piano")
    p.add_argument("-o", "--out", help="where to save the video (default: next to the input)")
    p.add_argument("--audio", help="sound to put under the video, like your own recording")
    p.add_argument("--title", help="text in the top left corner")
    p.add_argument("--format", choices=sorted(render_mod.FORMATS), default="phone",
                   help="phone = 1080x1920 (TikTok, Reels, Shorts), youtube = 1920x1080, "
                        "square = 1080x1080 (default: phone)")
    p.add_argument("--size", help="exact WxH in pixels, overrides --format")
    p.add_argument("--fps", type=int, default=60, help="frames per second (default 60, 30 renders twice as fast)")
    p.add_argument("--theme", default=theme.DEFAULT_THEME, choices=list(theme.THEMES),
                   help="colour palette (default: %s)" % theme.DEFAULT_THEME)
    p.add_argument("--lookahead", type=float,
                   help="seconds of notes visible above the keys (default: picked for the size)")
    p.add_argument("--lead-in", type=float,
                   help="seconds before the first note lands (default: enough to fall in)")
    p.add_argument("--split", metavar="NOTE",
                   help="colour by pitch instead of by track: notes at or above NOTE (like C4) "
                        "are right hand")
    p.add_argument("--sustain", choices=["keys", "pedal"], default="keys",
                   help="how long blocks are: keys = how long each key was held (default, best "
                        "for learning), pedal = until the sustain pedal lifts (how long it rings)")
    p.add_argument("--silent", action="store_true",
                   help="no sound. By default a MIDI with no --audio gets a piano track")
    p.add_argument("--synth", action="store_true", help=argparse.SUPPRESS)  # old flag, now default
    p.add_argument("--soundfont", help="a .sf2 piano for the sound (needs FluidSynth installed)")
    p.add_argument("--no-sparks", action="store_true", help="turn off the little sparks")
    p.add_argument("--no-bar-lines", action="store_true", help="hide the faint bar lines")
    p.add_argument("--no-progress", action="store_true", help="hide the bottom progress bar")
    p.add_argument("--workers", type=int, help="how many CPU cores to draw with")
    p.add_argument("--keep-midi", help="save the MIDI heard in a recording to this file")
    g = p.add_argument_group("listening to recordings (only used when the input isn't MIDI)")
    g.add_argument("--onset-threshold", type=float, default=0.65,
                   help="higher = fewer ghost notes, lower = catch soft notes (default 0.65)")
    g.add_argument("--frame-threshold", type=float, default=0.3)
    g.add_argument("--min-note-ms", type=float, default=58.0,
                   help="ignore notes shorter than this (default 58)")
    g.add_argument("--min-hz", type=float, default=None)
    g.add_argument("--max-hz", type=float, default=None)
    p.add_argument("--version", action="version", version="notefall " + __version__)
    return p


def run(args, log=print, on_progress=None, cancel=None):
    """Do the work for parsed `args`. Returns the output path."""
    if not os.path.isfile(args.input):
        raise media.NotefallError("can't find the file %s" % args.input)

    width, height = parse_size(args.size) if args.size else render_mod.FORMATS[args.format]
    out = args.out or default_output(args.input)
    if os.path.splitext(out)[1].lower() not in OUT_EXT:
        out += ".mp4"
    if os.path.abspath(out) == os.path.abspath(args.input):
        raise media.NotefallError("the output would overwrite your input file, pick another name")
    split = None
    if args.split:
        try:
            split = keyboard.parse_note(args.split)
        except ValueError:
            raise media.NotefallError("--split wants a note like C4 or F#3, got %r" % args.split)

    ext = os.path.splitext(args.input)[1].lower()
    audio = args.audio
    if audio and not os.path.isfile(audio):
        raise media.NotefallError("can't find the audio file %s" % audio)
    is_midi = ext in MIDI_EXT
    bar_lines = not args.no_bar_lines

    if is_midi:
        midi_path = args.input
    else:
        if not media.has_audio(args.input):
            raise media.NotefallError(
                "%s doesn't look like a MIDI file or a recording with sound in it" % args.input)
        log("Listening to %s and writing down the notes..." % os.path.basename(args.input))
        from .transcribe import transcribe

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
            log("Saved the notes as %s" % midi_path)
        if not audio:
            audio = args.input
        # a transcription has no real tempo, so bar lines would be made up
        bar_lines = False

    if is_midi and not audio and not args.silent:
        log("Making a piano sound for the MIDI...")
        audio = synth_mod.synth(midi_path, media.temp_path(".wav"), soundfont=args.soundfont)

    log("Drawing the video (%dx%d, %d fps)..." % (width, height, args.fps))
    render_mod.render(
        midi_path,
        out,
        width=width,
        height=height,
        fps=args.fps,
        lookahead=args.lookahead,
        theme_name=args.theme,
        title=args.title,
        audio=audio,
        progress=not args.no_progress,
        lead_in=args.lead_in,
        bar_lines=bar_lines,
        particles=not args.no_sparks,
        split=split,
        sustain=args.sustain,
        workers=args.workers,
        on_progress=on_progress,
        cancel=cancel,
    )
    return out


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.input is None:
        try:
            from .app import main as gui_main
        except ImportError as exc:  # Python built without tkinter
            parser.print_help()
            print("\n(the app window needs tkinter, which this Python doesn't have: %s)" % exc)
            return 2
        return gui_main()

    # packaged windowed apps have no console, so stderr can be None
    tty = sys.stderr is not None and getattr(sys.stderr, "isatty", lambda: False)()
    progress = render_mod._cli_progress if tty else None
    try:
        out = run(args, on_progress=progress)
    except media.NotefallError as exc:
        print("notefall: %s" % exc, file=sys.stderr or sys.stdout)
        return 1
    except KeyboardInterrupt:
        print("\nnotefall: stopped", file=sys.stderr or sys.stdout)
        return 130
    print("Done! Your video is here: %s (%.1f MB)" % (out, os.path.getsize(out) / 1e6))
    return 0


if __name__ == "__main__":
    sys.exit(main())
