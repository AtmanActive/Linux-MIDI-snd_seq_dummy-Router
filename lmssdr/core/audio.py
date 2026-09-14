"""Muting an audio input, through PipeWire's PulseAudio interface.

`pactl` rather than `wpctl`: WirePlumber addresses nodes by numeric id, and
those ids change when a device is unplugged or the graph is rebuilt, so a
setting that remembers one is a setting that silently points at the wrong
device later. Pulse source *names* are stable strings derived from the
hardware, which is what belongs in a config file.

Shelling out rather than binding libpulse: this runs twice per transport
press, so process startup is irrelevant, and it keeps the dependency list at
zero for a feature not everyone will use.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger(__name__)

#: Long enough for a loaded machine, short enough that a wedged pactl cannot
#: hang the MIDI thread through a whole take.
TIMEOUT = 4.0

#: Stored in place of a device name to mean "whatever the desktop calls the
#: default input". Angle brackets because PulseAudio names never contain
#: them, so this can never collide with a real device.
DEFAULT_SOURCE = "<default>"


@dataclass(frozen=True)
class AudioSource:
    """One capture device, as PulseAudio sees it."""

    name: str
    description: str
    muted: bool

    @property
    def is_monitor(self) -> bool:
        """True for an output's loopback rather than a real input.

        Every sink has one, they outnumber the real inputs, and muting one
        does nothing a user would notice -- so they are not offered.
        """
        return self.name.endswith(".monitor")


def available() -> bool:
    return shutil.which("pactl") is not None


def _run(args: List[str]) -> Optional[str]:
    if not available():
        return None
    try:
        proc = subprocess.run(["pactl", *args], capture_output=True,
                              text=True, timeout=TIMEOUT)
    except (OSError, subprocess.TimeoutExpired):
        logger.warning("pactl %s failed", " ".join(args), exc_info=True)
        return None
    if proc.returncode != 0:
        logger.warning("pactl %s: %s", " ".join(args), proc.stderr.strip())
        return None
    return proc.stdout


def sources(include_monitors: bool = False) -> List[AudioSource]:
    """Every capture device, real inputs first."""
    out = _run(["-f", "json", "list", "sources"])
    if not out:
        return []
    try:
        raw = json.loads(out)
    except json.JSONDecodeError:
        logger.warning("could not parse pactl output", exc_info=True)
        return []

    found = []
    for entry in raw:
        if not isinstance(entry, dict) or not entry.get("name"):
            continue
        source = AudioSource(name=str(entry["name"]),
                             description=str(entry.get("description")
                                             or entry["name"]),
                             muted=bool(entry.get("mute", False)))
        if source.is_monitor and not include_monitors:
            continue
        found.append(source)
    return found


def default_source() -> str:
    out = _run(["get-default-source"])
    return out.strip() if out else ""


def is_muted(name: str) -> Optional[bool]:
    """True, False, or None when the device cannot be read."""
    if not name:
        return None
    out = _run(["get-source-mute", name])
    if not out:
        return None
    # "Mute: yes" / "Mute: no"
    text = out.strip().lower()
    if "yes" in text:
        return True
    if "no" in text:
        return False
    return None


def set_mute(name: str, muted: bool) -> bool:
    """Mute or unmute. Returns whether pactl accepted it."""
    if not name:
        return False
    return _run(["set-source-mute", name, "1" if muted else "0"]) is not None


def resolve(name: str) -> str:
    """Turn a stored setting into a device name to act on.

    DEFAULT_SOURCE is looked up now rather than remembered, so the choice
    follows the desktop's default input. It is deliberately *not* re-checked
    on every message: a microphone that changed identity mid-take because
    something else was plugged in would be worse than one that stayed put.
    Resolution happens when the listener starts -- at application start, or
    when the feature is switched on or reconfigured.
    """
    if name == DEFAULT_SOURCE:
        return default_source()
    return name


def describe(name: str) -> str:
    """A readable label for a source name, falling back to the name."""
    if name == DEFAULT_SOURCE:
        return describe(default_source()) or "system default input"
    for source in sources(include_monitors=True):
        if source.name == name:
            return source.description
    return name
