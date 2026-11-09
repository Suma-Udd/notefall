#!/bin/sh
# NoteFall installer for macOS and Linux.
#
#   curl -LsSf https://raw.githubusercontent.com/Suma-Udd/notefall/main/scripts/install.sh | sh
#
# Installs uv (a tiny Python manager, it brings its own Python so you don't
# need one), installs NoteFall with it, and adds a NoteFall app you can
# double-click. Nothing needs admin rights. Run it again to update.
set -e

SOURCE="${NOTEFALL_SOURCE:-notefall @ https://github.com/Suma-Udd/notefall/archive/refs/heads/main.zip}"

say() { printf '\033[1;32m==>\033[0m %s\n' "$1"; }

if ! command -v uv >/dev/null 2>&1; then
    say "Getting uv (installs Python for NoteFall, nothing system wide)"
    curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

say "Installing NoteFall"
uv tool install --force --python 3.12 "$SOURCE"

BIN_DIR="$(uv tool dir --bin 2>/dev/null || echo "$HOME/.local/bin")"
TOOL_PY="$(uv tool dir)/notefall/bin/python"

case "$(uname -s)" in
Darwin)
    APP="$HOME/Applications/NoteFall.app"
    say "Adding NoteFall to $HOME/Applications"
    mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
    cat > "$APP/Contents/MacOS/NoteFall" <<SH
#!/bin/sh
exec "$BIN_DIR/notefall-app" "\$@"
SH
    chmod +x "$APP/Contents/MacOS/NoteFall"
    "$TOOL_PY" -c "from notefall.icon import save_icons; save_icons('$APP/Contents/Resources/icon')" || true
    cat > "$APP/Contents/Info.plist" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>NoteFall</string>
  <key>CFBundleIdentifier</key><string>io.github.suma-udd.notefall</string>
  <key>CFBundleExecutable</key><string>NoteFall</string>
  <key>CFBundleIconFile</key><string>icon.icns</string>
  <key>CFBundlePackageType</key><string>APPL</string>
</dict></plist>
PL
    ;;
*)
    APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
    ICON="${XDG_DATA_HOME:-$HOME/.local/share}/icons/notefall"
    say "Adding NoteFall to your app menu"
    mkdir -p "$APPS" "$(dirname "$ICON")"
    "$TOOL_PY" -c "from notefall.icon import save_icons; save_icons('$ICON')" || true
    cat > "$APPS/notefall.desktop" <<DT
[Desktop Entry]
Type=Application
Name=NoteFall
Comment=Turn piano music into a falling notes video
Exec=$BIN_DIR/notefall-app
Icon=$ICON.png
Categories=AudioVideo;Music;
Terminal=false
DT
    ;;
esac

say "Done! Open NoteFall from your apps, or type: notefall song.mid"
if ! command -v notefall >/dev/null 2>&1; then
    echo "   (open a new terminal first so the notefall command is found)"
fi
