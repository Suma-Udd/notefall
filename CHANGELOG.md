# Changelog

## 0.3.0

- A new app: clean and quiet, with a live moving preview, one button, and progress right on it.
- Videos are now 60 fps by default, with smoother anti-aliased notes, softer lighting, a glow that hugs the keys and Inter for the text.
- Rendering is about 2.8 times faster (17 ms per phone frame instead of 48).
- Sharper encoding: CRF 17, better use of bits in dark gradients, BT.709 colour tags, fast start for the web.
- The repo is reorganised: fonts and the model live in `notefall/assets`, docs live in `docs/`.

## 0.2.0

- The app window, with downloads for Windows, Mac and Linux.
- Recordings to notes built in (Basic Pitch on onnxruntime, no TensorFlow).
- Sustain pedal support: blocks follow the keys or the pedal, the sound always follows the pedal.
- A built in piano sound, and ffmpeg bundled so nothing else needs installing.

## 0.1.0

- First version: MIDI or a recording to a falling notes video.
