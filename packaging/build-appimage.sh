#!/bin/bash
#
# Build a self-contained AppImage: Python, PySide6 and the application in one
# executable file that runs on any reasonably current x86_64 Linux.
#
# This is the counterpart to the .deb. The .deb is right on Debian, where Qt
# is already installed and maintained; the AppImage is for everywhere else,
# and pays about 150 MB for the privilege of not caring what is installed.
#
# The interpreter is a python-build-standalone build, fetched through uv.
# That is the only kind of CPython that is genuinely relocatable -- a system
# python or a venv has its own prefix compiled or written in, and moving it
# into an AppDir leaves it looking for a directory that does not exist on the
# user's machine.
#
# PySide6-Essentials, not PySide6: Essentials carries QtCore, QtGui,
# QtWidgets, QtQml and QtQuick, which is everything this application imports.
# The full package adds Charts, 3D, WebEngine and more, none of which is used
# and all of which would be carried by every user forever.
#
# Usage: packaging/build-appimage.sh [output-directory]
#
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/.." && pwd)
out=${1:-$root/dist}
work=${APPIMAGE_WORKDIR:-$(mktemp -d)}
python_version=${APPIMAGE_PYTHON:-3.12}

version=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$root/lmssdr/__init__.py")
[ -n "$version" ] || { echo "error: no version in lmssdr/__init__.py" >&2; exit 1; }

command -v uv >/dev/null || { echo "error: uv is required" >&2; exit 1; }

appdir="$work/AppDir"
rm -rf "$appdir"
mkdir -p "$appdir/usr"

echo "Building lmssdr $version AppImage in $work"

# -- a relocatable interpreter --------------------------------------------

uv python install --managed-python "$python_version" >/dev/null
pybin=$(uv python find --managed-python "$python_version")
pyroot=$(cd "$(dirname "$pybin")/.." && pwd)
echo "  interpreter: $pyroot"
cp -a "$pyroot/." "$appdir/usr/"

# uv marks its managed interpreters EXTERNALLY-MANAGED so that nothing
# installs into the shared copy by accident. This is not that copy: it is a
# private one inside the AppDir whose whole purpose is to be installed into.
find "$appdir/usr" -name EXTERNALLY-MANAGED -delete

# -- the application and its one dependency -------------------------------

uv pip install --python "$appdir/usr/bin/python3" --no-cache \
    "PySide6-Essentials>=6.6" >/dev/null
uv pip install --python "$appdir/usr/bin/python3" --no-cache --no-deps \
    "$root" >/dev/null

site=$(echo "$appdir"/usr/lib/python*/site-packages)
[ -d "$site/lmssdr" ] || { echo "error: lmssdr did not install" >&2; exit 1; }
[ -d "$site/PySide6" ] || { echo "error: PySide6 did not install" >&2; exit 1; }

# Qt ships every module's translations, QML tooling and test/debug binaries.
# None of it is reachable from this application, and it is a third of the
# uncompressed size.
rm -rf "$site/PySide6/Qt/translations" \
       "$site/PySide6/Qt/libexec" \
       "$site/PySide6/Qt/qml/QtTest" \
       "$site/PySide6"/{assistant,designer,linguist,lrelease,lupdate,qmlls,qmlformat,qmllint,balsam,qsb} \
       "$site"/PySide6/Qt/plugins/{sqldrivers,qmltooling,designer}
find "$appdir/usr" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
find "$appdir/usr" -name '*.pyc' -delete 2>/dev/null || true

# -- AppDir metadata ------------------------------------------------------

# The desktop file and icon must sit at the AppDir root; appimagetool reads
# them there and the shell shows them after integration.
install -m 0644 "$here/lmssdr.desktop" "$appdir/lmssdr.desktop"
install -m 0644 "$here/icons/256x256/lmssdr.png" "$appdir/lmssdr.png"
install -D -m 0644 "$here/lmssdr.desktop" \
    "$appdir/usr/share/applications/lmssdr.desktop"
for dir in "$here"/icons/*x*; do
    size=$(basename "$dir")
    for icon in "$dir"/*.png; do
        install -D -m 0644 "$icon" \
            "$appdir/usr/share/icons/hicolor/$size/apps/$(basename "$icon")"
    done
done

# The privileged helper cannot work from inside an AppImage -- polkit
# identifies the program by an absolute path that must exist before the
# action is invoked, and a mount point that changes every run is not that.
# Shipped so the user can install it once from the extracted AppDir.
install -D -m 0755 "$here/polkit/lmssdr-module-helper" \
    "$appdir/usr/share/lmssdr/polkit/lmssdr-module-helper"
install -D -m 0644 "$here/polkit/org.atmanactive.lmssdr.policy" \
    "$appdir/usr/share/lmssdr/polkit/org.atmanactive.lmssdr.policy"
install -D -m 0755 "$here/install-polkit.sh" \
    "$appdir/usr/share/lmssdr/install-polkit.sh"
install -D -m 0755 "$here/install-icons.sh" \
    "$appdir/usr/share/lmssdr/install-icons.sh"
cp -a "$here/icons" "$appdir/usr/share/lmssdr/icons"

cat > "$appdir/AppRun" <<'EOF'
#!/bin/sh
# AppRun - entry point. $APPDIR is where the image is mounted this run, so
# every path here is derived from it and nothing is baked in at build time.
set -eu
HERE=$(dirname "$(readlink -f "$0")")

export PATH="$HERE/usr/bin:${PATH:-}"
# Icons: without this the tray falls back to pixmap data and stops changing
# colour, and the window has no icon at all. The user's own themes come
# first, so packaging/install-icons.sh still wins if it has been run.
export XDG_DATA_DIRS="${XDG_DATA_HOME:-$HOME/.local/share}:$HERE/usr/share:${XDG_DATA_DIRS:-/usr/local/share:/usr/share}"

# Qt's own plugin discovery looks next to the binary, which here is the
# interpreter, not PySide6. Point it at the bundled copy explicitly.
site=$(echo "$HERE"/usr/lib/python*/site-packages)
if [ -d "$site/PySide6/Qt/plugins" ]; then
    export QT_PLUGIN_PATH="$site/PySide6/Qt/plugins"
fi
if [ -d "$site/PySide6/Qt/qml" ]; then
    export QML2_IMPORT_PATH="$site/PySide6/Qt/qml"
fi

exec "$HERE/usr/bin/python3" -m lmssdr "$@"
EOF
chmod 0755 "$appdir/AppRun"

# -- package --------------------------------------------------------------

tool="$work/appimagetool"
if [ ! -x "$tool" ]; then
    echo "  fetching appimagetool"
    curl -fsSL -o "$tool" \
        "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"
    chmod +x "$tool"
fi

mkdir -p "$out"
image="$out/lmssdr-${version}-x86_64.AppImage"
# --appimage-extract-and-run because appimagetool is itself an AppImage and
# CI runners have no FUSE. ARCH is not inferred when the tool is extracted.
ARCH=x86_64 "$tool" --appimage-extract-and-run \
    --no-appstream "$appdir" "$image" >/dev/null 2>&1 || {
        echo "error: appimagetool failed" >&2
        ARCH=x86_64 "$tool" --appimage-extract-and-run --no-appstream "$appdir" "$image"
        exit 1
    }
chmod +x "$image"

echo "Built $image ($(du -h "$image" | cut -f1))"
[ -n "${APPIMAGE_WORKDIR:-}" ] || rm -rf "$work"
