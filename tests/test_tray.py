"""Tray icon colour selection.

A plain function precisely so it can be tested headlessly: the offscreen
platform reports no system tray, so the Tray object is never constructed in
an automated run and nothing inside it is covered.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest                                            # noqa: E402

from lmssdr.resources import (STATE_IDLE, STATE_MUTED, STATE_TALKBACK,  # noqa: E402
                              STATE_UNMUTED)
from lmssdr.ui.tray import tray_colour                     # noqa: E402


@pytest.mark.parametrize("state, expected", [
    ("idle", STATE_IDLE),
    ("muted", STATE_MUTED),
    ("talkback", STATE_TALKBACK),
    ("open", STATE_UNMUTED),
])
def test_running_states_have_colours(state, expected):
    assert tray_colour(True, True, state) == expected


def test_idle_is_not_the_plain_icon():
    """Blue while listening, plain while not: two different things."""
    assert tray_colour(True, True, "idle") == STATE_IDLE
    assert tray_colour(False, False, "idle") is None


def test_no_colour_when_the_feature_is_off():
    assert tray_colour(False, True, "muted") is None


def test_no_colour_when_it_is_not_listening():
    """Enabled but not running is not a state worth colouring."""
    assert tray_colour(True, False, "muted") is None


def test_an_unknown_state_falls_back_to_the_plain_icon():
    assert tray_colour(True, True, "something else") is None


# -- the real object ------------------------------------------------------
#
# QSystemTrayIcon.isSystemTrayAvailable() is False under the offscreen
# platform, so app.py never builds a Tray in a headless run and nothing in it
# is exercised. It can still be *constructed* there, though -- and doing so
# would have caught `self._colour()` calling a string, which shipped because
# every automated run skipped this class entirely.

@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def tray(qapp):
    from PySide6.QtCore import QObject
    from lmssdr.core.module import ModuleState
    from lmssdr.core.settings import Settings
    from lmssdr.ui.bridge import Bridge
    from lmssdr.ui.tray import Tray

    class FakeWindow(QObject):
        def show(self): pass
        def raise_(self): pass
        def requestActivate(self): pass

    bridge = Bridge(Settings())               # not started: no sequencer needed
    # Pin the kernel state. Left alone, it is read from /sys/module, so the
    # tray's tooltip would depend on whether the machine running the tests
    # happens to have snd_seq_dummy loaded with a matching port count --
    # true on a developer's desktop, false on every CI runner, and the
    # tooltip says something different in each case.
    bridge._module_state = ModuleState(loaded=True, duplex=False,
                                       ports=bridge._settings.port_count)
    return Tray(bridge, FakeWindow()), bridge


def test_tray_builds_and_syncs(tray):
    widget, _ = tray
    widget._sync()                            # must not raise


def test_tray_follows_the_mute_state(tray):
    widget, bridge = tray
    bridge._settings.mute_enabled = True
    bridge._mute._engine.playing = True
    # _sync reads muteRunning, which is False here, so the icon stays plain.
    widget._sync()
    assert widget._colour == ""


def test_tray_tooltip_mentions_the_port_count(tray):
    widget, bridge = tray
    bridge._live_ports = [0, 1, 2]
    assert "ports" in widget._tooltip()


# -- themed icons ---------------------------------------------------------
#
# The tray colour only changes on Plasma if the icon carries a *name*: a
# named icon travels to the shell by name and is re-read, a nameless one goes
# as pixmap data the shell may never refresh. These check the plumbing that
# makes a name available.

def test_theme_search_paths_include_the_user_icon_directory(qapp, tmp_path,
                                                            monkeypatch):
    from PySide6.QtGui import QIcon
    from lmssdr.resources import ensure_theme_search_paths
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    ensure_theme_search_paths()
    assert str(tmp_path / "icons") in QIcon.themeSearchPaths()


def test_a_fallback_theme_is_set(qapp):
    from PySide6.QtGui import QIcon
    from lmssdr.resources import ensure_theme_search_paths
    ensure_theme_search_paths()
    assert QIcon.fallbackThemeName() != ""


def test_every_state_has_its_own_icon_file():
    """A missing variant silently falls back to the default icon, which looks
    like the colour simply not changing."""
    from lmssdr.resources import icon_file
    seen = set()
    for colour in (None, STATE_IDLE, STATE_UNMUTED, STATE_MUTED,
                   STATE_TALKBACK):
        path = icon_file(colour)
        assert path.exists(), path
        seen.add(path.name)
    assert len(seen) == 5, f"variants collapsed to {seen}"


def test_packaged_theme_sizes_exist():
    """The tray uses a small size; downscaling 256px artwork looks wrong."""
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / "packaging" / "icons"
    for size in (16, 22, 24, 32, 48):
        assert (root / f"{size}x{size}" / "lmssdr-red.png").exists(), size


# -- state changes must reach the GUI thread ------------------------------

def test_mute_state_change_reaches_the_gui_thread(qapp):
    """The listener runs in its own thread with no Qt event loop.

    A QTimer.singleShot bounce there never fires, so the signal was never
    emitted and the tray icon never changed colour -- the failure this pins.
    """
    import threading
    from PySide6.QtCore import QCoreApplication
    from lmssdr.core.settings import Settings
    from lmssdr.ui.bridge import Bridge

    bridge = Bridge(Settings())
    fired = []
    bridge.muteChanged.connect(lambda: fired.append(bridge.muteState))

    # Call the service's callback the way its thread does.
    done = threading.Event()

    def worker():
        bridge._mute._notify()
        done.set()

    threading.Thread(target=worker).start()
    done.wait(2.0)
    # Queued across threads, so it lands when the event loop next runs.
    QCoreApplication.processEvents()
    assert fired, "muteChanged did not reach the GUI thread"


def test_tray_icon_changes_with_the_mute_state(tray):
    """End to end through the tray object, not just the colour function."""
    widget, bridge = tray
    bridge._settings.mute_enabled = True
    # Stand in for a running listener.
    bridge._mute._thread = type("T", (), {"is_alive": staticmethod(lambda: True)})()
    seen = []
    # Starts before anything has been heard, hence the leading `seen=False`.
    for heard, playing, talkback in [(False, False, False), (True, False, False),
                                     (True, True, False), (True, True, True)]:
        bridge._mute._engine.seen = heard
        bridge._mute._engine.playing = playing
        bridge._mute._engine.talkback = talkback
        widget._sync()
        seen.append(widget._colour)
    bridge._mute._thread = None
    assert seen == ["blue", "green", "red", "purple"]


def test_the_tray_starts_blue_once_the_listener_is_up(tray):
    """What the user sees at startup: listening, nothing heard, blue."""
    widget, bridge = tray
    bridge._settings.mute_enabled = True
    bridge._mute._thread = type("T", (), {"is_alive": staticmethod(lambda: True)})()
    widget._sync()
    assert widget._colour == "blue"
    assert "waiting" in widget._tooltip().lower()
    bridge._mute._thread = None
