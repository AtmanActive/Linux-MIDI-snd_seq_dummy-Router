"""System tray icon.

Not a convenience: this application is resident by design. The routing it
applies lives in the kernel and outlives the process, but the mute rules and
the re-application of routing after a module reload do not, so the tray is
the honest way to show that it is running rather than lurking invisibly.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Slot
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from .. import APP_HOMEPAGE, APP_TITLE, __version__
from ..resources import (STATE_IDLE, STATE_MUTED, STATE_TALKBACK,
                         STATE_UNMUTED, app_icon, state_icon)

logger = logging.getLogger(__name__)


def tray_colour(mute_enabled: bool, mute_running: bool, mute_state: str):
    """Which icon colour a state deserves, or None for the plain icon.

    Only the mute feature colours the tray, and only while it is actually
    listening: a coloured icon has to mean something, and "the application is
    open" is not worth a colour.

    While listening, blue is the starting point and stays until a transport
    message arrives. Red, green and purple each assert something about the
    microphone, and none of them is true yet at that point.
    """
    if not mute_enabled or not mute_running:
        return None
    return {"idle": STATE_IDLE,
            "muted": STATE_MUTED,
            "talkback": STATE_TALKBACK,
            "open": STATE_UNMUTED}.get(mute_state)


class Tray(QObject):
    def __init__(self, bridge, window, parent=None):
        super().__init__(parent)
        self._bridge = bridge
        self._window = window
        self._icon = QSystemTrayIcon(app_icon(), self)
        self._icon.setToolTip(APP_TITLE)
        self._menu = QMenu()
        self._build()
        self._icon.setContextMenu(self._menu)
        self._icon.activated.connect(self._on_activated)
        self._icon.show()

        bridge.moduleChanged.connect(self._sync)
        bridge.portsChanged.connect(self._sync)
        bridge.muteChanged.connect(self._sync)
        self._colour = ""
        self._sync()

    def _build(self) -> None:
        show = QAction("Show window", self)
        show.triggered.connect(self._show_window)
        self._menu.addAction(show)
        self._menu.addSeparator()

        self._status = QAction("", self)
        self._status.setEnabled(False)
        self._menu.addAction(self._status)
        self._menu.addSeparator()

        about = QAction(f"{APP_TITLE} {__version__}…", self)
        about.setToolTip(APP_HOMEPAGE)
        about.triggered.connect(self._bridge.openHomepage)
        self._menu.addAction(about)

        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self._quit)
        self._menu.addAction(quit_action)

    @Slot()
    def _sync(self) -> None:
        count = self._bridge.livePortCount
        self._status.setText(f"{count} MIDI port{'' if count == 1 else 's'}")
        self._apply_icon(tray_colour(self._bridge.muteEnabled,
                                     self._bridge.muteRunning,
                                     self._bridge.muteState))
        self._icon.setToolTip(self._tooltip())

    def _tooltip(self) -> str:
        if self._bridge.sequencerError:
            return f"{APP_TITLE} — no ALSA sequencer"
        if not self._bridge.moduleMatches:
            return f"{APP_TITLE} — port count not applied"
        if self._bridge.muteEnabled and self._bridge.muteRunning:
            return {"idle": f"{APP_TITLE} — waiting for transport",
                    "muted": f"{APP_TITLE} — microphone muted",
                    "talkback": f"{APP_TITLE} — talkback",
                    "open": f"{APP_TITLE} — microphone live",
                    }.get(self._bridge.muteState, APP_TITLE)
        return f"{APP_TITLE} — {self._bridge.livePortCount} ports"

    def _apply_icon(self, colour) -> None:
        if (colour or "") == self._colour:
            return
        self._colour = colour or ""
        icon = state_icon(colour)
        # The name is what matters on Plasma: an icon with one travels to the
        # shell by name and is re-read on change, while a nameless icon goes
        # as pixmap data that the shell may never refresh. Logged so a tray
        # that will not change colour can be diagnosed in one line.
        logger.info("tray icon -> %s (themed name=%r, null=%s)",
                    colour or "default", icon.name(), icon.isNull())
        self._icon.setIcon(icon)

    def _on_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.Trigger:
            self._show_window()

    def _show_window(self) -> None:
        self._window.show()
        self._window.raise_()
        self._window.requestActivate()

    def _quit(self) -> None:
        from PySide6.QtWidgets import QApplication
        self._bridge.stop()
        QApplication.instance().quit()
