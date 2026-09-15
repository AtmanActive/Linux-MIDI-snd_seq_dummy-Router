"""The object QML talks to.

Everything stateful lives in `core`; this is a thin adapter that exposes it
as Qt properties and slots. The split is deliberate -- `core` has no Qt
import, so the interesting logic stays testable without a display.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from pathlib import Path
import webbrowser
from typing import Dict, List, Optional

from PySide6.QtCore import (Property, QObject, Qt, QTimer, QUrl, Signal,
                            Slot)
from PySide6.QtGui import QGuiApplication

from .. import APP_HOMEPAGE, APP_TITLE, __version__
from ..core import archive, audio, autostart, module
from ..core.mute import MuteRules, MuteService
from ..core.alsaseq import AlsaSeqError, Seq
from ..core.ports import (PORT_COLOUR_NAMES, PORT_COLOURS, PortNames,
                          colour_hex, matches as port_matches)
from ..core.routing import (Link, Routing, adopt, apply as apply_routing,
                            export_links, forget_inactive, live_links,
                            set_link)
from ..core.settings import Settings
from . import theming
from .portmodel import PortListModel

logger = logging.getLogger(__name__)

#: How often to re-read the sequencer graph. Ports appear and disappear only
#: when the module is reloaded or another application starts, so this is a
#: safety net rather than the main path -- explicit refreshes cover the rest.
POLL_MS = 4000


class Bridge(QObject):
    # -- notifications ---------------------------------------------------
    paletteChanged = Signal()
    fontScaleChanged = Signal()
    settingsChanged = Signal()
    portsChanged = Signal()
    routingChanged = Signal()
    filtersChanged = Signal()
    moduleChanged = Signal()
    busyChanged = Signal()

    errorRaised = Signal(str)
    noticeRaised = Signal(str)
    foundRoutesOnStart = Signal(int)
    routeAdded = Signal(int, int)
    muteChanged = Signal()
    #: An archive was opened and holds this many of our files.
    archiveOpened = Signal(int)
    #: An archive cannot be used, with the reason. A dialog, not a toast:
    #: the user asked for something and it did not happen.
    archiveRejected = Signal(str)
    archiveChanged = Signal()
    showWindowRequested = Signal()
    hideWindowRequested = Signal()

    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._names = PortNames.load()
        self._routing = Routing.load()
        self._live_links: set = set()
        # Search boxes. Not persisted: a filter is a way of looking at the
        # data right now, and reopening the app to a hidden half of your
        # ports with no obvious reason why is a bad surprise.
        self._ports_filter = ""
        self._filter_from = ""
        self._filter_to = ""
        # QML binds to this model object once and keeps it. Handing the view
        # a fresh array on every edit would reset it and scroll to the top.
        self._ports_model = PortListModel(self)

        #: Created on demand, for the Mute page's test buttons.
        self._send_port: Optional[int] = None

        #: What the last opened archive holds, between the file dialog and
        #: the user's choice of what to take from it.
        self._archive_items: List[archive.ArchiveItem] = []
        self._archive_name = ""

        # The mute listener runs in its own thread and calls back from there.
        # Emitting the signal straight from that thread IS the bounce: Qt
        # delivers it to slots in the GUI thread through a queued connection,
        # because the threads differ.
        #
        # QTimer.singleShot must not be used here. It creates a timer owned by
        # the calling thread, and the listener thread has no event loop to run
        # it -- so the callback never fires, the signal is never emitted, and
        # the tray never hears that the microphone was muted.
        self._mute = MuteService(on_change=lambda state: self.muteChanged.emit())
        self._seq: Optional[Seq] = None
        self._seq_error = ""
        self._live_ports: List[int] = []
        self._module_state = module.read_state()
        self._busy = False
        self._dark = self._detect_dark()

        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self.refresh)

        # Follow the desktop's light/dark switch while the mode is "system".
        hints = QGuiApplication.styleHints()
        if hasattr(hints, "colorSchemeChanged"):
            hints.colorSchemeChanged.connect(self._on_scheme_changed)

    # -- lifecycle -------------------------------------------------------

    def start(self) -> None:
        self._open_sequencer()
        self.refresh()
        self._sync_ports_model()
        if self._settings.restore_routing_on_start:
            self._restore_routing()
        self._offer_to_record_found_routes()
        self._configure_mute()
        if self._settings.mute_enabled:
            if not self._mute.start():
                logger.warning("mute listener did not start: %s",
                               self._mute.error)
        # Whether it started or not, the interface has to hear about it:
        # muteRunning and muteError both changed, and without this the Mute
        # page keeps showing the state it was constructed with.
        self.muteChanged.emit()
        self._timer.start()

    def _restore_routing(self) -> None:
        """Re-assert saved routes at start-up, authoritatively.

        Same rule as the Apply button: the saved routing describes what
        should be connected, so a dummy-to-dummy connection that is not in it
        is stale and gets removed. Without that, a connection nobody
        remembers making survives every restart and the matrix never settles.

        One exception, and it is deliberate: when *nothing* is saved this
        does nothing at all rather than disconnecting everything. An empty
        routing file is the first-run state, not an instruction to wipe a
        setup the user built with aconnect before installing this. Pressing
        Apply with an empty routing still sweeps -- that is an explicit act.
        """
        if self._seq is None or not len(self._routing):
            return
        report = apply_routing(self._seq, self._routing, remove_extra=True)
        self.refresh()
        self.routingChanged.emit()
        if report.changed or report.skipped or report.failed:
            logger.info("routing restored: %s", report.summary())
        # Removals are the surprising half, so they are the half that is
        # said out loud. The log carries the rest.
        if report.removed:
            self.noticeRaised.emit(
                f"{len(report.removed)} connection"
                f"{'' if len(report.removed) == 1 else 's'} not in the saved "
                f"routing "
                f"{'was' if len(report.removed) == 1 else 'were'} removed.")
        if report.failed:
            self.errorRaised.emit("Some saved routes could not be applied: "
                                  + "; ".join(report.failed[:3]))

    def stop(self) -> None:
        # Before anything else: hand the microphone back. Quitting mid-take
        # must not leave it muted.
        self._mute.stop()
        self._timer.stop()
        if self._seq is not None:
            self._seq.close()
            self._seq = None

    def _open_sequencer(self) -> None:
        try:
            self._seq = Seq(APP_TITLE)
            self._seq_error = ""
        except AlsaSeqError as exc:
            self._seq = None
            self._seq_error = str(exc)
            logger.error("cannot open the ALSA sequencer: %s", exc)

    def _offer_to_record_found_routes(self) -> None:
        """Tell the user about connections that predate any saved routing.

        This is the only moment the application can still see routes that
        were built before it was installed. As soon as anything is saved,
        start-up becomes authoritative and sweeps them -- so if they are
        going to be written down at all, it has to be now.
        """
        if not self._settings.warn_about_found_routes:
            return
        if len(self._routing) or not self._live_links:
            return
        self.foundRoutesOnStart.emit(len(self._live_links))

    @Slot(bool)
    def dismissFoundRoutes(self, never_again: bool) -> None:
        if never_again:
            self._settings.warn_about_found_routes = False
            self._save_settings()

    @Slot(str, result=bool)
    def exportFoundRoutes(self, file_url: str) -> bool:
        """Write the current connections to a file the user picked."""
        path = QUrl(file_url).toLocalFile() if file_url.startswith("file:") \
            else file_url
        if not path:
            self.errorRaised.emit("No file was chosen.")
            return False
        try:
            count = export_links(
                Path(path), self._live_links,
                name_for=lambda n: self._names.get(n).display_name)
        except OSError as exc:
            self.errorRaised.emit(f"Could not write {path}: {exc}")
            return False
        self.noticeRaised.emit(
            f"{count} connection{'' if count == 1 else 's'} written to {path}")
        return True

    @Property(str, constant=True)
    def suggestedExportName(self) -> str:
        stamp = datetime.now().strftime("%Y-%m-%d")
        return f"lmssdr.found-routes.{stamp}.json"

    # -- appearance ------------------------------------------------------

    @staticmethod
    def _detect_dark() -> bool:
        hints = QGuiApplication.styleHints()
        scheme = getattr(hints, "colorScheme", None)
        if scheme is None:
            return True
        return scheme() == Qt.ColorScheme.Dark

    def _on_scheme_changed(self, *_) -> None:
        self._dark = self._detect_dark()
        if self._settings.theme_mode == "system":
            self.paletteChanged.emit()

    @Property("QVariant", notify=paletteChanged)
    def palette(self) -> Dict[str, str]:
        dark = theming.resolve_mode(self._settings.theme_mode, self._dark)
        return theming.build_palette(self._settings.theme_name, dark)

    @Property(float, notify=fontScaleChanged)
    def fontScale(self) -> float:
        return theming.TEXT_SIZES.get(self._settings.text_size, 1.0)

    @Property("QVariant", constant=True)
    def themeNames(self) -> List[str]:
        return theming.THEME_NAMES

    @Property("QVariant", constant=True)
    def textSizeNames(self) -> List[str]:
        return theming.TEXT_SIZE_NAMES

    @Property(str, notify=settingsChanged)
    def themeMode(self) -> str:
        return self._settings.theme_mode

    @Property(str, notify=settingsChanged)
    def themeName(self) -> str:
        return self._settings.theme_name

    @Property(str, notify=settingsChanged)
    def textSize(self) -> str:
        return self._settings.text_size

    @Slot(str)
    def setThemeMode(self, mode: str) -> None:
        if mode in theming.MODES and mode != self._settings.theme_mode:
            self._settings.theme_mode = mode
            self._save_settings()
            self.paletteChanged.emit()

    @Slot(str)
    def setThemeName(self, name: str) -> None:
        if name in theming.THEMES and name != self._settings.theme_name:
            self._settings.theme_name = name
            self._save_settings()
            self.paletteChanged.emit()

    @Slot(str)
    def setTextSize(self, size: str) -> None:
        if size in theming.TEXT_SIZES and size != self._settings.text_size:
            self._settings.text_size = size
            self._save_settings()
            self.fontScaleChanged.emit()

    def _save_settings(self) -> None:
        self._settings.save()
        self.settingsChanged.emit()

    # -- identity --------------------------------------------------------

    @Property(str, constant=True)
    def appName(self) -> str:
        return APP_TITLE

    @Property(str, constant=True)
    def appVersion(self) -> str:
        return __version__

    @Property(str, constant=True)
    def homepage(self) -> str:
        return APP_HOMEPAGE

    # -- general settings ------------------------------------------------

    @Property(int, constant=True)
    def windowWidth(self) -> int:
        """Constant on purpose: this seeds the window, it does not drive it.

        A notifying property here would fight the user -- every resize would
        write the setting, the setting would push a new width back, and the
        window would judder or refuse to be dragged smaller.
        """
        return max(480, self._settings.window_width)

    @Property(int, constant=True)
    def windowHeight(self) -> int:
        return max(360, self._settings.window_height)

    @Slot(int, int)
    def saveWindowSize(self, width: int, height: int) -> None:
        if width < 480 or height < 360:
            return                      # a minimised or collapsed window
        if (width, height) == (self._settings.window_width,
                               self._settings.window_height):
            return
        self._settings.window_width = int(width)
        self._settings.window_height = int(height)
        self._settings.save()           # no settingsChanged: nothing rebinds

    @Property(bool, notify=settingsChanged)
    def startMinimised(self) -> bool:
        return self._settings.start_minimised

    @Slot(bool)
    def setStartMinimised(self, value: bool) -> None:
        self._settings.start_minimised = bool(value)
        self._save_settings()

    @Property(bool, notify=settingsChanged)
    def autostart(self) -> bool:
        return autostart.is_enabled()

    @Slot(bool)
    def setAutostart(self, value: bool) -> None:
        autostart.set_enabled(bool(value))
        self.settingsChanged.emit()

    # -- the kernel module -----------------------------------------------

    @Property(int, notify=settingsChanged)
    def portCount(self) -> int:
        """How many ports the user wants."""
        return self._settings.port_count

    @Slot(int)
    def setPortCount(self, value: int) -> None:
        value = module.clamp_ports(value)
        if value != self._settings.port_count:
            self._settings.port_count = value
            self._save_settings()
            self._sync_ports_model()
            self.portsChanged.emit()

    @Property(int, notify=moduleChanged)
    def livePortCount(self) -> int:
        """How many ports the kernel is actually providing."""
        return len(self._live_ports)

    @Property(int, constant=True)
    def maxPorts(self) -> int:
        return module.MAX_PORTS

    @Property(str, notify=moduleChanged)
    def moduleSummary(self) -> str:
        return self._module_state.describe()

    @Property(bool, notify=moduleChanged)
    def moduleMatches(self) -> bool:
        """True when the kernel already provides what the settings ask for."""
        return self._module_state.matches(self._settings.port_count)

    @Property(bool, notify=moduleChanged)
    def moduleDuplex(self) -> bool:
        return bool(self._module_state.duplex)

    @Property("QVariant", notify=moduleChanged)
    def conflictingConfigs(self) -> List[str]:
        return [str(p) for p in module.conflicting_configs()]

    @Property(str, notify=settingsChanged)
    def manualCommand(self) -> str:
        return module.manual_command(self._settings.port_count)

    @Property(bool, notify=busyChanged)
    def busy(self) -> bool:
        return self._busy

    def _set_busy(self, value: bool) -> None:
        if value != self._busy:
            self._busy = value
            self.busyChanged.emit()

    @Slot()
    def applyPortCount(self) -> None:
        """Reload the module so the kernel provides `portCount` ports.

        Runs off the GUI thread: pkexec blocks until the user answers the
        password prompt, which can be a long time, and a frozen window during
        an authentication dialog looks like a crash.
        """
        if self._busy:
            return
        wanted = self._settings.port_count
        self._set_busy(True)

        def work() -> None:
            result = module.apply_ports(wanted)
            # Back to the GUI thread. A queued invocation is the only safe way
            # to touch Qt objects from a worker.
            QTimer.singleShot(0, lambda: self._apply_finished(result))

        threading.Thread(target=work, name="lmssdr-apply", daemon=True).start()

    def _apply_finished(self, result: module.ApplyResult) -> None:
        self._set_busy(False)
        self._module_state = result.state or module.read_state()
        self.moduleChanged.emit()
        self.refresh()
        if result.ok:
            self.noticeRaised.emit(
                result.message + "  Restart your browser so it sees the new ports.")
        elif result.cancelled:
            self.noticeRaised.emit(result.message)
        else:
            self.errorRaised.emit(result.message)

    # -- ports -----------------------------------------------------------

    @Property(str, notify=portsChanged)
    def sequencerError(self) -> str:
        return self._seq_error

    @Property(str, notify=filtersChanged)
    def portsFilter(self) -> str:
        return self._ports_filter

    @Slot(str)
    def setPortsFilter(self, text: str) -> None:
        if text != self._ports_filter:
            self._ports_filter = text
            self.filtersChanged.emit()
            self._sync_ports_model()
            self.portsChanged.emit()

    @Property(int, notify=portsChanged)
    def totalPortRowCount(self) -> int:
        """Rows before filtering, so the interface can say "8 of 32"."""
        return len(self._port_rows())

    def _port_rows(self) -> List[int]:
        """Union of live ports, named ports and the configured count."""
        live = set(self._live_ports)
        configured = {info.number for info in self._names.named()}
        return sorted(live | configured | set(range(self._settings.port_count)))

    @Property(QObject, constant=True)
    def portsModel(self) -> PortListModel:
        """The model the ports table binds to. Never replaced."""
        return self._ports_model

    def _sync_ports_model(self) -> None:
        self._ports_model.set_rows(self.ports)

    @Property("QVariant", notify=portsChanged)
    def ports(self) -> List[dict]:
        """One row per port the user has configured or the kernel provides.

        The union of the two, so a port that exists but has no name still
        shows up, and a name for a port that has gone away is not silently
        hidden -- it is marked missing instead.
        """
        live = set(self._live_ports)
        numbers = self._names.filter(self._port_rows(), self._ports_filter)
        rows = []
        for number in numbers:
            info = self._names.get(number)
            rows.append({
                "number": number,
                "kernelName": info.kernel_name,
                "name": info.name,
                "remark": info.remark,
                "displayName": info.display_name,
                "colour": info.colour,
                "colourHex": info.colour_hex,
                "exists": number in live,
            })
        return rows

    @Slot(int, str)
    def setPortName(self, number: int, name: str) -> None:
        if self._names.get(number).name == name.strip():
            return                      # nothing changed; do not disturb the view
        self._names.set_name(number, name)
        self._names.save()
        self._sync_ports_model()
        # Deliberately not portsChanged: that notifies the *row set*, and
        # re-emitting it here is what used to reset the list. The routing
        # page needs the new label, so tell it directly.
        self.routingChanged.emit()

    @Property("QVariant", constant=True)
    def portColourNames(self) -> List[str]:
        return PORT_COLOUR_NAMES

    @Property("QVariant", constant=True)
    def portColours(self) -> dict:
        """Name -> hex, so QML can draw a swatch without a second lookup."""
        return dict(PORT_COLOURS)

    @Slot(int, int, result=bool)
    def swapPorts(self, a: int, b: int) -> bool:
        """Exchange two ports' identities and their routing.

        Everything the user assigned moves -- alias, remark, colour -- and
        every route follows, so a swap is a relabelling of two sockets rather
        than a re-typing of two cards. Saved and applied in one go: a swap
        that left the kernel on the old wiring would be a swap in name only.
        """
        if a == b:
            return False
        live = set(self._live_ports)
        if a not in live or b not in live:
            self.errorRaised.emit("Both ports have to exist to swap them.")
            return False

        before = set(self._routing.links())
        self._names.swap(a, b)
        moved = len(self._routing.swap_ports(a, b))
        after = set(self._routing.links())

        # Apply only what the swap changed. Re-applying the whole routing
        # would also sweep links this app did not make, which is a much
        # bigger action than the user asked for.
        failed = []
        if self._seq is not None:
            for link in sorted(before - after):
                try:
                    set_link(self._seq, link.source, link.dest, False)
                except AlsaSeqError as exc:
                    failed.append(str(exc))
            for link in sorted(after - before):
                try:
                    set_link(self._seq, link.source, link.dest, True)
                except AlsaSeqError as exc:
                    failed.append(str(exc))

        self._names.save()
        self._routing.save()
        self._sync_ports_model()
        self.refresh()
        self.portsChanged.emit()
        self.routingChanged.emit()

        # Count routes, not endpoints: `before ^ after` holds the old and
        # the new form of each one and would report a single moved route as
        # two.
        if failed:
            self.errorRaised.emit("Swapped, but some routes could not be "
                                  "applied: " + "; ".join(failed[:3]))
        else:
            self.noticeRaised.emit(
                f"Ports {a} and {b} swapped"
                + (f", {moved} route{'' if moved == 1 else 's'} moved." if moved
                   else "."))
        return True

    @Slot(int, str)
    def setPortColour(self, number: int, colour: str) -> None:
        """Tag a port with a colour, or untag it with an empty name."""
        if self._names.get(number).colour == colour:
            return
        self._names.set_colour(number, colour)
        self._names.save()
        self._sync_ports_model()
        # The colour shows on every screen, so the routing views need telling
        # even though no route changed.
        self.routingChanged.emit()

    @Slot(int, str)
    def setPortRemark(self, number: int, remark: str) -> None:
        if self._names.get(number).remark == remark.strip():
            return
        self._names.set_remark(number, remark)
        self._names.save()
        self._sync_ports_model()
        self.routingChanged.emit()

    @Slot()
    def refresh(self) -> None:
        """Re-read the module state and the live port list."""
        previous_ports = self._live_ports
        previous_module = self._module_state

        self._module_state = module.read_state()
        if self._seq is None:
            self._open_sequencer()
        if self._seq is not None:
            try:
                ports = self._seq.dummy_ports()
                self._live_ports = sorted(ports)
                links = live_links(self._seq, ports)
                if links != self._live_links:
                    self._live_links = links
                    self.routingChanged.emit()
            except AlsaSeqError as exc:
                logger.warning("could not read the sequencer: %s", exc)
                self._live_ports = []
                self._live_links = set()

        if self._module_state != previous_module:
            self.moduleChanged.emit()
        if self._live_ports != previous_ports:
            self.moduleChanged.emit()
            self._sync_ports_model()
            self.portsChanged.emit()
            # The routing views are keyed off the port list too -- the matrix
            # axes, the graph nodes, the port count. They declare
            # routingChanged as their notifier, so a change to the ports has
            # to say so here or the matrix keeps showing the empty list it
            # was born with.
            self.routingChanged.emit()

    # -- microphone mute -------------------------------------------------

    def _mute_rules(self) -> MuteRules:
        s = self._settings
        return MuteRules(transport_channel=s.mute_transport_channel,
                         play_note=s.mute_play_note,
                         stop_note=s.mute_stop_note,
                         transport_velocity=s.mute_transport_velocity,
                         talkback_channel=s.mute_talkback_channel,
                         talkback_cc=s.mute_talkback_cc)

    def _configure_mute(self) -> None:
        s = self._settings
        # Resolved here, which is the moment the listener is (re)started --
        # so "<default>" means the desktop's default input as of application
        # start or of the last time this feature was switched on.
        resolved = audio.resolve(s.mute_source)
        if s.mute_source == audio.DEFAULT_SOURCE and not resolved:
            self._mute._error = ("The system default input could not be "
                                 "determined.")
        self._mute.configure(
            transport_port=s.mute_transport_port if s.mute_transport_port >= 0 else None,
            talkback_port=s.mute_talkback_port if s.mute_talkback_port >= 0 else None,
            source=resolved, rules=self._mute_rules())

    def _restart_mute(self) -> None:
        """Apply the current settings to the listener."""
        self._mute.stop()
        self._configure_mute()
        if self._settings.mute_enabled:
            if not self._mute.start():
                self.errorRaised.emit(self._mute.error or
                                      "The mute listener could not start.")
        self.muteChanged.emit()

    @Property(bool, notify=muteChanged)
    def muteEnabled(self) -> bool:
        return self._settings.mute_enabled

    @Slot(bool)
    def setMuteEnabled(self, value: bool) -> None:
        if bool(value) == self._settings.mute_enabled:
            return
        self._settings.mute_enabled = bool(value)
        self._save_settings()
        self._restart_mute()

    @Property(str, notify=muteChanged)
    def muteState(self) -> str:
        """"idle", "open", "muted" or "talkback".

        "idle" until the listener recognizes its first transport or talkback
        message; it is the difference between a stopped DAW and a silent one.
        """
        return self._mute.state

    @Property(bool, notify=muteChanged)
    def muteRunning(self) -> bool:
        return self._mute.running

    @Property(str, notify=muteChanged)
    def muteError(self) -> str:
        return self._mute.error

    @Property(bool, constant=True)
    def audioAvailable(self) -> bool:
        return audio.available()

    @Property("QVariant", notify=muteChanged)
    def audioSources(self) -> List[dict]:
        """Choosable inputs, with the system default offered first.

        The default is a choice in its own right rather than a convenience
        that copies a name: a studio machine whose interface is swapped
        should follow the desktop, not keep pointing at the old device.
        """
        choices = [{"name": audio.DEFAULT_SOURCE,
                    "description": "\u2039Default\u203a  \u2014  "
                                   + (audio.describe(audio.DEFAULT_SOURCE)
                                      or "no default input"),
                    "muted": False}]
        choices += [{"name": s.name, "description": s.description,
                     "muted": s.muted} for s in audio.sources()]
        return choices

    @Property(str, notify=muteChanged)
    def muteSourceLabel(self) -> str:
        """What is actually being muted, spelled out.

        With the default chosen, the setting says "<default>" and the device
        it resolved to is the thing the user needs to see.
        """
        if not self._settings.mute_source:
            return ""
        return audio.describe(self._settings.mute_source)

    @Slot(str)
    def sendMuteTest(self, what: str) -> None:
        """Send the real message the rule listens for.

        Deliberately not a shortcut into the engine: the point of a test
        button is to prove the whole path -- the right port, a live
        subscription, a rule that matches, a microphone that responds. Poking
        the state machine directly would pass while the port was wrong.
        """
        s = self._settings
        rules = self._mute_rules()
        spec = {
            "play": ("note", s.mute_transport_port, rules.transport_channel,
                     rules.play_note, rules.transport_velocity),
            "stop": ("note", s.mute_transport_port, rules.transport_channel,
                     rules.stop_note, rules.transport_velocity),
            "talkback_on": ("cc", s.mute_talkback_port, rules.talkback_channel,
                            rules.talkback_cc, 127),
            "talkback_off": ("cc", s.mute_talkback_port, rules.talkback_channel,
                             rules.talkback_cc, 0),
        }.get(what)
        if spec is None:
            return
        kind, port_number, channel, data1, data2 = spec

        if port_number is None or port_number < 0:
            self.errorRaised.emit(
                "Choose a talkback port first." if kind == "cc"
                else "Choose a transport port first.")
            return
        if self._seq is None:
            self.errorRaised.emit("The ALSA sequencer is not available.")
            return

        ports = self._seq.dummy_ports()
        target = ports.get(port_number)
        if target is None:
            self.errorRaised.emit(f"Midi Through Port-{port_number} is not present.")
            return

        try:
            if self._send_port is None:
                self._send_port = self._seq.create_output_port("test")
            self._seq.send(self._send_port, target.addr, kind, channel,
                           data1, data2)
        except AlsaSeqError as exc:
            self.errorRaised.emit(str(exc))
            return

        self.noticeRaised.emit(
            f"Sent {'CC' if kind == 'cc' else 'note'} {data1}={data2} "
            f"on channel {channel} to Midi Through Port-{port_number}.")

    @Property(bool, notify=muteChanged)
    def muteSourceIsDefault(self) -> bool:
        return self._settings.mute_source == audio.DEFAULT_SOURCE

    @Property(str, notify=muteChanged)
    def muteSource(self) -> str:
        return self._settings.mute_source

    @Slot(str)
    def setMuteSource(self, name: str) -> None:
        if name == self._settings.mute_source:
            return
        self._settings.mute_source = name
        self._save_settings()
        self._restart_mute()

    @Property(int, notify=muteChanged)
    def muteTransportPort(self) -> int:
        return self._settings.mute_transport_port

    @Slot(int)
    def setMuteTransportPort(self, number: int) -> None:
        if number == self._settings.mute_transport_port:
            return
        self._settings.mute_transport_port = int(number)
        self._save_settings()
        self._restart_mute()

    @Property(int, notify=muteChanged)
    def muteTalkbackPort(self) -> int:
        return self._settings.mute_talkback_port

    @Slot(int)
    def setMuteTalkbackPort(self, number: int) -> None:
        if number == self._settings.mute_talkback_port:
            return
        self._settings.mute_talkback_port = int(number)
        self._save_settings()
        self._restart_mute()

    @Property("QVariant", notify=muteChanged)
    def muteRuleValues(self) -> dict:
        s = self._settings
        return {"transportChannel": s.mute_transport_channel,
                "playNote": s.mute_play_note,
                "stopNote": s.mute_stop_note,
                "velocity": s.mute_transport_velocity,
                "talkbackChannel": s.mute_talkback_channel,
                "talkbackCc": s.mute_talkback_cc}

    @Slot(str, int)
    def setMuteRule(self, key: str, value: int) -> None:
        field = {"transportChannel": "mute_transport_channel",
                 "playNote": "mute_play_note",
                 "stopNote": "mute_stop_note",
                 "velocity": "mute_transport_velocity",
                 "talkbackChannel": "mute_talkback_channel",
                 "talkbackCc": "mute_talkback_cc"}.get(key)
        if field is None or getattr(self._settings, field) == int(value):
            return
        setattr(self._settings, field, int(value))
        self._save_settings()
        self._restart_mute()

    # -- routing ---------------------------------------------------------

    def _describe(self, numbers: List[int]) -> List[dict]:
        out = []
        for n in numbers:
            info = self._names.get(n)
            out.append({"number": n, "displayName": info.display_name,
                        "kernelName": info.kernel_name, "name": info.name,
                        "remark": info.remark, "colour": info.colour,
                        "colourHex": info.colour_hex,
                        "exists": n in self._live_ports})
        return out

    @Property("QVariant", notify=portsChanged)
    def routablePorts(self) -> List[dict]:
        """Live ports only: you cannot route through a port that is absent."""
        return self._describe(self._live_ports)

    @Property(str, notify=filtersChanged)
    def filterFrom(self) -> str:
        return self._filter_from

    @Property(str, notify=filtersChanged)
    def filterTo(self) -> str:
        return self._filter_to

    @Slot(str)
    def setFilterFrom(self, text: str) -> None:
        if text != self._filter_from:
            self._filter_from = text
            self.filtersChanged.emit()
            self.routingChanged.emit()

    @Slot(str)
    def setFilterTo(self, text: str) -> None:
        if text != self._filter_to:
            self._filter_to = text
            self.filtersChanged.emit()
            self.routingChanged.emit()

    def _source_numbers(self) -> List[int]:
        return self._names.filter(self._live_ports, self._filter_from)

    def _dest_numbers(self) -> List[int]:
        return self._names.filter(self._live_ports, self._filter_to)

    @Property("QVariant", notify=routingChanged)
    def sourcePorts(self) -> List[dict]:
        """Matrix rows. Filtered separately from the columns on purpose:
        one filter across both axes could never show a route from a port in
        one group to a port in another, which is most of what routing is."""
        return self._describe(self._source_numbers())

    @Property("QVariant", notify=routingChanged)
    def destPorts(self) -> List[dict]:
        """Matrix columns."""
        return self._describe(self._dest_numbers())

    def _visible_route(self):
        """A predicate over (source, dest) for the list and graph views.

        The same question the matrix asks of each axis -- does this port
        match the text? -- asked of each end of a route. A route survives
        when its source matches the From filter and its destination matches
        the To filter.

        Deliberately *not* "is this port in sourcePorts": those lists are
        drawn from the live ports, because the matrix can only offer cells
        for ports that exist. A saved route whose port has since gone away
        still belongs in the list, which is the one place it can be seen and
        deleted, so liveness must not be part of this test.

        Returns a closure, and the no-filter case returns a constant one, so
        the common path costs nothing per route.
        """
        if not self._filter_from.strip() and not self._filter_to.strip():
            return lambda source, dest: True
        return lambda source, dest: (
            port_matches(self._names.get(source), self._filter_from)
            and port_matches(self._names.get(dest), self._filter_to))

    @Property("QVariant", notify=routingChanged)
    def graphPorts(self) -> List[dict]:
        """Nodes for the graph.

        Unfiltered, every live port, so the graph is a picture of the whole
        machine and an unrouted port is visibly unrouted.

        Filtered, only the ports the surviving routes actually touch. The
        matrix keeps its empty rows and columns because the grid is where you
        *make* routes and an empty cell is the thing you click; the graph
        draws no such affordance, so a ring of unconnected dots is noise
        around the handful of edges the filter was asked to isolate.

        Both endpoints of every drawn edge are included, so an edge can never
        reference a node that is not there.
        """
        if not self.filtersActive:
            return self._describe(self._live_ports)
        visible = self._visible_route()
        wanted = set()
        for source, dest in self._route_pairs():
            if visible(source, dest):
                wanted.update((source, dest))
        return self._describe([n for n in self._live_ports if n in wanted])

    def _route_pairs(self) -> set:
        """Every (source, dest) that is saved, live, or both."""
        pairs = {(l.source, l.dest) for l in self._routing.links()}
        pairs |= {(l.source, l.dest) for l in self._live_links}
        return pairs

    @Property(bool, notify=routingChanged)
    def filtersActive(self) -> bool:
        return bool(self._filter_from.strip() or self._filter_to.strip())

    @Property(int, notify=routingChanged)
    def totalRoutablePortCount(self) -> int:
        return len(self._live_ports)

    @Property("QVariant", notify=routingChanged)
    def matrix(self) -> List[List[int]]:
        """Row = source, column = destination, in routablePorts order.

        Cell values carry the difference between intent and reality, which is
        the thing a routing screen most needs to show:
          bit 0 (1) saved, bit 1 (2) live, so 3 is saved and live.
        A third bit marks cells whose *reverse* exists:
          bit 2 (4) the opposite direction is routed.
        A cell with bits 2 and either 0 or 1 is half of a two-way pair, which
        makes every message arrive several times -- see wouldCreateLoop.
        """
        sources = self._source_numbers()
        dests = self._dest_numbers()
        rows = []
        for source in sources:
            row = []
            for dest in dests:
                value = 0
                if self._routing.has(source, dest):
                    value |= 1
                if Link(source, dest) in self._live_links:
                    value |= 2
                if self._is_routed(dest, source):
                    value |= 4
                row.append(value)
            rows.append(row)
        return rows

    @Property("QVariant", notify=routingChanged)
    def links(self) -> List[dict]:
        """Routes for the graph view, saved or live.

        Filtered the same way the matrix is: a route is drawn when its source
        passes the From filter and its destination passes the To filter.
        """
        seen = {(l.source, l.dest) for l in self._routing.links()}
        seen |= {(l.source, l.dest) for l in self._live_links}
        visible = self._visible_route()
        return [{"from": s, "to": d,
                 "saved": self._routing.has(s, d),
                 "live": Link(s, d) in self._live_links}
                for s, d in sorted(seen) if visible(s, d)]

    @Property("QVariant", notify=routingChanged)
    def routeRows(self) -> List[dict]:
        """One row per route, for the list view.

        Each row carries both ports in full -- number, custom name, kernel
        name and remark -- because the list has room to show what a port is,
        and a routing screen where you have to remember what "port 17" means
        is a routing screen you cannot read.
        """
        # Saved routes first, in creation order, then anything live that is
        # not saved. Sorting the whole list would move a row every time it
        # was edited and put a newly added route wherever its numbers fell.
        ordered = [(l.source, l.dest) for l in self._routing.links()]
        known = set(ordered)
        ordered += sorted((l.source, l.dest) for l in self._live_links
                          if (l.source, l.dest) not in known)
        visible = self._visible_route()
        rows = []
        for source, dest in ordered:
            if not visible(source, dest):
                continue
            rows.append({
                "source": self._port_detail(source),
                "dest": self._port_detail(dest),
                "saved": self._routing.has(source, dest),
                "live": Link(source, dest) in self._live_links,
            })
        return rows

    def _port_detail(self, number: int) -> dict:
        info = self._names.get(number)
        return {"number": number, "name": info.name,
                "kernelName": info.kernel_name, "remark": info.remark,
                "displayName": info.display_name,
                "colour": info.colour, "colourHex": info.colour_hex,
                "exists": number in self._live_ports}

    @Slot(result=bool)
    def addRoute(self) -> bool:
        """Add a route on the first pair of ports not already connected.

        Applied immediately, like clicking a matrix cell: a list of routes
        where some are real and some are pending would need a second column
        to say which, and this app has one meaning for "it is in the list".
        """
        ports = self._live_ports
        if len(ports) < 2:
            self.errorRaised.emit(
                "At least two ports are needed to make a route.")
            return False
        for source in ports:
            for dest in ports:
                if source != dest and not self._is_routed(source, dest):
                    self._apply_link(source, dest, True)
                    self.routeAdded.emit(source, dest)
                    return True
        self.errorRaised.emit("Every possible route already exists.")
        return False

    @Slot(int, int)
    def removeRoute(self, source: int, dest: int) -> None:
        self._apply_link(source, dest, False)

    @Slot(int, int, int, int)
    def retargetRoute(self, old_source: int, old_dest: int,
                      new_source: int, new_dest: int) -> None:
        """Point an existing route at different ports."""
        if (old_source, old_dest) == (new_source, new_dest):
            return
        if new_source == new_dest:
            self.errorRaised.emit(
                "A port cannot route to itself: it would echo its own "
                "output back into its input.")
            return
        if self._is_routed(new_source, new_dest):
            self.errorRaised.emit(
                f"Port {new_source} already routes to port {new_dest}.")
            return
        if self._seq is not None:
            try:
                set_link(self._seq, old_source, old_dest, False)
                set_link(self._seq, new_source, new_dest, True)
            except AlsaSeqError as exc:
                self.errorRaised.emit(str(exc))
                return
        # replace(), not remove-then-add: the row keeps its place in the list.
        if not self._routing.replace(old_source, old_dest,
                                     new_source, new_dest):
            self._routing.remove(old_source, old_dest)
            self._routing.add(new_source, new_dest)
        self._routing.save()
        self.refresh()
        self.routingChanged.emit()

    def _apply_link(self, source: int, dest: int, connected: bool) -> None:
        """Save and apply one route, or save and drop it."""
        if self._seq is not None:
            try:
                set_link(self._seq, source, dest, connected)
            except AlsaSeqError as exc:
                self.errorRaised.emit(str(exc))
                return
        if connected:
            self._routing.add(source, dest)
        else:
            self._routing.remove(source, dest)
        self._routing.save()
        self.refresh()
        self.routingChanged.emit()

    @Property(int, notify=routingChanged)
    def savedLinkCount(self) -> int:
        return len(self._routing)

    @Property(int, notify=routingChanged)
    def totalRouteCount(self) -> int:
        """Every route the list would show with no filter applied.

        Paired with len(routeRows) so the toolbar can say "3 of 11" on the
        list and graph views, where "1x32 of 32 ports" means nothing.
        """
        return len(self._route_pairs())

    @Property(int, notify=routingChanged)
    def unmanagedLinkCount(self) -> int:
        """Live dummy-to-dummy routes this app has not been told about."""
        return len([l for l in self._live_links
                    if not self._routing.has(l.source, l.dest)])

    def _is_routed(self, source: int, dest: int) -> bool:
        """Connected or intended to be, which is what matters for a warning."""
        return (self._routing.has(source, dest)
                or Link(source, dest) in self._live_links)

    @Slot(int, int, result=bool)
    def wouldCreateLoop(self, source: int, dest: int) -> bool:
        """True when clicking this cell would complete a two-way pair.

        A dummy port echoes whatever it receives to its subscribers, so with
        both directions routed a message goes round and round: measured at
        three copies of every event before ALSA's hop limit stops it. Almost
        never what anyone wants, but occasionally deliberate -- so this
        reports rather than refuses.
        """
        turning_on = not self._routing.has(source, dest)
        return turning_on and self._is_routed(dest, source)

    @Slot(int, int)
    def toggleLink(self, source: int, dest: int) -> None:
        """Connect or disconnect one route, saving and applying together.

        Clicking a cell should do the thing, not queue it: a routing screen
        with a separate Apply invites the user to believe MIDI is flowing
        when it is not.
        """
        if source == dest:
            self.errorRaised.emit(
                "A port cannot route to itself: it would echo its own "
                "output back into its input.")
            return
        wanted = not self._routing.has(source, dest)
        if self._seq is not None:
            try:
                set_link(self._seq, source, dest, wanted)
            except AlsaSeqError as exc:
                self.errorRaised.emit(str(exc))
                return
        self._routing.toggle(source, dest)
        self._routing.save()
        self.refresh()
        self.routingChanged.emit()

    @Slot(int, int)
    def adoptLink(self, source: int, dest: int) -> None:
        """Record an existing live route so it survives a reload."""
        if self._routing.add(source, dest):
            self._routing.save()
            self.routingChanged.emit()
            self.noticeRaised.emit(f"Port {source} to port {dest} is now saved.")

    @Slot()
    def applySavedRouting(self) -> None:
        """Push: make the kernel match the saved routing exactly.

        Authoritative, not a merge. The saved routing is the description of
        what should be connected, so anything else between dummy ports is by
        definition stale and gets removed -- otherwise a connection nobody
        remembers making survives indefinitely and the matrix never settles.

        Still only ever touches dummy-to-dummy links: a browser or a DAW
        subscribed to a port made that connection itself and it is not ours
        to remove.
        """
        if self._seq is None:
            return
        report = apply_routing(self._seq, self._routing, remove_extra=True)
        self.refresh()
        self.routingChanged.emit()
        (self.errorRaised if report.failed else self.noticeRaised).emit(report.summary())

    @Property(int, notify=routingChanged)
    def inactiveSavedCount(self) -> int:
        """Saved routes whose ports both exist but which are not connected."""
        present = set(self._live_ports)
        return len([l for l in self._routing.links()
                    if l not in self._live_links
                    and l.source in present and l.dest in present])

    @Slot(bool)
    def syncFromKernel(self, forget_unconnected: bool = False) -> None:
        """Pull: make the saved routing describe what the kernel has.

        Additive by default. `forget_unconnected` makes it a true mirror,
        but even then it leaves routes for absent ports alone -- see
        core.routing.forget_inactive.
        """
        added = adopt(self._routing, self._live_links)
        removed = []
        if forget_unconnected:
            removed = forget_inactive(self._routing, self._live_links,
                                      self._live_ports)
        if added or removed:
            self._routing.save()
        self.routingChanged.emit()

        parts = []
        if added:
            parts.append(f"{len(added)} connection"
                         f"{'' if len(added) == 1 else 's'} saved")
        if removed:
            parts.append(f"{len(removed)} saved route"
                         f"{'' if len(removed) == 1 else 's'} forgotten")
        self.noticeRaised.emit(
            ", ".join(parts) if parts
            else "The saved routing already matched the kernel.")

    @Slot(bool)
    def sortRouting(self, by_source: bool) -> None:
        """Reorder the saved routing and write it out.

        A durable edit, not a view option: the file is the list's order, so
        sorting it here is what makes the order survive a restart.

        Only the saved routes move. Live connections this app has not been
        told about are appended to the list after them and have nowhere to be
        written, so Sync from Kernel comes first if you want those sorted in.
        """
        if not self._routing.sort(by_source=by_source):
            self.noticeRaised.emit(
                "The routing was already in that order.")
            return
        self._routing.save()
        self.routingChanged.emit()
        count = len(self._routing)
        self.noticeRaised.emit(
            f"{count} route{'' if count == 1 else 's'} sorted by "
            f"{'source' if by_source else 'destination'} and saved.")

    @Slot()
    def clearRouting(self) -> None:
        self._routing.clear()
        self._routing.save()
        self.applySavedRouting()

    # -- backup and restore ----------------------------------------------

    @staticmethod
    def _local_path(file_url: str) -> str:
        """A path from what a FileDialog hands back, which is a URL."""
        return QUrl(file_url).toLocalFile() if file_url.startswith("file:") \
            else file_url

    @Property(str, constant=True)
    def suggestedArchiveName(self) -> str:
        return archive.suggested_name()

    @Property(str, constant=True)
    def suggestedArchiveUrl(self) -> str:
        """A full file:// URL, so the save dialog opens somewhere sensible.

        A bare filename would leave the dialog in whatever directory it last
        remembered -- which on a first run is anyone's guess. Documents if it
        exists, the home directory otherwise.
        """
        from PySide6.QtCore import QStandardPaths
        folder = QStandardPaths.writableLocation(
            QStandardPaths.DocumentsLocation) or \
            QStandardPaths.writableLocation(QStandardPaths.HomeLocation)
        return QUrl.fromLocalFile(
            str(Path(folder) / archive.suggested_name())).toString()

    @Property("QVariant", notify=settingsChanged)
    def exportableFiles(self) -> List[str]:
        """What an export would actually contain, for the page to show."""
        return [entry.filename for entry in archive.exportable()]

    @Slot(str, result=bool)
    def exportArchive(self, file_url: str) -> bool:
        path = self._local_path(file_url)
        if not path:
            self.errorRaised.emit("No file was chosen.")
            return False
        try:
            written = archive.export_archive(Path(path), __version__)
        except OSError as exc:
            self.errorRaised.emit(f"Could not write {path}: {exc}")
            return False
        if not written:
            self.errorRaised.emit("There is nothing saved to export yet.")
            return False
        self.noticeRaised.emit(
            f"{len(written)} file{'' if len(written) == 1 else 's'} "
            f"exported to {path}")
        return True

    @Slot(str)
    def openArchive(self, file_url: str) -> None:
        """Read an archive and offer what is in it.

        Nothing is written here. The file is opened, checked and held, and
        the interface asks the user what to take from it -- an import that
        started the moment a file was picked would give no chance to notice
        the wrong archive.
        """
        path = self._local_path(file_url)
        self._archive_items = []
        self._archive_name = Path(path).name if path else ""
        if not path:
            self.archiveRejected.emit("No file was chosen.")
            return
        try:
            items = archive.inspect_archive(Path(path))
        except archive.ArchiveError as exc:
            self.archiveChanged.emit()
            self.archiveRejected.emit(str(exc))
            return
        if not items:
            self.archiveChanged.emit()
            self.archiveRejected.emit(
                f"{self._archive_name} does not contain any "
                f"{APP_TITLE} data files.\n\nAn archive to import from is "
                f"one this application exported, or any ZIP containing "
                f"{', '.join(e.filename for e in archive.REGISTRY)}.")
            return
        self._archive_items = items
        self.archiveChanged.emit()
        self.archiveOpened.emit(len(items))

    @Property(str, notify=archiveChanged)
    def archiveName(self) -> str:
        return self._archive_name

    @Property("QVariant", notify=archiveChanged)
    def archiveItems(self) -> List[dict]:
        """What the opened archive holds, for the picker."""
        return [{"key": item.key, "label": item.label,
                 "describe": item.describe, "summary": item.summary,
                 "member": item.member} for item in self._archive_items]

    @Slot("QVariantList")
    def importArchive(self, keys) -> None:
        """Overwrite the chosen stores, reload, and re-apply to the kernel.

        Everything the application holds in memory is rebuilt from disk
        afterwards, not patched: an import replaces files wholesale, and
        reloading is the only way to be sure the interface, the kernel and
        the files all say the same thing.
        """
        chosen = [str(k) for k in (keys or [])]
        if not self._archive_items:
            self.errorRaised.emit("No archive is open.")
            return
        if not chosen:
            self.errorRaised.emit("Nothing was chosen to import.")
            return
        try:
            done = archive.import_items(self._archive_items, chosen)
        except OSError as exc:
            self.errorRaised.emit(f"Could not write the configuration: {exc}")
            return
        if not done:
            self.errorRaised.emit("Nothing was imported.")
            return

        wanted_ports = self._settings.port_count
        self._reload_after_import(done)

        labels = [entry.label for entry in archive.REGISTRY
                  if entry.key in done]
        message = f"Imported {', '.join(labels).lower()} from {self._archive_name}."
        # The port count is the one thing an import cannot finish on its own:
        # changing it reloads a kernel module and needs a password, which is
        # not something to spring on someone who clicked Import.
        if "settings" in done and self._settings.port_count != wanted_ports \
                and not self.moduleMatches:
            message += (f" The archive asks for {self._settings.port_count} "
                        f"ports — press Apply on this page to change the "
                        f"kernel module.")
        self.noticeRaised.emit(message)

    def _reload_after_import(self, done: List[str]) -> None:
        """Re-read what was imported and make the world match it."""
        if "settings" in done:
            self._settings = Settings.load()
            self.settingsChanged.emit()
            self.paletteChanged.emit()
            self.fontScaleChanged.emit()
            self.moduleChanged.emit()
            # The mute rules, ports and microphone may all have moved. A
            # restart is the only honest way to apply them: the listener
            # holds its own sequencer subscriptions.
            self._restart_mute()
        if "ports" in done:
            self._names = PortNames.load()
            self._sync_ports_model()
            self.portsChanged.emit()
        if "routing" in done:
            self._routing = Routing.load()
            # Authoritative, exactly like Apply to Kernel and start-up: the
            # imported routing is now the description of what should be
            # connected, so anything else between dummy ports is stale.
            if self._seq is not None:
                report = apply_routing(self._seq, self._routing,
                                       remove_extra=True)
                if report.failed:
                    self.errorRaised.emit(
                        "Some imported routes could not be applied: "
                        + "; ".join(report.failed[:3]))
                logger.info("routing imported: %s", report.summary())
        self.refresh()
        self.routingChanged.emit()

    # -- odds and ends ---------------------------------------------------

    @Slot(str)
    def copyToClipboard(self, text: str) -> None:
        QGuiApplication.clipboard().setText(text)

    @Slot()
    def openHomepage(self) -> None:
        webbrowser.open(APP_HOMEPAGE)

    @Slot()
    def quitApplication(self) -> None:
        from PySide6.QtWidgets import QApplication
        self.stop()
        QApplication.instance().quit()
