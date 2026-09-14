#!/bin/sh
#
# Install the application and tray icons into an icon theme.
#
# This is what makes the tray colour actually change on KDE Plasma. Plasma's
# tray speaks StatusNotifierItem, which carries a themed icon by *name* and
# lets the shell load it; an icon built from a file has to travel as pixmap
# data instead, and the shell will often not refresh that when it changes. So
# without these files the icon is drawn once and then stays put, whatever the
# microphone is doing.
#
# Installs per-user by default -- no root, and it is a per-user application.
# Pass --system to install for everyone.
#
set -eu
here=$(cd "$(dirname "$0")" && pwd)
source_dir="$here/icons"

target="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor"
scope="for this user"
if [ "${1:-}" = "--system" ]; then
    target=/usr/share/icons/hicolor
    scope="system-wide"
fi

[ -d "$source_dir" ] || {
    echo "error: $source_dir is missing. Run packaging/make-icons.py first." >&2
    exit 1
}

count=0
for dir in "$source_dir"/*x*; do
    size=$(basename "$dir")
    install -d "$target/$size/apps"
    for icon in "$dir"/*.png; do
        install -m 0644 "$icon" "$target/$size/apps/$(basename "$icon")"
        count=$((count + 1))
    done
done

# Refresh the caches, where the tools exist. Both are optional: the icons
# work without a cache, just with a slower first lookup.
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -q -t -f "$target" 2>/dev/null || true
fi
if command -v kbuildsycoca6 >/dev/null 2>&1; then
    kbuildsycoca6 --noincremental >/dev/null 2>&1 || true
elif command -v kbuildsycoca5 >/dev/null 2>&1; then
    kbuildsycoca5 --noincremental >/dev/null 2>&1 || true
fi

echo "Installed $count icon files $scope into $target"
echo "Restart the application so the tray picks up the themed icons."
