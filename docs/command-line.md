# Command line

[Back to the README](../README.md)

Everything the app does also works from a terminal. Running `notefall` with nothing after it opens the app.

```bash
# a MIDI straight to a video next to it (song-notefall.mp4), with piano sound
notefall song.mid

# YouTube shape, other colours, a title
notefall song.mid --format youtube --theme neon --title "Clair de Lune"

# a recording, no MIDI anywhere
notefall performance.mp4

# MIDI for the notes, your real recording for the sound
notefall song.mid --audio recording.wav

# blocks as long as the pedal holds them
notefall song.mid --sustain pedal
```

## Options

| option | what it does |
| --- | --- |
| `-o, --out FILE` | where to save it. Default: next to your song, called `name-notefall.mp4` |
| `--format` | `phone` (1080x1920, default), `youtube` (1920x1080) or `square` (1080x1080) |
| `--size WxH` | any exact size, like `1440x2560` |
| `--fps N` | frames per second. Default 60, and 30 renders twice as fast |
| `--theme` | `default`, `sunset`, `ocean`, `neon`, `gold` (glowing notes on a dark stage), `paper` (sketchbook with note and chord names), `watercolour` (soft paint on cream paper), `washi` (journal: washi tape on a dot grid), `riso` (pink and blue ink print) or `moonlit` (gold notes under a night sky) |
| `--title TEXT` | text in the top left |
| `--audio FILE` | sound to put under the video |
| `--silent` | no sound at all |
| `--soundfont FILE.sf2` | a real sampled piano for the sound (needs [FluidSynth](https://www.fluidsynth.org) installed) |
| `--sustain keys/pedal` | block length, see [the sustain pedal](guide.md#the-sustain-pedal) |
| `--split NOTE` | colour by pitch instead of by track, like `--split C4` |
| `--lookahead SECONDS` | how much of the future you see above the keys |
| `--lead-in SECONDS` | wait before the first note lands |
| `--no-sparks`, `--no-bar-lines`, `--no-progress` | turn those bits off |
| `--no-hands` | hide the animated hands |
| `--workers N` | how many CPU cores to draw with |
| `--keep-midi FILE` | save the notes heard in a recording, so you can fix them and render again |
| `--engine` | how recordings are listened to: `piano` (piano-only model, downloaded once), `basic` (Basic Pitch, small, any instrument) or `auto` (piano, falling back to basic) |
| `--onset-threshold`, `--min-note-ms` | recording tuning. A higher threshold means fewer made up notes, lower catches soft notes |

Run `notefall --help` for the full list.

## From Python

```python
from notefall import render_video, synth

synth("song.mid", "song.wav")
render_video("song.mid", "song.mp4", width=1920, height=1080, audio="song.wav",
             theme_name="ocean", title="My Song")
```

`transcribe("recording.mp3", midi_out="notes.mid")` turns a recording into a MIDI file.
