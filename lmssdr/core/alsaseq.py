"""A small ctypes binding to the ALSA sequencer.

Why no dependency: `python3-pyalsa` is not packaged everywhere, and
`python-rtmidi` cannot read or create *subscriptions* at all -- which is the
whole point here. Routing between two ports is a kernel-side subscription,
not bytes copied in userspace, so the kernel moves the MIDI and this process
can be busy, slow or paused without a single event being late or lost.
`libasound.so.2` is present on every ALSA system, so a ctypes binding costs
one file and removes a build dependency.

Nothing here touches MIDI *data*. This module only reads and edits the
sequencer graph; `core.mute` is the one place the app actually reads events.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import select
import logging
import re
from dataclasses import dataclass
from typing import Dict, Iterator, List, Optional, Tuple

logger = logging.getLogger(__name__)

__all__ = [
    "Addr", "Client", "Port", "AlsaSeqError", "Seq",
    "DUMMY_PORT_RE", "dummy_port_number",
]

# -- libasound -----------------------------------------------------------

# The soname is stable and every ALSA system has it; find_library is only a
# fallback for unusual layouts.
_LIB_CANDIDATES = ("libasound.so.2", ctypes.util.find_library("asound"))


def _load() -> ctypes.CDLL:
    for name in _LIB_CANDIDATES:
        if not name:
            continue
        try:
            return ctypes.CDLL(name)
        except OSError:
            continue
    raise AlsaSeqError(
        "libasound.so.2 could not be loaded. On Debian/Ubuntu install "
        "libasound2t64 (or libasound2).")


class AlsaSeqError(RuntimeError):
    """Any failure coming out of libasound, with its message attached."""


# -- constants (sound/asequencer.h) --------------------------------------

OPEN_OUTPUT = 1
OPEN_INPUT = 2
OPEN_DUPLEX = 3
NONBLOCK = 1

CAP_READ = 1 << 0
CAP_WRITE = 1 << 1
CAP_SYNC_READ = 1 << 2
CAP_SYNC_WRITE = 1 << 3
CAP_DUPLEX = 1 << 4
CAP_SUBS_READ = 1 << 5
CAP_SUBS_WRITE = 1 << 6
CAP_NO_EXPORT = 1 << 7

TYPE_SPECIFIC = 1 << 0
TYPE_MIDI_GENERIC = 1 << 1
TYPE_HARDWARE = 1 << 16
TYPE_SOFTWARE = 1 << 17
TYPE_SYNTHESIZER = 1 << 18
TYPE_PORT = 1 << 19
TYPE_APPLICATION = 1 << 20

USER_CLIENT = 1
KERNEL_CLIENT = 2

QUERY_SUBS_READ = 0
QUERY_SUBS_WRITE = 1

#: Deliver immediately rather than through a timing queue.
QUEUE_DIRECT = 253

#: A port is usable as a routing *source* only if others may subscribe to it,
#: and as a *destination* only if it accepts subscriptions. Ports lacking the
#: SUBS bits (PipeWire's internal ones, for instance) cannot be routed at all.
READABLE = CAP_READ | CAP_SUBS_READ
WRITABLE = CAP_WRITE | CAP_SUBS_WRITE

#: snd_seq_dummy names its ports "Midi Through Port-<n>" (or "...-<n>:A"/":B"
#: in duplex mode, which this app never uses -- see core.module).
DUMMY_PORT_RE = re.compile(r"^Midi Through Port-(\d+)$")


def dummy_port_number(port_name: str) -> Optional[int]:
    """The N in "Midi Through Port-N", or None if this is not such a port."""
    match = DUMMY_PORT_RE.match(port_name)
    return int(match.group(1)) if match else None


class _CAddr(ctypes.Structure):
    _fields_ = [("client", ctypes.c_ubyte), ("port", ctypes.c_ubyte)]


# -- event structures (sound/asequencer.h) -------------------------------
#
# Laid out by hand because libasound offers no accessors for event fields the
# way it does for client and port info. The sizes are asserted at import so a
# layout change breaks loudly here rather than silently decoding garbage.

EVENT_NOTEON = 6
EVENT_NOTEOFF = 7
EVENT_CONTROLLER = 10


class _RealTime(ctypes.Structure):
    _fields_ = [("tv_sec", ctypes.c_uint), ("tv_nsec", ctypes.c_uint)]


class _Timestamp(ctypes.Union):
    _fields_ = [("tick", ctypes.c_uint), ("time", _RealTime)]


class _EvNote(ctypes.Structure):
    _fields_ = [("channel", ctypes.c_ubyte), ("note", ctypes.c_ubyte),
                ("velocity", ctypes.c_ubyte), ("off_velocity", ctypes.c_ubyte),
                ("duration", ctypes.c_uint)]


class _EvCtrl(ctypes.Structure):
    _fields_ = [("channel", ctypes.c_ubyte), ("unused", ctypes.c_ubyte * 3),
                ("param", ctypes.c_uint), ("value", ctypes.c_int)]


class _EvData(ctypes.Union):
    _fields_ = [("note", _EvNote), ("control", _EvCtrl),
                ("raw8", ctypes.c_ubyte * 12)]


class _CEvent(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ubyte), ("flags", ctypes.c_ubyte),
                ("tag", ctypes.c_ubyte), ("queue", ctypes.c_ubyte),
                ("time", _Timestamp),
                ("source", _CAddr), ("dest", _CAddr),
                ("data", _EvData)]


assert ctypes.sizeof(_CEvent) == 28, ctypes.sizeof(_CEvent)


class _CPollFd(ctypes.Structure):
    _fields_ = [("fd", ctypes.c_int), ("events", ctypes.c_short),
                ("revents", ctypes.c_short)]


@dataclass(frozen=True)
class MidiEvent:
    """One decoded MIDI message.

    `channel` is 1-based. ALSA counts from zero, but every MIDI spec, DAW and
    hardware panel counts from one -- including the Mackie transport rules
    this exists to serve -- so the translation happens here rather than in
    every rule that reads it.
    """

    kind: str            # "noteon" | "noteoff" | "cc"
    channel: int
    data1: int           # note number, or controller number
    data2: int           # velocity, or controller value
    source: Addr

    def __str__(self) -> str:
        return (f"{self.kind} ch{self.channel} "
                f"{self.data1}={self.data2} from {self.source}")


# -- data ----------------------------------------------------------------


@dataclass(frozen=True, order=True)
class Addr:
    """A sequencer address, the `client:port` pair `aconnect` prints."""

    client: int
    port: int

    def __str__(self) -> str:
        return f"{self.client}:{self.port}"

    @classmethod
    def parse(cls, text: str) -> "Addr":
        client, _, port = text.partition(":")
        return cls(int(client), int(port))


@dataclass(frozen=True)
class Port:
    addr: Addr
    name: str
    caps: int
    type: int
    client_name: str

    @property
    def readable(self) -> bool:
        """Can be a routing source."""
        return self.caps & READABLE == READABLE

    @property
    def writable(self) -> bool:
        """Can be a routing destination."""
        return self.caps & WRITABLE == WRITABLE

    @property
    def is_midi(self) -> bool:
        return bool(self.type & TYPE_MIDI_GENERIC)

    @property
    def dummy_number(self) -> Optional[int]:
        return dummy_port_number(self.name)


@dataclass(frozen=True)
class Client:
    id: int
    name: str
    type: int

    @property
    def is_kernel(self) -> bool:
        return self.type == KERNEL_CLIENT


# -- the binding ---------------------------------------------------------


class Seq:
    """An open connection to the sequencer.

    Use as a context manager. The client this opens is a normal userspace
    client; it exists only so we have a handle through which to read the
    graph and create subscriptions, and it deliberately creates no ports of
    its own -- an empty client cannot be mistaken for something routable.
    """

    def __init__(self, name: str = "LMSSDR MIDI Router", mode: int = OPEN_DUPLEX,
                 nonblock: bool = False):
        self._lib = _load()
        self._bind()
        handle = ctypes.c_void_p()
        # Non-blocking is what makes read_events() safe to call from a poll
        # loop: blocking, it would sit in the kernel until a note arrived and
        # never notice a request to stop.
        err = self._lib.snd_seq_open(ctypes.byref(handle), b"default", mode,
                                     NONBLOCK if nonblock else 0)
        if err < 0:
            raise AlsaSeqError(f"snd_seq_open failed: {self._strerror(err)}")
        self._handle = handle
        self._lib.snd_seq_set_client_name(handle, name.encode())
        self.client_id = self._lib.snd_seq_client_id(handle)

    # -- lifecycle -------------------------------------------------------

    def close(self) -> None:
        if getattr(self, "_handle", None) is not None:
            self._lib.snd_seq_close(self._handle)
            self._handle = None

    def __enter__(self) -> "Seq":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def __del__(self):
        try:
            self.close()
        except Exception:       # interpreter teardown; nothing useful to do
            pass

    # -- ctypes plumbing -------------------------------------------------

    def _bind(self) -> None:
        lib = self._lib
        lib.snd_strerror.restype = ctypes.c_char_p
        for fn in ("snd_seq_client_info_get_name", "snd_seq_port_info_get_name"):
            getattr(lib, fn).restype = ctypes.c_char_p
        for fn in ("snd_seq_port_info_get_capability", "snd_seq_port_info_get_type"):
            getattr(lib, fn).restype = ctypes.c_uint
        lib.snd_seq_query_subscribe_get_addr.restype = ctypes.POINTER(_CAddr)

    def _strerror(self, err: int) -> str:
        return self._lib.snd_strerror(err).decode(errors="replace")

    def _check(self, err: int, what: str) -> None:
        if err < 0:
            raise AlsaSeqError(f"{what}: {self._strerror(err)}")

    # -- reading the graph -----------------------------------------------

    def clients(self) -> List[Client]:
        lib = self._lib
        info = ctypes.c_void_p()
        lib.snd_seq_client_info_malloc(ctypes.byref(info))
        try:
            lib.snd_seq_client_info_set_client(info, -1)
            found = []
            while lib.snd_seq_query_next_client(self._handle, info) >= 0:
                found.append(Client(
                    id=lib.snd_seq_client_info_get_client(info),
                    name=lib.snd_seq_client_info_get_name(info).decode(errors="replace"),
                    type=lib.snd_seq_client_info_get_type(info)))
            return found
        finally:
            lib.snd_seq_client_info_free(info)

    def ports(self, client: Optional[Client] = None) -> List[Port]:
        """Every port, or only one client's."""
        clients = [client] if client else self.clients()
        lib = self._lib
        info = ctypes.c_void_p()
        lib.snd_seq_port_info_malloc(ctypes.byref(info))
        try:
            found = []
            for cli in clients:
                lib.snd_seq_port_info_set_client(info, cli.id)
                lib.snd_seq_port_info_set_port(info, -1)
                while lib.snd_seq_query_next_port(self._handle, info) >= 0:
                    found.append(Port(
                        addr=Addr(cli.id, lib.snd_seq_port_info_get_port(info)),
                        name=lib.snd_seq_port_info_get_name(info).decode(errors="replace"),
                        caps=lib.snd_seq_port_info_get_capability(info),
                        type=lib.snd_seq_port_info_get_type(info),
                        client_name=cli.name))
            return found
        finally:
            lib.snd_seq_port_info_free(info)

    def connections(self) -> List[Tuple[Addr, Addr]]:
        """Every subscription in the system, as (sender, destination).

        Read from the *read* side of each port only. Every subscription is
        visible from both ends, so querying both would return each link
        twice.
        """
        lib = self._lib
        subs = ctypes.c_void_p()
        lib.snd_seq_query_subscribe_malloc(ctypes.byref(subs))
        try:
            links: List[Tuple[Addr, Addr]] = []
            for port in self.ports():
                root = _CAddr(port.addr.client, port.addr.port)
                index = 0
                while True:
                    lib.snd_seq_query_subscribe_set_root(subs, ctypes.byref(root))
                    lib.snd_seq_query_subscribe_set_type(subs, QUERY_SUBS_READ)
                    lib.snd_seq_query_subscribe_set_index(subs, index)
                    if lib.snd_seq_query_port_subscribers(self._handle, subs) < 0:
                        break
                    dest = lib.snd_seq_query_subscribe_get_addr(subs).contents
                    links.append((port.addr, Addr(dest.client, dest.port)))
                    index += 1
            return links
        finally:
            lib.snd_seq_query_subscribe_free(subs)

    # -- editing the graph -----------------------------------------------

    def _subscription(self, sender: Addr, dest: Addr):
        lib = self._lib
        subs = ctypes.c_void_p()
        lib.snd_seq_port_subscribe_malloc(ctypes.byref(subs))
        s = _CAddr(sender.client, sender.port)
        d = _CAddr(dest.client, dest.port)
        lib.snd_seq_port_subscribe_set_sender(subs, ctypes.byref(s))
        lib.snd_seq_port_subscribe_set_dest(subs, ctypes.byref(d))
        return subs

    def connect(self, sender: Addr, dest: Addr) -> None:
        """Subscribe dest to sender. Already-connected is not an error."""
        subs = self._subscription(sender, dest)
        try:
            err = self._lib.snd_seq_subscribe_port(self._handle, subs)
            # -EBUSY means the link is already there, which is the state the
            # caller asked for -- so applying a saved routing twice is safe.
            if err < 0 and err != -16:
                self._check(err, f"connect {sender} -> {dest}")
        finally:
            self._lib.snd_seq_port_subscribe_free(subs)

    def disconnect(self, sender: Addr, dest: Addr) -> None:
        """Remove a subscription. Not-connected is not an error."""
        subs = self._subscription(sender, dest)
        try:
            err = self._lib.snd_seq_unsubscribe_port(self._handle, subs)
            if err < 0 and err != -2:        # -ENOENT: already absent
                self._check(err, f"disconnect {sender} -> {dest}")
        finally:
            self._lib.snd_seq_port_subscribe_free(subs)

    # -- listening -------------------------------------------------------

    def create_input_port(self, name: str = "listen") -> int:
        """A port for receiving, which nothing else may route through.

        NO_EXPORT keeps it out of other applications' port lists: it is an
        ear, not a patch point, and offering it as a destination would invite
        someone to wire something into it by mistake.
        """
        caps = CAP_WRITE | CAP_NO_EXPORT
        port = self._lib.snd_seq_create_simple_port(
            self._handle, name.encode(), caps,
            TYPE_MIDI_GENERIC | TYPE_APPLICATION)
        self._check(port, "snd_seq_create_simple_port")
        return port

    def poll_fds(self) -> List[int]:
        """File descriptors to wait on, so a listener need not spin."""
        lib = self._lib
        count = lib.snd_seq_poll_descriptors_count(self._handle, select.POLLIN)
        if count <= 0:
            return []
        buf = (_CPollFd * count)()
        lib.snd_seq_poll_descriptors(self._handle, buf, count, select.POLLIN)
        return [buf[i].fd for i in range(count)]

    def read_events(self) -> List[MidiEvent]:
        """Every event waiting right now. Never blocks.

        Only note-on, note-off and controller messages are returned. The
        sequencer also delivers announcements about ports appearing and
        disappearing, and a rule engine has no use for those.
        """
        lib = self._lib
        pointer = ctypes.POINTER(_CEvent)()
        found: List[MidiEvent] = []
        while True:
            err = lib.snd_seq_event_input(self._handle, ctypes.byref(pointer))
            if err < 0:
                # -EAGAIN (nothing left) and -ENOSPC (the input pool
                # overflowed and older events were dropped) are both just
                # "stop reading for now".
                break
            event = pointer.contents
            decoded = self._decode(event)
            if decoded is not None:
                found.append(decoded)
        return found

    @staticmethod
    def _decode(event: "_CEvent") -> Optional[MidiEvent]:
        source = Addr(event.source.client, event.source.port)
        if event.type in (EVENT_NOTEON, EVENT_NOTEOFF):
            note = event.data.note
            kind = "noteon" if event.type == EVENT_NOTEON else "noteoff"
            # A note-on with zero velocity is a note-off. Hardware and DAWs
            # both send it, so a rule matching "note on, velocity 127" would
            # otherwise fire on a release too.
            if kind == "noteon" and note.velocity == 0:
                kind = "noteoff"
            return MidiEvent(kind, note.channel + 1, note.note,
                             note.velocity, source)
        if event.type == EVENT_CONTROLLER:
            ctrl = event.data.control
            return MidiEvent("cc", ctrl.channel + 1, ctrl.param,
                             ctrl.value, source)
        return None

    # -- sending ---------------------------------------------------------

    def create_output_port(self, name: str = "send") -> int:
        """A port for sending. NO_EXPORT: nothing should route *into* this."""
        caps = CAP_READ | CAP_NO_EXPORT
        port = self._lib.snd_seq_create_simple_port(
            self._handle, name.encode(), caps,
            TYPE_MIDI_GENERIC | TYPE_APPLICATION)
        self._check(port, "snd_seq_create_simple_port")
        return port

    def send(self, source_port: int, dest: Addr, kind: str, channel: int,
             data1: int, data2: int) -> None:
        """Send one message straight to a port, bypassing any subscription.

        Addressed directly rather than to subscribers, so a test message goes
        exactly where the caller aimed it and nowhere else -- it must not
        leak into whatever else happens to be listening to our output port.
        """
        event = _CEvent()
        event.type = EVENT_CONTROLLER if kind == "cc" else EVENT_NOTEON
        event.flags = 0
        event.queue = QUEUE_DIRECT
        event.source = _CAddr(self.client_id, source_port)
        event.dest = _CAddr(dest.client, dest.port)
        # ALSA channels are 0-based; every user-facing number here is 1-based.
        if kind == "cc":
            event.data.control.channel = (channel - 1) & 0x0f
            event.data.control.param = data1
            event.data.control.value = data2
        else:
            event.data.note.channel = (channel - 1) & 0x0f
            event.data.note.note = data1
            event.data.note.velocity = data2

        err = self._lib.snd_seq_event_output(self._handle, ctypes.byref(event))
        self._check(err, "snd_seq_event_output")
        err = self._lib.snd_seq_drain_output(self._handle)
        self._check(err, "snd_seq_drain_output")

    # -- convenience -----------------------------------------------------

    def dummy_client(self) -> Optional[Client]:
        """The snd_seq_dummy client, if the module is loaded.

        Matched by port naming rather than by the client name or the fixed id
        14, so a renamed or relocated client still resolves.
        """
        for cli in self.clients():
            if not cli.is_kernel:
                continue
            if any(p.dummy_number is not None for p in self.ports(cli)):
                return cli
        return None

    def dummy_ports(self) -> Dict[int, Port]:
        """Dummy port number -> Port, e.g. {0: Port(14:0), 1: Port(14:1)}."""
        client = self.dummy_client()
        if client is None:
            return {}
        result = {}
        for port in self.ports(client):
            number = port.dummy_number
            if number is not None:
                result[number] = port
        return result
