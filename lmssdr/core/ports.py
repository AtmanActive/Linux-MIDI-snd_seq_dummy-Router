"""Custom port names and remarks.

Kernel port names cannot be changed. ALSA refuses to rename another client's
port outright -- `snd_seq_ioctl_set_port_info` returns EPERM unless you own
the port -- and snd_seq_dummy hardcodes "Midi Through Port-N" regardless. So
the names the user cares about live here, keyed by port number, and the
interface shows both: the name they chose and the name every other
application on the system will show them.

Keyed by port *number*, not by sequencer address: the client id can change
across a module reload, but "port 7" stays the seventh port.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional

from .paths import (config_dir, migrate, migrate_config_dir,
                    read_json, write_json)

FILE_NAME = "lmssdr.ports.json"

#: Colours a port can be tagged with, in the order they are offered.
#:
#: Stored by NAME, not by hex: the file stays readable, and adjusting a shade
#: later changes every port tagged with it instead of leaving old ports on an
#: old value. Every one is mid-tone so white text sits on it legibly and it
#: reads against both the light and the dark background.
PORT_COLOURS: Dict[str, str] = {
    "Red":     "#e05a5a",
    "Orange":  "#e07a3c",
    "Amber":   "#d99a2b",
    "Yellow":  "#c9b52e",
    "Lime":    "#8fb63a",
    "Green":   "#4caf6d",
    "Teal":    "#21a5b8",
    "Cyan":    "#2bb3d6",
    "Sky":     "#4a9fe0",
    "Blue":    "#5c7ded",
    "Indigo":  "#7a6fe0",
    "Violet":  "#9b7ede",
    "Magenta": "#c264d6",
    "Pink":    "#e07aa8",
    "Grey":    "#8b93a3",
}
PORT_COLOUR_NAMES: List[str] = list(PORT_COLOURS)


def colour_hex(name: str) -> str:
    """The hex for a colour name, or "" for none and for anything unknown."""
    return PORT_COLOURS.get(name, "")
#: What this file was called in earlier versions, newest
#: first. Renamed on load, one hop at a time.
LEGACY_FILE_NAMES = ("lmsdr.ports.json", "ports.json")


def kernel_name(number: int) -> str:
    """What the rest of the system calls this port."""
    return f"Midi Through Port-{number}"


def matches(info: "PortInfo", query: str) -> bool:
    """Does this port match a search query?

    Searches all three names a port has at once -- the kernel name, the
    custom name and the remark -- because the user should not have to
    remember which field they put a word in. Typing "drums" finds the port
    whether "drums" is its name or only mentioned in its remark.

    Whitespace-separated terms are ANDed, so "keys ret" narrows to "Keys
    Return" without matching every port with "return" in it. Searching the
    kernel name also means a bare number works: "7" finds Port-7.
    """
    terms = query.lower().split()
    if not terms:
        return True
    haystack = f"{info.kernel_name} {info.name} {info.remark}".lower()
    return all(term in haystack for term in terms)


@dataclass
class PortInfo:
    """One port's user-assigned identity."""

    number: int
    name: str = ""
    remark: str = ""
    #: A key of PORT_COLOURS, or "" for untagged.
    colour: str = ""

    @property
    def kernel_name(self) -> str:
        return kernel_name(self.number)

    @property
    def has_name(self) -> bool:
        return bool(self.name.strip())

    @property
    def colour_hex(self) -> str:
        return colour_hex(self.colour)

    @property
    def display_name(self) -> str:
        """The custom name if there is one, else the kernel name.

        Used where only one string fits -- a menu, a tooltip, the routing
        graph. Anywhere with room shows both.
        """
        return self.name.strip() if self.has_name else self.kernel_name

    @property
    def label(self) -> str:
        """Both names, for lists that have room for a subtitle."""
        if not self.has_name:
            return self.kernel_name
        return f"{self.name.strip()}  ({self.kernel_name})"


class PortNames:
    """The lmssdr.ports.json database.

    Entries persist for ports that do not currently exist. Shrinking the port
    count and growing it again must not silently discard the names for the
    ports that went away -- that would be a destructive side effect of a
    setting the user may well be experimenting with.
    """

    def __init__(self, entries: Optional[Dict[int, PortInfo]] = None):
        self._entries: Dict[int, PortInfo] = dict(entries or {})

    # -- persistence -----------------------------------------------------

    @classmethod
    def path(cls) -> Path:
        return config_dir() / FILE_NAME

    @classmethod
    def load(cls) -> "PortNames":
        migrate_config_dir()
        for legacy in LEGACY_FILE_NAMES:
            migrate(config_dir() / legacy, cls.path())
        raw = read_json(cls.path(), {})
        entries: Dict[int, PortInfo] = {}
        for key, value in (raw.get("ports") or {}).items():
            try:
                number = int(key)
            except (TypeError, ValueError):
                continue
            if not isinstance(value, dict):
                continue
            colour = str(value.get("colour", ""))
            entries[number] = PortInfo(
                number=number,
                name=str(value.get("name", "")),
                remark=str(value.get("remark", "")),
                # An unknown name becomes untagged rather than an error: the
                # file may come from a version with a different palette.
                colour=colour if colour in PORT_COLOURS else "")
        return cls(entries)

    def save(self) -> None:
        payload = {
            "ports": {
                str(info.number): {"name": info.name, "remark": info.remark,
                                   "colour": info.colour}
                for info in self._entries.values()
                # Do not persist rows the user has emptied again.
                if info.name.strip() or info.remark.strip() or info.colour
            }
        }
        write_json(self.path(), payload)

    # -- access ----------------------------------------------------------

    def get(self, number: int) -> PortInfo:
        """The entry for a port, creating an empty one on demand."""
        info = self._entries.get(number)
        if info is None:
            info = PortInfo(number=number)
            self._entries[number] = info
        return info

    def set_name(self, number: int, name: str) -> PortInfo:
        info = self.get(number)
        info.name = name.strip()
        return info

    def set_remark(self, number: int, remark: str) -> PortInfo:
        info = self.get(number)
        info.remark = remark.strip()
        return info

    def set_colour(self, number: int, colour: str) -> PortInfo:
        """Tag a port, or untag it with "" or an unknown name."""
        info = self.get(number)
        info.colour = colour if colour in PORT_COLOURS else ""
        return info

    def swap(self, a: int, b: int) -> bool:
        """Exchange everything the user assigned to two ports.

        The number and the kernel name stay put -- those belong to ALSA and
        cannot move. What moves is the identity the user gave the port: its
        alias, its remark and its colour.
        """
        if a == b:
            return False
        first, second = self.get(a), self.get(b)
        first.name, second.name = second.name, first.name
        first.remark, second.remark = second.remark, first.remark
        first.colour, second.colour = second.colour, first.colour
        return True

    def display_name(self, number: int) -> str:
        return self.get(number).display_name

    def filter(self, numbers: Iterable[int], query: str) -> List[int]:
        """Those of `numbers` whose port matches `query`, order preserved."""
        if not query.strip():
            return list(numbers)
        return [n for n in numbers if matches(self.get(n), query)]

    def named(self) -> Iterator[PortInfo]:
        """Only the ports the user has actually named."""
        for info in sorted(self._entries.values(), key=lambda i: i.number):
            if info.has_name:
                yield info

    def rows(self, count: int) -> list[PortInfo]:
        """One entry per live port, 0..count-1, in order."""
        return [self.get(n) for n in range(count)]

    def __len__(self) -> int:
        return len(self._entries)
