# Guide

[Back to the README](../README.md)

- [Where do I get a MIDI file?](#where-do-i-get-a-midi-file)
- [Using a recording instead](#using-a-recording-instead)
- [The sustain pedal](#the-sustain-pedal)
- [The settings in the app](#the-settings-in-the-app)
- [Questions](#questions)

## Where do I get a MIDI file?

A MIDI file (`.mid`) is a list of which keys were pressed and when. It gives the cleanest video, because nothing has to be guessed.

- **Digital piano or keyboard.** Most can record straight to MIDI, over USB or onto a USB stick. Look for a "record" or "USB" button, or plug it into your computer and record with a free app like [MuseScore](https://musescore.org) or GarageBand.
- **Sheet music apps.** MuseScore, Flat and Noteflight can all export MIDI.
- **The internet.** Search for the song name plus "MIDI". Lots of classical pieces are free and public domain.

No MIDI at all? Use a recording.

## Using a recording instead

Pick an audio or video file (mp3, wav, m4a, mp4, mov and more) and NoteFall figures out the notes by itself, right on your computer, and keeps the real sound under the video.

Be realistic about this part. On a clean recording of a digital piano it's really good. On an acoustic piano with lots of pedal, or with singing or other instruments in the background, it will miss some quiet notes and invent a few that weren't there. For the best result, record just the piano in a quiet room.

On the command line, `--keep-midi notes.mid` saves what NoteFall heard, so you can fix wrong notes in any MIDI editor and render that instead.

## The sustain pedal

When you hold the sustain pedal, a note keeps ringing after you let go of the key. So how long should the falling block be? It depends what the video is for, so you get to pick.

- **By default a block is as long as the key was held.** That's what you'd copy when learning a piece, and fast passages stay readable.
- **Turn on "Notes ring with the pedal"** (or use `--sustain pedal`) and blocks last as long as the sound does. If a key is played again while the pedal is down, the old block stops there, like on a real piano.
- **The sound always follows the pedal** either way, and a small **Sustain** sign lights up above the keys while it's down.

Recordings don't carry pedal information, so their blocks simply follow how long each note sounds.

## The settings in the app

| setting | what it does |
| --- | --- |
| Format | Phone is 1080 × 1920 for TikTok, Reels and Shorts. YouTube is 1920 × 1080. Square is 1080 × 1080. |
| Colours | Five colour themes. The preview shows each one. |
| Title | Text in the top corner. Leave it empty for none. |
| Sound | **Piano** makes a piano sound from your MIDI. **Recording** uses your own audio or video file. **None** makes a silent video. |
| Smooth motion | 60 frames a second. Turn it off for 30, which renders twice as fast. |
| Notes ring with the pedal | See [the sustain pedal](#the-sustain-pedal). |
| Sparks | The little sparks where notes hit the keys. |

## Questions

**How long does it take?** About as long as the song on a normal laptop at 60 fps, often less. It uses all your CPU cores. Turning off smooth motion halves the time.

**Why are the hands the colours they are?** If the MIDI has two tracks (most piano MIDIs do), or tracks named something like "Left hand" and "Right hand", NoteFall uses those. Otherwise it splits by pitch. You can force the split point with `--split C4`.

**The keyboard doesn't show all 88 keys.** On purpose. It shows only the range your song uses, so the keys are big enough to see on a phone.

**Do I need to install ffmpeg?** No, NoteFall brings its own. If you already have one installed it uses yours.

**Something broke.** Please [open an issue](https://github.com/Suma-Udd/notefall/issues) with the message you got. If it's about a MIDI file, attaching the file helps a lot.
