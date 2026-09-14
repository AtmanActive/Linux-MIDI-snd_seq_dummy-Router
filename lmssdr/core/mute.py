"""Muting a microphone from DAW transport messages.

A Linux counterpart to MIDI-Transport-to-Mute, and deliberately the same
rules, so that a studio running both sees identical behaviour:

    Mackie Play  -- note on, channel 1, note 94, velocity 127 -- mutes
    Mackie Stop  -- note on, channel 1, note 93, velocity 127 -- unmutes
    Talkback     -- CC 14 on channel 14, value 127 / 0        -- holds open

Talkback is a hold, not a toggle, and it only does anything while the
transport has the microphone muted: unmuting something that is already open
would be a no-op with a tray colour attached, and re-muting on release would
cut a microphone the user never muted.

Before the first recognized message the engine reports ``idle`` rather than
``open``. It is not the same claim: "the transport is stopped" is something
the engine has been told, while "nothing has spoken to me yet" is the absence
of any such message. The tray shows the two differently, so a glance
distinguishes a listener that is following the DAW from one that is merely
running.

The engine here decides; it does not act. Keeping it free of both ALSA and
PulseAudio means the whole rule set can be tested by handing it events, which
matters for a feature whose failure mode is a live microphone.
"""

from __future__ import annotations

import logging
import select
import threading
from dataclasses import dataclass
from typing import Optional

from . import audio
from .alsaseq import Addr, AlsaSeqError, MidiEvent, Seq

logger = logging.getLogger(__name__)

#: Tray and interface states.
STATE_IDLE = "idle"           # nothing recognized yet, state unknown
STATE_OPEN = "open"           # transport stopped, microphone live
STATE_MUTED = "muted"         # transport playing, microphone muted
STATE_TALKBACK = "talkback"   # transport playing, held open by talkback


@dataclass(frozen=True)
class MuteRules:
    """Which messages mean what.

    Defaults are the Mackie Control transport notes. They are fields rather
    than constants because a DAW that cannot be talked into Mackie mode can
    still be pointed at some other note or controller.
    """

    transport_channel: int = 1
    play_note: int = 94           # 0x5E
    stop_note: int = 93           # 0x5D
    #: Transport notes are only honoured at full velocity, as Mackie sends
    #: them; a note-on at another velocity is something else entirely.
    transport_velocity: int = 127

    talkback_channel: int = 14
    talkback_cc: int = 14


class MuteEngine:
    """The state machine. Decides, never acts."""

    def __init__(self, rules: Optional[MuteRules] = None):
        self.rules = rules or MuteRules()
        self.playing = False
        self.talkback = False
        #: Whether any message matching the rules has arrived. Until one has,
        #: the engine will not claim to know where the transport is.
        self.seen = False

    # -- state -----------------------------------------------------------

    @property
    def should_mute(self) -> bool:
        return self.playing and not self.talkback

    @property
    def state(self) -> str:
        if not self.seen:
            return STATE_IDLE
        if not self.playing:
            return STATE_OPEN
        return STATE_TALKBACK if self.talkback else STATE_MUTED

    def reset(self) -> None:
        self.playing = False
        self.talkback = False
        self.seen = False

    # -- events ----------------------------------------------------------

    def on_transport(self, event: MidiEvent) -> bool:
        """Feed a message from the transport port. True if the state moved."""
        rules = self.rules
        if event.kind != "noteon" or event.channel != rules.transport_channel:
            return False
        if event.data2 != rules.transport_velocity:
            return False
        if event.data1 not in (rules.play_note, rules.stop_note):
            return False

        before = self.state
        # Recognized, so the engine is no longer idle even if the transport
        # turns out to be where it already assumed: the first Stop of a
        # session is what tells it the DAW is stopped rather than silent.
        self.seen = True
        if event.data1 == rules.play_note:
            self.playing = True
        else:
            self.playing = False
            # Release talkback on stop. Carrying it into the next take would
            # mean pressing play and getting an open microphone because of a
            # button held minutes earlier.
            self.talkback = False
        return self.state != before

    def on_talkback(self, event: MidiEvent) -> bool:
        """Feed a message from the talkback port. True if the state moved."""
        rules = self.rules
        if event.kind != "cc" or event.channel != rules.talkback_channel:
            return False
        if event.data1 != rules.talkback_cc:
            return False
        if event.data2 not in (0, 127):
            return False

        before = self.state
        self.seen = True
        # The hold itself is ignored while stopped: the microphone is already
        # open, so there is nothing to hold open and nothing to restore on
        # release. The message still counts as recognized, which is why this
        # sets `seen` above rather than returning early.
        if self.playing:
            self.talkback = event.data2 == 127
        return self.state != before

    def describe(self) -> str:
        return {
            STATE_IDLE: "Waiting — no transport message heard yet",
            STATE_OPEN: "Microphone live — transport stopped",
            STATE_MUTED: "Microphone muted — transport playing",
            STATE_TALKBACK: "Talkback held — microphone live while playing",
        }[self.state]


class MuteService:
    """Runs the engine against live MIDI and applies its decisions.

    One thread, owning its own sequencer connection. It is separate from the
    application's main connection because it blocks on a poll and would
    otherwise have to share a handle with the routing code, and libasound
    makes no promises about that.
    """

    #: How long the poll waits before checking whether it has been asked to
    #: stop. Short enough to quit promptly, long enough to cost nothing.
    POLL_SECONDS = 0.25

    def __init__(self, on_change=None):
        self._engine = MuteEngine()
        self._on_change = on_change
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._lock = threading.Lock()

        self._transport_port: Optional[int] = None
        self._talkback_port: Optional[int] = None
        self._source = ""
        self._error = ""
        #: Whether this service is the reason the microphone is muted, so it
        #: can put it back on the way out and not otherwise.
        self._we_muted = False

    # -- configuration ---------------------------------------------------

    def configure(self, transport_port: Optional[int],
                  talkback_port: Optional[int], source: str,
                  rules: Optional[MuteRules] = None) -> None:
        with self._lock:
            self._transport_port = transport_port
            self._talkback_port = talkback_port
            self._source = source or ""
            if rules is not None:
                self._engine.rules = rules

    @property
    def state(self) -> str:
        return self._engine.state

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def error(self) -> str:
        return self._error

    # -- lifecycle -------------------------------------------------------

    def start(self) -> bool:
        if self.running:
            return True
        if self._transport_port is None:
            self._error = "No transport port chosen."
            return False
        if not self._source:
            self._error = "No microphone chosen."
            return False
        self._error = ""
        self._stop.clear()
        self._engine.reset()
        self._thread = threading.Thread(target=self._run, name="lmssdr-mute",
                                        daemon=True)
        self._thread.start()
        return True

    def stop(self, restore: bool = True) -> None:
        """Stop listening and, by default, hand the microphone back.

        Leaving it muted because the application happened to exit mid-take
        would be a silent failure of exactly the kind this feature exists to
        prevent.
        """
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=2.0)
        if restore and self._we_muted:
            audio.set_mute(self._source, False)
            self._we_muted = False
        self._engine.reset()
        self._notify()

    # -- the loop --------------------------------------------------------

    def _notify(self) -> None:
        if self._on_change is not None:
            try:
                self._on_change(self._engine.state)
            except Exception:       # a listener must not kill the thread
                logger.warning("mute state listener raised", exc_info=True)

    def _apply(self) -> None:
        wanted = self._engine.should_mute
        if audio.set_mute(self._source, wanted):
            self._we_muted = wanted
        else:
            self._error = f"Could not mute {self._source}"
            logger.warning(self._error)
        self._notify()

    def _run(self) -> None:
        try:
            seq = Seq("MIDI Router (mute)", nonblock=True)
        except AlsaSeqError as exc:
            self._error = str(exc)
            logger.error("mute listener could not open the sequencer: %s", exc)
            self._notify()
            return

        try:
            port = seq.create_input_port("transport")
            me = Addr(seq.client_id, port)
            ports = seq.dummy_ports()

            transport = ports.get(self._transport_port)
            talkback = ports.get(self._talkback_port) \
                if self._talkback_port is not None else None
            if transport is None:
                self._error = (f"Midi Through Port-{self._transport_port} "
                               f"is not present.")
                self._notify()
                return

            seq.connect(transport.addr, me)
            if talkback is not None:
                seq.connect(talkback.addr, me)

            transport_addr = transport.addr
            talkback_addr = talkback.addr if talkback else None
            fds = seq.poll_fds()

            while not self._stop.is_set():
                if fds:
                    select.select(fds, [], [], self.POLL_SECONDS)
                else:
                    self._stop.wait(self.POLL_SECONDS)
                for event in seq.read_events():
                    moved = False
                    if event.source == transport_addr:
                        moved = self._engine.on_transport(event)
                    if event.source == talkback_addr:
                        # Both roles may sit on one port, so this is a second
                        # `if`, not an `elif`: a single port carrying the
                        # transport and the talkback still works.
                        moved = self._engine.on_talkback(event) or moved
                    if moved:
                        self._apply()
        except AlsaSeqError as exc:
            self._error = str(exc)
            logger.warning("mute listener stopped: %s", exc)
            self._notify()
        finally:
            seq.close()
