<p align="center">
  <img src="docs/media/banner.png" width="840" alt="NoteFall: piano music in, falling notes out">
</p>

<p align="center">
  <b>Turn piano music into a falling notes video.</b><br>
  Give it a MIDI file or just a recording of someone playing. Get a video back, ready to post.
</p>

<p align="center">
  <a href="https://github.com/Suma-Udd/notefall/releases/latest"><img alt="Latest version" src="https://img.shields.io/github/v/release/Suma-Udd/notefall?label=version&color=0a84ff&style=flat-square"></a>
  <a href="https://github.com/Suma-Udd/notefall/releases"><img alt="Downloads" src="https://img.shields.io/github/downloads/Suma-Udd/notefall/total?color=30d158&style=flat-square"></a>
  <img alt="Windows, Mac and Linux" src="https://img.shields.io/badge/runs%20on-Windows%20%C2%B7%20Mac%20%C2%B7%20Linux-8e8e93?style=flat-square">
  <a href="https://github.com/Suma-Udd/notefall/actions/workflows/tests.yml"><img alt="Tests" src="https://img.shields.io/github/actions/workflow/status/Suma-Udd/notefall/tests.yml?branch=main&label=tests&style=flat-square"></a>
  <a href="LICENSE"><img alt="MIT license" src="https://img.shields.io/badge/license-MIT-8e8e93?style=flat-square"></a>
</p>

<p align="center">
  <a href="https://github.com/Suma-Udd/notefall/releases/latest"><img src="docs/media/buttons/download-windows.svg" height="56" alt="Download for Windows"></a>
  <a href="https://github.com/Suma-Udd/notefall/releases/latest"><img src="docs/media/buttons/download-mac.svg" height="56" alt="Download for Mac"></a>
  <a href="https://github.com/Suma-Udd/notefall/releases/latest"><img src="docs/media/buttons/download-linux.svg" height="56" alt="Download for Linux"></a>
</p>

<p align="center">
  <sub>Free, no account, no watermark. Everything runs on your own computer.</sub>
</p>

<br>

## See it

<table>
  <tr>
    <td align="center">
      <img src="docs/media/demo.webp" width="580" alt="Bach's Prelude in C as glowing falling notes"><br>
      <sub><b>Midnight</b> look. Watch with sound: <a href="docs/media/demo-landscape.mp4">YouTube shape</a> · <a href="docs/media/demo.mp4">phone shape</a></sub>
    </td>
    <td align="center">
      <img src="docs/media/demo-paper.webp" width="183" alt="The Paper look: hand drawn notes, labelled keys, chord names and animated hands"><br>
      <sub><b>Paper</b> look. <a href="docs/media/demo-paper.mp4">With sound</a></sub>
    </td>
  </tr>
</table>

<p align="center"><sub>Bach's Prelude in C, straight out of NoteFall. Nothing edited by hand.</sub></p>

## What it does

<table>
  <tr>
    <td width="50%" valign="top">
      <h3>🎹 MIDI in, video out</h3>
      Every note lands on the exact key, left hand in one colour, right hand in another.
    </td>
    <td width="50%" valign="top">
      <h3>🎧 No MIDI? Use a recording</h3>
      An mp3, a phone recording or a video of someone playing. NoteFall listens with a piano only model, writes down the notes and the pedal, and keeps the real sound.
    </td>
  </tr>
  <tr>
    <td valign="top">
      <h3>📱 Ready to post</h3>
      Phone (TikTok, Reels, Shorts), YouTube or square, in smooth 60 fps.
    </td>
    <td valign="top">
      <h3>✋ Hands that play</h3>
      Two animated hands glide over the keys and press each note on the beat. Every look has them.
    </td>
  </tr>
  <tr>
    <td valign="top">
      <h3>🎨 Six looks</h3>
      Glowing notes on a dark stage in five colour sets, or <b>Paper</b>: a sketchbook page with every key and note named and the chord on screen. No sheet music needed.
    </td>
    <td valign="top">
      <h3>🔄 Updates itself</h3>
      Click <b>Check for updates</b> in the app. On Windows it downloads, installs and reopens in one go.
    </td>
  </tr>
</table>

## The app

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/media/app-dark.png">
    <img src="docs/media/app-light.png" width="820" alt="The NoteFall app">
  </picture>
</p>

<p align="center"><sub>Light and dark mode. It follows your computer, and the button in the corner switches it.</sub></p>

## Get it

1. Open the **[download page](https://github.com/Suma-Udd/notefall/releases/latest)** and scroll to **Assets**. Grab the file for your computer:

   | your computer | the file to download |
   | --- | --- |
   | 🪟 Windows | `NoteFall-…-windows-x64-Setup.exe` |
   | 🍎 Mac with an Apple chip (M1 and newer) | `NoteFall-…-mac-arm64.dmg` |
   | 🍎 Older Intel Mac | `NoteFall-…-mac-x64.dmg` |
   | 🐧 Linux | `NoteFall-…-linux-x64.tar.gz` |

   Not sure which Mac you have? Click the Apple menu, then **About This Mac**. If it says **Chip: Apple M…** take arm64, if it says **Processor: Intel** take x64.

2. **Windows:** open the Setup file and click **Install**. No admin password needed, and NoteFall shows up in the Start menu.<br>
   **Mac:** open the .dmg and drag **NoteFall** onto **Applications**.

<details>
<summary><b>My computer says the app might be unsafe</b></summary>
<br>

That's because the app isn't signed by a big company (signing costs money every year). It's the same app, built in the open right here by GitHub.

- **Windows:** click **More info**, then **Run anyway**.
- **Mac:** open NoteFall once, then go to **System Settings → Privacy & Security** and click **Open Anyway**.

You only do this once.

</details>

<details>
<summary><b>How do updates work?</b></summary>
<br>

NoteFall checks for a new version when it opens, and you can check any time with the **Check for updates** button under **Create Video**. On Windows one click downloads the new version, installs it and reopens the app. On a Mac it opens the download page so you can grab the new .dmg.

If you're on 0.3.0 or older, download the new version by hand once. After that it's automatic.

</details>

<details>
<summary><b>Prefer a one line installer?</b></summary>
<br>

It installs NoteFall with a shortcut, needs no admin password, and you can run it again any time to update.

**Windows:** open **PowerShell**, paste this and press Enter:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://raw.githubusercontent.com/Suma-Udd/notefall/main/scripts/install.ps1 | iex"
```

**Mac or Linux:** open **Terminal**, paste this and press Enter:

```sh
curl -LsSf https://raw.githubusercontent.com/Suma-Udd/notefall/main/scripts/install.sh | sh
```

</details>

## Make a video

1. Open NoteFall and click **Choose…**. To try it right away, use [`examples/prelude_in_c.mid`](examples/prelude_in_c.mid).
2. Pick a format and a look. The preview moves as you change things.
3. Click **Create Video** and pick where to save it.
4. When it's done, click **Play**. That's it.

> [!TIP]
> A MIDI file is exact, a recording is a very good guess. For the cleanest result from a recording, use one with just the piano in a quiet room. The **[guide](docs/guide.md)** has more tips.

## Learn more

| | |
| --- | --- |
| 📖 [Guide](docs/guide.md) | where to find MIDI files, using recordings, the sustain pedal, common questions |
| ⌨️ [Command line](docs/command-line.md) | every option, and using NoteFall from Python |
| ⚙️ [How it works](docs/how-it-works.md) | how the video gets drawn, and why it's fast |
| 🛠️ [Contributing](CONTRIBUTING.md) | run it from source, tests, building the apps |
| 🗒️ [Changelog](CHANGELOG.md) | what changed in each version |

Found a bug or have an idea? **[Open an issue](https://github.com/Suma-Udd/notefall/issues/new/choose)**, there's a short form for each.

## Credits

Recording to notes uses ByteDance's [piano transcription](https://github.com/bytedance/piano_transcription) model (Kong et al., code MIT, see [`docs/licenses/piano-transcription.md`](docs/licenses/piano-transcription.md)), with [Basic Pitch](https://github.com/spotify/basic-pitch) by Spotify (Apache 2.0) as the fallback. Text is set in [Inter](https://rsms.me/inter/) and the Paper look in [Kalam](https://fonts.google.com/specimen/Kalam) (both OFL). MIDI reading by [pretty_midi](https://github.com/craffel/pretty-midi), video by [FFmpeg](https://ffmpeg.org). The Basic Pitch and font licenses live in [`notefall/assets`](notefall/assets).

NoteFall itself is MIT licensed, see [LICENSE](LICENSE).
