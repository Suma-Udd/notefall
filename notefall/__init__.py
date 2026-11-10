"""NoteFall: turn MIDI or a piano recording into a falling notes video."""

__version__ = "0.4.0"

__all__ = ["render_video", "transcribe", "synth", "__version__"]


def __getattr__(name):
    # keep `import notefall` instant; numpy and Pillow load on first use
    if name == "render_video":
        from .render import render

        return render
    if name == "transcribe":
        from .transcribe import transcribe

        return transcribe
    if name == "synth":
        from .synth import synth

        return synth
    raise AttributeError(name)
