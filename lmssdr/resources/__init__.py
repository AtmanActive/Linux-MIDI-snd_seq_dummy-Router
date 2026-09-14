"""Bundled assets."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

RESOURCE_DIR = Path(__file__).parent
ICON_NAME = "lmssdr"
ICON_FILE = RESOURCE_DIR / f"{ICON_NAME}.png"

#: Tray colours. These mirror MIDI-Transport-to-Mute so the states read the
#: same way to anyone who used it: green unmuted, red muted, purple talkback.
#: They are an identity, not decoration, so nothing in the palette may
#: override them.
#:
#: Blue is the addition: the listener is running but has not heard a transport
#: message yet, so it does not yet know where the DAW is. Green would be a
#: claim, and an unverified one -- blue says "watching, nothing heard".
STATE_IDLE = "blue"
STATE_UNMUTED = "green"
STATE_MUTED = "red"
STATE_TALKBACK = "purple"

_ICON_CACHE: dict = {}


def ensure_theme_search_paths() -> None:
    """Make sure Qt looks where install-icons.sh puts things.

    Plasma normally configures this, but a checkout run under an unusual
    session -- or any platform plugin that does not set up an icon theme --
    ends up searching only ``:/icons`` and never finds the installed files.
    Then every icon falls back to a bundled QIcon, which reaches the tray as
    pixmap data rather than a name, and the colour stops updating.
    """
    from PySide6.QtGui import QIcon

    data_home = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local/share")
    data_dirs = (os.environ.get("XDG_DATA_DIRS")
                 or "/usr/local/share:/usr/share").split(":")
    paths = QIcon.themeSearchPaths()
    for base in [data_home, *data_dirs]:
        candidate = str(Path(base) / "icons")
        if candidate not in paths:
            paths.append(candidate)
    QIcon.setThemeSearchPaths(paths)
    if not QIcon.fallbackThemeName():
        # hicolor is where install-icons.sh writes, and the spec says every
        # theme falls back to it.
        QIcon.setFallbackThemeName("hicolor")


def icon_file(colour: Optional[str] = None) -> Path:
    """Path to a colour variant, or the default icon when colour is None."""
    if not colour:
        return ICON_FILE
    candidate = RESOURCE_DIR / f"{ICON_NAME}-{colour}.png"
    return candidate if candidate.exists() else ICON_FILE


def icon_theme_name(colour: Optional[str] = None) -> str:
    return ICON_NAME if not colour else f"{ICON_NAME}-{colour}"


def state_icon(colour: Optional[str] = None):
    """A QIcon for one state, cached so tray updates cost nothing.

    Prefers the installed theme icon. KDE's tray uses StatusNotifierItem,
    which passes a themed icon by *name* and lets the shell load it; a QIcon
    built from a bare file has to travel as pixmap data instead, which some
    shells will not refresh on change. Installing the variants into hicolor
    is therefore what makes the tray colour actually update on Plasma.
    """
    from PySide6.QtGui import QIcon

    key = colour or ""
    icon = _ICON_CACHE.get(key)
    if icon is None:
        icon = QIcon.fromTheme(icon_theme_name(colour))
        if icon.isNull():
            icon = QIcon(str(icon_file(colour)))
        _ICON_CACHE[key] = icon
    return icon


def app_icon():
    """The application icon, preferring the installed theme icon."""
    from PySide6.QtGui import QIcon

    themed = QIcon.fromTheme(ICON_NAME)
    if not themed.isNull():
        return themed
    return QIcon(str(ICON_FILE))
