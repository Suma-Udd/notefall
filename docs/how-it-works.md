# How it works

[Back to the README](../README.md)

A few ideas, and the rest is drawing.

1. **Crop the keyboard to what's played.** All 88 keys across a phone screen leaves about 20 pixels per white key, which is unreadable. Showing only the range the song uses makes blocks two to four times wider.
2. **One geometry map.** A single `pitch -> (x0, x1, is_black)` mapping feeds both the drawn keys and the falling blocks, so they can't drift apart.
3. **Blocks land on the key line.** `bottom = keys_top - (start - t) * speed`, and the height is the note length times the same speed.
4. **Notes are pre-drawn sprites.** Each kind of block (hand, black or white key, playing or not, how hard it was hit) is drawn once at 4x size with smooth corners, soft lighting and a thin rim, then shrunk. A block of any height is two caps plus a stretched middle, so drawing a frame is just pasting.
5. **Glow is cheap if you cheat.** It only exists near the keys, so it's drawn there alone, at quarter size, blurred, scaled up and screen blended on top.
6. **Frames go straight into the encoder.** They're drawn on all CPU cores and piped as raw pixels into x264 (60 fps, CRF 17, BT.709 colour, fast start). No PNG per frame, no temp folders full of images.
7. **No TensorFlow.** Listening to recordings runs Spotify's Basic Pitch model directly through onnxruntime. The model is 230 KB and ships inside NoteFall, and the note decoding is ported to plain numpy. It gives the same notes as the original library.

A 1080 × 1920 frame takes about 17 ms to draw on one core, so a three minute song at 60 fps is a few minutes on a normal laptop.

## Where things live

```
notefall/
  app.py          the app window
  cli.py          the notefall command
  render.py       draws frames and talks to ffmpeg
  paper.py        the Paper look: sketched notes and labelled keys
  hands.py        the animated hands, planned once and drawn on any look
  chords.py       names the chord that's playing
  keyboard.py     key layout, hands and the sustain pedal
  synth.py        the built in piano sound
  transcribe.py   recording -> notes, picks the listener and writes the MIDI
  piano.py        the piano-only listener (ByteDance model on onnxruntime, downloaded once)
  theme.py        the colour themes
  media.py        finding ffmpeg, reading audio, friendly errors
  icon.py         the app icon, drawn in code
  assets/         fonts (Inter, Kalam) and the Basic Pitch model, with their licenses
tests/            pytest suite
examples/         the demo MIDI and the script that builds the demo videos
scripts/          building the apps and the one line installers
docs/             these pages, plus the images and videos the README uses
```
