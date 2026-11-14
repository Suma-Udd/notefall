# Changelog

## 0.7.0

- **Four new hand made looks**, all with the hands playing at the bottom:
  - **Watercolour**: soft paint washes on textured cream paper, darker where the paint dried.
  - **Journal**: a dot grid notebook page with the notes as washi tape (stripes for the right hand, polka dots for the left) and a little name sticker on each.
  - **Riso print**: grainy pink and blue ink like a risograph print, with halftone dots and a halftone sun.
  - **Moonlit**: gold and periwinkle notes under a night sky with a moon and stars.
- **Pick a look by its picture.** The row of colour dots in the app is now a grid of little previews, one per look, and hovering one shows its name.

## 0.6.2

- **Clips saved from TikTok no longer get junk notes at the end.** The logo jingle that TikTok adds to a saved video was being written down as a little run of notes. NoteFall now spots it (very short, pure beeps right at the end, which a piano can't make) and leaves it out of the notes, the MIDI and the video's sound, so the video ends when the music does.

## 0.6.1

- **The hands are told apart properly in recordings.** A recording doesn't say which hand played a note, so everything above one fixed pitch used to be painted as the right hand, which is wrong whenever a hand wanders. The split point now moves with the music: it follows the gap between the hands and never asks one hand to stretch further than a hand can. Checked on 311 classical pieces where the hands are written out, wrong hand notes went from 17% to 8%. The same goes for any MIDI with a single track.
- The MIDI saved from a recording has a **Right hand** and a **Left hand** track, like a normal piano MIDI, so other apps show the hands too.
- After listening, the app tells you how it went: how many notes it heard, whether it corrected the piano's tuning, and a warning when the recording is hard to hear clearly (echo, noise, other instruments), because then more notes will be off.

## 0.6.0

- **Notes from recordings are the right length.** With the sustain pedal down every note used to come out as long as it rings, 3 to 4 times longer than the key was held, which filled the screen with long bars. Now a pedalled note ends when that hand plays its next note. Measured on real concert recordings with known notes, the typical note went from 2.8 to 3.9 times too long down to 1.1 to 1.8. The pedal is still written to the MIDI, so the sound is the same, and "Notes ring with the pedal" (or `--note-lengths ring`) brings the long bars back.
- **Out of tune pianos are heard properly.** A piano (or an upload) a quarter of a semitone off made the listener invent notes: 85% right at +25 cents, 70% at -35. NoteFall now measures the tuning and corrects it before listening, which brings both back to 96%.
- **Quiet recordings keep their soft notes.** The volume is evened out first (a very quiet take went from 90% to 96%).
- **Save the notes as MIDI from the app.** Once a recording has been listened to, the Song card gets a "Notes as MIDI · Save…" row, so mp3 to MIDI is one click (it used to need the command line).
- Slightly stricter about what counts as a note, so fewer ghost notes in echoey rooms.
- **The preview is live.** It plays the song from the start at 30 fps instead of looping two seconds, and cross-fades when you change the look, the format or a switch.
- **The app moves.** Buttons fade between states, switches and the selection ring glide, the progress fill is smooth, the list scrolls softly and shows a thumb when there's more, the window fades in, the button turns green when the video is done, and listening shows a progress ring. The empty window plays a tiny NoteFall of its own.

## 0.5.1

- A **Check for updates** button under Create Video. It tells you if you're up to date, and when there's a new version it turns blue: one click downloads and installs it (on Mac and Linux it opens the download page).

## 0.5.0

- Recordings are listened to with a model made only for piano (ByteDance's high resolution piano transcription) instead of Basic Pitch. It gets far more notes right, and hears the sustain pedal and how hard each key was hit. It's downloaded once (about 150 MB) the first time you use a recording, and Basic Pitch is still there as the fallback (`--engine`).
- The hands now play along in every look, not just Paper, and the toggle is on by default.
- The title is empty unless you type one. It used to be filled in from the file name, which put things like a TikTok id over the video.
- A redesigned app: a calm Apple style sidebar with grouped cards, segmented controls, real switches and colour swatches, sharp on high DPI Windows screens.
- Dark mode. It follows your system, and the button at the top switches it (and remembers).
- The app remembers your look, hands and appearance between runs.

## 0.4.0

- A new look, **Paper**: a warm sketchbook page, hand drawn note blocks with the note name on each one, a keyboard with every key labelled, and the chord that's playing (with the next one coming up).
- Two animated hands play along in the Paper look. They glide to where the music goes next, lift a finger just before a note and press it down on the beat, with a soft shadow on the keys. Turn them off with the new toggle or `--no-hands`.
- Bundled the Kalam handwriting font (SIL Open Font License) for the Paper look.
- A real Windows installer: one Setup.exe, installs per user with no admin prompt, Start menu entry, optional desktop icon, clean uninstall.
- Mac downloads are now a .dmg you drag onto Applications.
- The app tells you when a new version is out. On Windows it updates itself in one click.
- Release builds take their version from the tag you type when running the release workflow.

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
