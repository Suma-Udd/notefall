# Contributing

Bug reports, ideas and pull requests are all welcome. [How it works](docs/how-it-works.md) explains the moving parts and where each one lives.

## Run it from source

```bash
git clone https://github.com/Suma-Udd/notefall
cd notefall
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
notefall                # the app
notefall song.mid       # the command line
pytest                  # the tests
```

The app needs a Python with tkinter, which the python.org installers and most Linux distros (`python3-tk`) have.

## Rebuild the demo

```bash
python examples/make_demo.py           # docs/media/demo.mp4, demo-landscape.mp4 and demo.webp
python examples/make_demo.py --quick   # a small fast preview
```

The demo is fully generated: the script writes the MIDI itself and makes its own sound, so there are no mystery files.

## Build the apps

```bash
pip install pyinstaller
python scripts/build_app.py
```

That builds the double-click app for the computer you run it on, into `dist/`.

## Releases

1. Bump the version in `pyproject.toml` and `notefall/__init__.py`, and add a section to [CHANGELOG.md](CHANGELOG.md).
2. Push a tag like `v0.3.0`, or open **Actions → release → Run workflow** and type the tag.

GitHub Actions then builds the Windows, Mac and Linux apps, checks that each one starts, and publishes them on the [releases page](https://github.com/Suma-Udd/notefall/releases).
