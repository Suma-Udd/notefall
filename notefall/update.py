"""Checks GitHub for a newer NoteFall and, on Windows, installs it.

Only the packaged app checks (not pip installs). One small request on launch,
silent if offline. On Windows the new installer is downloaded and run quietly,
then it reopens NoteFall. On Mac and Linux the download page opens instead.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request

from . import __version__

REPO = "Suma-Udd/notefall"
API = "https://api.github.com/repos/%s/releases/latest" % REPO
PAGE = "https://github.com/%s/releases/latest" % REPO


def _parts(version):
    return tuple(int(n) for n in re.findall(r"\d+", version)[:3])


def is_newer(latest, current=__version__):
    try:
        return _parts(latest) > _parts(current)
    except ValueError:
        return False


def installed_with_setup():
    """True when this copy came from the Windows installer (so it can update itself)."""
    if not (sys.platform.startswith("win") and getattr(sys, "frozen", False)):
        return False
    return os.path.exists(os.path.join(os.path.dirname(sys.executable), "unins000.exe"))


def check(timeout=6):
    """Return {"version", "page", "setup"} when a newer release exists, else None."""
    if not getattr(sys, "frozen", False) or os.environ.get("NOTEFALL_NO_UPDATE_CHECK"):
        return None
    req = urllib.request.Request(API, headers={"Accept": "application/vnd.github+json",
                                               "User-Agent": "NoteFall/" + __version__})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.load(r)
    except Exception:
        return None
    tag = data.get("tag_name") or ""
    if data.get("draft") or data.get("prerelease") or not is_newer(tag):
        return None
    setup = next((a["browser_download_url"] for a in data.get("assets", [])
                  if a.get("name", "").lower().endswith("-setup.exe")), None)
    return {"version": tag.lstrip("v"), "page": data.get("html_url") or PAGE, "setup": setup}


def download(url, on_progress=None, cancel=None):
    """Download the installer to a temp file and return its path."""
    dest = os.path.join(tempfile.gettempdir(), url.rsplit("/", 1)[-1])
    req = urllib.request.Request(url, headers={"User-Agent": "NoteFall/" + __version__})
    with urllib.request.urlopen(req, timeout=30) as r, open(dest + ".part", "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while True:
            if cancel is not None and cancel.is_set():
                raise RuntimeError("cancelled")
            chunk = r.read(1 << 16)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if on_progress and total:
                on_progress(done / total)
    os.replace(dest + ".part", dest)
    return dest


def run_installer(path):
    """Start the installer quietly; it closes this app, updates, and reopens it."""
    flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([path, "/SILENT", "/SP-", "/SUPPRESSMSGBOXES", "/NORESTART",
                      "/CLOSEAPPLICATIONS"], creationflags=flags, close_fds=True)
