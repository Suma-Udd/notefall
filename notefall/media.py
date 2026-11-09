"""ffmpeg discovery, probing and temp files."""

import atexit
import os
import re
import shutil
import subprocess
import sys
import tempfile

# stop Windows flashing a console window for every ffmpeg call from the app
NO_WINDOW = {"creationflags": 0x08000000} if sys.platform.startswith("win") else {}


class NotefallError(Exception):
    """Something went wrong that the user can fix. The message says how."""


_TEMP = []


def temp_path(suffix):
    fd, path = tempfile.mkstemp(prefix="notefall-", suffix=suffix)
    os.close(fd)
    _TEMP.append(path)
    return path


@atexit.register
def _cleanup():
    while _TEMP:
        try:
            os.unlink(_TEMP.pop())
        except OSError:
            pass


_FFMPEG = None


def ffmpeg_bin():
    """Find ffmpeg: NOTEFALL_FFMPEG, then PATH, then the copy bundled by imageio-ffmpeg."""
    global _FFMPEG
    if _FFMPEG:
        return _FFMPEG
    env = os.environ.get("NOTEFALL_FFMPEG")
    if env and os.path.exists(env):
        _FFMPEG = env
        return env
    found = shutil.which("ffmpeg")
    if found:
        _FFMPEG = found
        return found
    try:
        import imageio_ffmpeg

        _FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
        return _FFMPEG
    except Exception:
        pass
    raise NotefallError(
        "couldn't find ffmpeg. Reinstall notefall (it ships its own copy), "
        "or install ffmpeg yourself: https://ffmpeg.org/download.html"
    )


_DURATION = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")


def duration(path):
    """Length of an audio or video file in seconds, 0.0 if unknown.

    Parses `ffmpeg -i` instead of calling ffprobe, because the bundled
    ffmpeg from imageio-ffmpeg doesn't come with ffprobe.
    """
    proc = subprocess.run([ffmpeg_bin(), "-hide_banner", "-i", path],
                          capture_output=True, text=True, errors="replace", **NO_WINDOW)
    m = _DURATION.search(proc.stderr)
    if not m:
        return 0.0
    h, mnt, s = m.groups()
    return int(h) * 3600 + int(mnt) * 60 + float(s)


def has_audio(path):
    proc = subprocess.run([ffmpeg_bin(), "-hide_banner", "-i", path],
                          capture_output=True, text=True, errors="replace", **NO_WINDOW)
    return bool(re.search(r"Stream #\S+.*: Audio:", proc.stderr))
