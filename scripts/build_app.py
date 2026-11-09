#!/usr/bin/env python3
"""Build the double-click NoteFall app for this OS with PyInstaller.

    pip install pyinstaller .
    python scripts/build_app.py

Leaves a zip (Windows, macOS) or tar.gz (Linux) in dist/. CI runs this on
every release, see .github/workflows/release.yml.
"""

import os
import platform
import shutil
import subprocess
import sys
import tarfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def main():
    from notefall import __version__
    from notefall.icon import save_icons

    build = os.path.join(ROOT, "build")
    dist = os.path.join(ROOT, "dist")
    os.makedirs(build, exist_ok=True)
    icon_prefix = os.path.join(build, "icon")
    save_icons(icon_prefix)

    system = platform.system()
    icon = icon_prefix + {"Windows": ".ico", "Darwin": ".icns"}.get(system, ".png")
    sep = ";" if system == "Windows" else ":"

    cmd = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
        "--name", "NoteFall",
        "--icon", icon,
        "--distpath", dist, "--workpath", os.path.join(build, "pyinstaller"),
        "--specpath", build,
        "--add-data", "%s%snotefall/models" % (os.path.join(ROOT, "notefall", "models"), sep),
        "--collect-data", "imageio_ffmpeg",
        "--collect-binaries", "onnxruntime",
        "--hidden-import", "notefall.gui",
        "--hidden-import", "notefall.cli",
        "--osx-bundle-identifier", "io.github.suma-udd.notefall",
        os.path.join(ROOT, "scripts", "notefall_app.py"),
    ]
    subprocess.run(cmd, check=True)

    arch = platform.machine().lower().replace("amd64", "x64").replace("x86_64", "x64")
    name = "NoteFall-%s-%s-%s" % (__version__, {"Darwin": "mac", "Windows": "windows"}.get(
        system, "linux"), arch)
    if system == "Darwin":
        out = os.path.join(dist, name + ".zip")
        subprocess.run(["ditto", "-c", "-k", "--keepParent", os.path.join(dist, "NoteFall.app"), out],
                       check=True)
    elif system == "Windows":
        out = shutil.make_archive(os.path.join(dist, name), "zip", dist, "NoteFall")
    else:
        out = os.path.join(dist, name + ".tar.gz")
        with tarfile.open(out, "w:gz") as tar:
            tar.add(os.path.join(dist, "NoteFall"), arcname="NoteFall")
    print("built", out)


if __name__ == "__main__":
    main()
