"""Saved routing between ports, and applying it to the sequencer.

A route is one ALSA subscription: whatever is written into the source port is
echoed to its subscribers, and the destination port is one of them. The
kernel moves the bytes, so a route keeps working whether or not this process
is running -- which is exactly why the routing has to be saved and re-applied
rather than merely observed. Subscriptions do not survive a reboot or a
module reload.

Routes are stored as port *numbers*, never as sequencer addresses. A module
reload can hand the dummy client a different id; port 7 stays port 7.

What this module will and will not touch:

* It only ever creates or removes subscriptions where **both** ends are
  snd_seq_dummy ports. A browser or a DAW subscribing to a dummy port is
  someone else's link, and deleting it would break their audio session.
* Even among dummy-to-dummy links, removal happens only when explicitly
  asked for. Applying saved routing adds what is missing and leaves anything
  else alone, so a route somebody made by hand with `aconnect` survives an
  ordinary start.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set

from .alsaseq import Addr, AlsaSeqError, Seq
from .paths import (config_dir, migrate, migrate_config_dir,
                    read_json, write_json)

logger = logging.getLogger(__name__)

FILE_NAME = "lmssdr.routing.json"
#: What this file was called in earlier versions, newest
#: first. Renamed on load, one hop at a time.
LEGACY_FILE_NAMES = ("lmsdr.routing.json", "routing.json")


@dataclass(frozen=True, order=True)
class Link:
    """A route from one dummy port number to another."""

    source: int
    dest: int

    def __str__(self) -> str:
        return f"{self.source}->{self.dest}"


def is_legal(source: int, dest: int) -> bool:
    """Routes must go somewhere else.

    A dummy port echoes what it receives to its own subscribers, so a port
    subscribed to itself would feed its own output back into its input and
    loop for as long as anything keeps sending.
    """
    return source != dest


@dataclass
class ApplyReport:
    added: List[Link] = field(default_factory=list)
    removed: List[Link] = field(default_factory=list)
    #: Saved routes whose ports do not currently exist -- usually because the
    #: port count was lowered. Kept in the file, skipped for now.
    skipped: List[Link] = field(default_factory=list)
    failed: List[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.added or self.removed)

    def summary(self) -> str:
        bits = []
        if self.added:
            bits.append(f"{len(self.added)} connected")
        if self.removed:
            bits.append(f"{len(self.removed)} disconnected")
        if self.skipped:
            bits.append(f"{len(self.skipped)} skipped (port not present)")
        if self.failed:
            bits.append(f"{len(self.failed)} failed")
        return ", ".join(bits) if bits else "Routing already matched"


class Routing:
    """The lmssdr.routing.json database.

    Ordered, not sorted. Routes are kept in the order they were created and
    saved that way, because the list view shows them in this order: a new
    route has to appear at the bottom where the user just added it, and
    re-pointing one must not make its row jump somewhere else.

    `sort()` reorders the list on request, and the new order is what gets
    saved -- so sorting is a durable edit to the file, not a way of looking
    at it.
    """

    def __init__(self, links: Optional[Iterable[Link]] = None):
        self._links: List[Link] = []
        for link in links or ():
            if link not in self._links:
                self._links.append(link)

    # -- persistence -----------------------------------------------------

    @classmethod
    def path(cls) -> Path:
        return config_dir() / FILE_NAME

    @classmethod
    def load(cls) -> "Routing":
        migrate_config_dir()
        for legacy in LEGACY_FILE_NAMES:
            migrate(config_dir() / legacy, cls.path())
        raw = read_json(cls.path(), {})
        # A list, not a set: the file order is the order the user created
        # these in, and that is what the list view shows.
        links = []
        for entry in (raw.get("links") or []):
            if not isinstance(entry, dict):
                continue
            try:
                source = int(entry["from"])
                dest = int(entry["to"])
            except (KeyError, TypeError, ValueError):
                continue
            link = Link(source, dest)
            if is_legal(source, dest) and link not in links:
                links.append(link)
        return cls(links)

    def save(self) -> None:
        write_json(self.path(), {
            "links": [{"from": link.source, "to": link.dest}
                      for link in self._links]
        })

    # -- editing ---------------------------------------------------------

    def add(self, source: int, dest: int) -> bool:
        """Record a route. False when it is illegal or already present."""
        if not is_legal(source, dest):
            return False
        link = Link(source, dest)
        if link in self._links:
            return False
        self._links.append(link)        # newest last
        return True

    def remove(self, source: int, dest: int) -> bool:
        link = Link(source, dest)
        if link not in self._links:
            return False
        self._links.remove(link)
        return True

    def replace(self, old_source: int, old_dest: int,
                new_source: int, new_dest: int) -> bool:
        """Re-point a route without moving it in the list.

        Remove-then-add would send the row to the bottom, which is a strange
        thing for editing one end of it to do.
        """
        old = Link(old_source, old_dest)
        new = Link(new_source, new_dest)
        if old not in self._links or not is_legal(new_source, new_dest):
            return False
        if new in self._links and new != old:
            return False
        self._links[self._links.index(old)] = new
        return True

    def toggle(self, source: int, dest: int) -> bool:
        """Add or remove. Returns the resulting state (True = connected)."""
        if Link(source, dest) in self._links:
            self.remove(source, dest)
            return False
        return self.add(source, dest)

    def clear(self) -> None:
        self._links = []

    def sort(self, by_source: bool = True) -> bool:
        """Reorder the whole list. Returns True if anything moved.

        Creation order is the default because a route the user just added
        must appear where they added it. But a list that has been edited for
        a while stops having an order anyone remembers, and then the only
        useful order is by number -- so this is offered as an explicit act,
        not applied behind the user's back.

        The other end breaks ties, so the secondary order is always defined
        and the same list always sorts to the same arrangement: by source
        11->10 precedes 11->11, and by destination 10->11 precedes 11->11.
        """
        before = list(self._links)
        key = ((lambda l: (l.source, l.dest)) if by_source
               else (lambda l: (l.dest, l.source)))
        self._links.sort(key=key)
        return self._links != before

    def swap_ports(self, a: int, b: int) -> List[Link]:
        """Rewrite every route as if the two ports had changed places.

        Both ends of every link are relabelled, so a route into one port
        follows it to the other and a route between the pair reverses. The
        relabelling is a bijection, so it cannot collide with an existing
        route or produce a self-route out of one that was legal.

        Positions are preserved: the list is edited in place, not rebuilt.
        Returns the links that actually changed.
        """
        if a == b:
            return []

        def moved(number: int) -> int:
            if number == a:
                return b
            if number == b:
                return a
            return number

        changed = []
        for index, link in enumerate(self._links):
            new = Link(moved(link.source), moved(link.dest))
            if new != link:
                self._links[index] = new
                changed.append(new)
        return changed

    def drop_port(self, number: int) -> None:
        """Forget every route touching a port."""
        self._links = [l for l in self._links
                       if l.source != number and l.dest != number]

    # -- access ----------------------------------------------------------

    def has(self, source: int, dest: int) -> bool:
        return Link(source, dest) in self._links

    def links(self) -> List[Link]:
        """In creation order. Callers that need a stable key sort it."""
        return list(self._links)

    def destinations(self, source: int) -> List[int]:
        return sorted(l.dest for l in self._links if l.source == source)

    def sources(self, dest: int) -> List[int]:
        return sorted(l.source for l in self._links if l.dest == dest)

    def __len__(self) -> int:
        return len(self._links)

    def __contains__(self, link: Link) -> bool:
        return link in self._links


# -- talking to the sequencer -------------------------------------------


def live_links(seq: Seq, dummy_ports: Optional[Dict[int, object]] = None) -> Set[Link]:
    """Dummy-to-dummy subscriptions that currently exist in the kernel.

    Links with one end outside the dummy client are deliberately invisible
    here: they belong to whatever application made them.
    """
    ports = dummy_ports if dummy_ports is not None else seq.dummy_ports()
    by_addr = {port.addr: number for number, port in ports.items()}
    found = set()
    for sender, dest in seq.connections():
        source_number = by_addr.get(sender)
        dest_number = by_addr.get(dest)
        if source_number is not None and dest_number is not None:
            found.add(Link(source_number, dest_number))
    return found


def apply(seq: Seq, routing: Routing, *, remove_extra: bool = False) -> ApplyReport:
    """Make the kernel match the saved routing.

    With `remove_extra` false -- the default, and what runs at start-up --
    this only adds. Links somebody else made between dummy ports are left
    alone, because silently deleting a route the user set up by hand is not
    a reasonable thing for a start-up task to do. The interface offers
    removal as an explicit action.
    """
    report = ApplyReport()
    ports = seq.dummy_ports()

    wanted = set()
    for link in routing.links():
        if link.source in ports and link.dest in ports:
            wanted.add(link)
        else:
            report.skipped.append(link)

    present = live_links(seq, ports)

    for link in sorted(wanted - present):
        try:
            seq.connect(ports[link.source].addr, ports[link.dest].addr)
            report.added.append(link)
        except AlsaSeqError as exc:
            logger.warning("could not connect %s: %s", link, exc)
            report.failed.append(f"{link}: {exc}")

    if remove_extra:
        for link in sorted(present - wanted):
            try:
                seq.disconnect(ports[link.source].addr, ports[link.dest].addr)
                report.removed.append(link)
            except AlsaSeqError as exc:
                logger.warning("could not disconnect %s: %s", link, exc)
                report.failed.append(f"{link}: {exc}")

    return report


def adopt(routing: Routing, live: Iterable[Link]) -> List[Link]:
    """Record live connections in the saved routing. Returns what was added.

    The pull direction: the kernel is the truth, and whatever is connected
    now becomes something the app will restore later. Purely additive --
    saved routes that are not currently connected stay saved, because a port
    being absent or a route not yet applied is not evidence the user stopped
    wanting it.
    """
    added = [link for link in sorted(live)
             if not routing.has(link.source, link.dest)]
    for link in added:
        routing.add(link.source, link.dest)
    return added


def forget_inactive(routing: Routing, live: Iterable[Link],
                    present: Iterable[int]) -> List[Link]:
    """Drop saved routes that exist but are not connected.

    Only considers routes whose ports are both present. A route for a port
    that does not exist right now is skipped rather than deleted: the usual
    reason is a temporarily lowered port count, and deleting on that basis
    would quietly destroy a setup the user still wants.
    """
    live = set(live)
    present = set(present)
    doomed = [link for link in routing.links()
              if link not in live
              and link.source in present and link.dest in present]
    for link in doomed:
        routing.remove(link.source, link.dest)
    return doomed


def export_links(path: Path, links: Iterable[Link],
                 name_for=None) -> int:
    """Write connections to a file the user chose, and return how many.

    Two audiences at once. A person opening it later needs to recognise what
    the routes were, so each link carries the port names as well as the
    numbers. The application needs to be able to read it back, so the shape
    is the same `{"links": [{"from": n, "to": n}]}` that lmssdr.routing.json
    uses -- the extra keys are ignored on load. Copying this file over
    lmssdr.routing.json restores exactly these routes.
    """
    links = sorted(links)
    payload = {
        "exported": datetime.now().astimezone().isoformat(timespec="seconds"),
        "note": ("Connections found in the ALSA sequencer that were not in "
                 "this application's saved routing. Copy this file over "
                 "lmssdr.routing.json to adopt them."),
        "links": [],
    }
    for link in links:
        entry = {"from": link.source, "to": link.dest}
        if name_for is not None:
            entry["fromName"] = name_for(link.source)
            entry["toName"] = name_for(link.dest)
        payload["links"].append(entry)

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    tmp.replace(path)
    return len(links)


def set_link(seq: Seq, source: int, dest: int, connected: bool) -> None:
    """Create or drop one subscription immediately.

    Raises AlsaSeqError if the ports are not present; the caller knows which
    port the user clicked and can say so.
    """
    ports = seq.dummy_ports()
    if source not in ports or dest not in ports:
        missing = source if source not in ports else dest
        raise AlsaSeqError(f"Midi Through Port-{missing} is not present")
    if connected:
        seq.connect(ports[source].addr, ports[dest].addr)
    else:
        seq.disconnect(ports[source].addr, ports[dest].addr)
