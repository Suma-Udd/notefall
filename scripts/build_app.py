#!/usr/bin/env python3
"""Build the double-click NoteFall app for this OS with PyInstaller.

    pip install pyinstaller .
    python scripts/build_app.py

Leaves in dist/:
  Windows  NoteFall-<v>-windows-x64-Setup.exe (installer) + a portable zip
  macOS    NoteFall-<v>-mac-<arch>.dmg (drag to Applications)
  Linux    NoteFall-<v>-linux-x64.tar.gz
CI runs this on every release, see .github/workflows/release.yml. The
Windows installer needs Inno Setup 6 (iscc), which CI installs.
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
        "--add-data", "%s%snotefall/assets" % (os.path.join(ROOT, "notefall", "assets"), sep),
        "--collect-data", "imageio_ffmpeg",
        "--collect-data", "certifi",
        "--collect-binaries", "onnxruntime",
        "--hidden-import", "notefall.app",
        "--hidden-import", "notefall.cli",
        "--hidden-import", "notefall.update",
        # never used by the app, keeps the download smaller
        "--exclude-module", "pytest", "--exclude-module", "IPython",
        "--exclude-module", "matplotlib", "--exclude-module", "scipy",
        "--osx-bundle-identifier", "io.github.suma-udd.notefall",
        os.path.join(ROOT, "scripts", "notefall_app.py"),
    ]
    subprocess.run(cmd, check=True)

    arch = platform.machine().lower().replace("amd64", "x64").replace("x86_64", "x64")
    name = "NoteFall-%s-%s-%s" % (__version__, {"Darwin": "mac", "Windows": "windows"}.get(
        system, "linux"), arch)
    if system == "Darwin":
        out = make_dmg(dist, name)
    elif system == "Windows":
        out = shutil.make_archive(os.path.join(dist, name), "zip", dist, "NoteFall")
        print("built", out)
        out = make_setup(dist, build, icon, __version__)
    else:
        out = os.path.join(dist, name + ".tar.gz")
        with tarfile.open(out, "w:gz") as tar:
            tar.add(os.path.join(dist, "NoteFall"), arcname="NoteFall")
    print("built", out)


def make_dmg(dist, name):
    """A disk image with the app and an Applications shortcut to drag it onto."""
    stage = os.path.join(dist, "dmg")
    shutil.rmtree(stage, ignore_errors=True)
    os.makedirs(stage)
    subprocess.run(["ditto", os.path.join(dist, "NoteFall.app"), os.path.join(stage, "NoteFall.app")],
                   check=True)
    os.symlink("/Applications", os.path.join(stage, "Applications"))
    out = os.path.join(dist, name + ".dmg")
    subprocess.run(["hdiutil", "create", "-volname", "NoteFall", "-srcfolder", stage, "-ov",
                    "-fs", "HFS+", "-format", "ULFO", out], check=True)
    shutil.rmtree(stage)
    return out


def find_iscc():
    found = shutil.which("iscc")
    if found:
        return found
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"),
                 os.environ.get("LOCALAPPDATA") and os.path.join(os.environ["LOCALAPPDATA"], "Programs")):
        path = base and os.path.join(base, "Inno Setup 6", "ISCC.exe")
        if path and os.path.exists(path):
            return path
    raise SystemExit("Inno Setup 6 not found. Install it (choco install innosetup) and try again.")


def make_setup(dist, build, icon, version):
    """The Windows installer, from the PyInstaller folder."""
    subprocess.run([find_iscc(), "/Q", "/DAppVersion=" + version,
                    "/DSourceDir=" + os.path.join(dist, "NoteFall"), "/DOutputDir=" + dist,
                    "/DIconFile=" + icon, os.path.join(ROOT, "scripts", "installer", "notefall.iss")],
                   check=True)
    return os.path.join(dist, "NoteFall-%s-windows-x64-Setup.exe" % version)


if __name__ == "__main__":
    main()
