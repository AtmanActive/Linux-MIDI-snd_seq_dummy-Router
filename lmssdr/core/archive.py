"""Export and import the whole configuration as one ZIP file.

Three JSON files hold everything the application knows, and they are the sort
of thing people want to move between machines, keep before an experiment, or
attach to a bug report. Zipping them is the difference between "back up your
config" and a button.

Two rules shape the import side, and both are about not trusting the file:

* Nothing in the archive decides where anything is written. Members are
  matched by *base name* against the registry below, and the destination
  comes from the registry, never from the archive. A member called
  ``../../.bashrc`` simply is not recognized, and a recognized member cannot
  land anywhere but the config directory.
* A member is parsed and validated before a single existing file is touched.
  A truncated download should fail with a message, not half-overwrite a
  routing setup.

The archive is read in memory rather than unpacked to a temporary directory:
these files are a few kilobytes, and not writing them out means there is no
temporary state to clean up, no race with a second import, and no window in
which a half-extracted config exists on disk.
"""

from __future__ import annotations

import json
import logging
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from . import ports as ports_mod
from . import routing as routing_mod
from . import settings as settings_mod
from .paths import config_dir, write_json

logger = logging.getLogger(__name__)

#: Written into every archive so its origin is readable without this app.
MANIFEST_NAME = "lmssdr.manifest.json"

#: Refuse to read a member larger than this. These files are kilobytes; a
#: hundred megabytes of "settings" is a zip bomb or a mistake, and either way
#: it should not be loaded into memory to find out.
MAX_MEMBER_BYTES = 8 * 1024 * 1024

#: Kept alongside an imported file, so an import that turns out to be the
#: wrong archive is recoverable. One generation only: the point is an undo
#: for the last import, not a history.
BACKUP_SUFFIX = ".pre-import"


def _summarise_settings(data: Any) -> str:
    if not isinstance(data, dict):
        return "unreadable"
    bits = [f"{data.get('port_count', '?')} ports"]
    theme = data.get("theme_name")
    if theme:
        bits.append(f"{theme} theme")
    if data.get("mute_enabled"):
        bits.append("mute on")
    return ", ".join(bits)


def _summarise_ports(data: Any) -> str:
    entries = (data or {}).get("ports") if isinstance(data, dict) else None
    if not isinstance(entries, dict):
        return "no named ports"
    named = sum(1 for v in entries.values()
                if isinstance(v, dict) and (v.get("name") or v.get("remark")))
    coloured = sum(1 for v in entries.values()
                   if isinstance(v, dict) and v.get("colour"))
    bits = [f"{named} named port{'' if named == 1 else 's'}"]
    if coloured:
        bits.append(f"{coloured} coloured")
    return ", ".join(bits)


def _summarise_routing(data: Any) -> str:
    links = (data or {}).get("links") if isinstance(data, dict) else None
    count = len(links) if isinstance(links, list) else 0
    return f"{count} route{'' if count == 1 else 's'}"


@dataclass(frozen=True)
class DataFile:
    """One of the application's JSON stores.

    The registry is the single place that knows the set. Adding a fourth
    store later means adding a line here, and export, the import picker and
    the tests all pick it up.
    """

    key: str
    filename: str
    label: str
    describe: str
    #: Names earlier versions used. Recognized on import so a backup taken
    #: before a rename still restores, and written to the current name.
    legacy: Tuple[str, ...] = ()
    summarise: Callable[[Any], str] = lambda data: ""

    @property
    def path(self) -> Path:
        return config_dir() / self.filename

    def names(self) -> Tuple[str, ...]:
        return (self.filename,) + self.legacy


REGISTRY: Tuple[DataFile, ...] = (
    DataFile("settings", settings_mod.FILE_NAME, "Settings",
             "Port count, appearance, startup and the mute rules.",
             settings_mod.LEGACY_FILE_NAMES, _summarise_settings),
    DataFile("ports", ports_mod.FILE_NAME, "Port names",
             "Your aliases, remarks and colours for each port.",
             ports_mod.LEGACY_FILE_NAMES, _summarise_ports),
    DataFile("routing", routing_mod.FILE_NAME, "Routing",
             "Which port is connected to which.",
             routing_mod.LEGACY_FILE_NAMES, _summarise_routing),
)


def registry_for(key: str) -> Optional[DataFile]:
    return next((d for d in REGISTRY if d.key == key), None)


def _match(member: str) -> Optional[DataFile]:
    """Which store a ZIP member is, by base name only.

    Base name only is the whole defence against a crafted archive: whatever
    directory a member claims to live in is discarded before it is compared,
    and the destination comes from the registry afterwards.
    """
    name = Path(member).name
    for entry in REGISTRY:
        if name in entry.names():
            return entry
    return None


# -- export ---------------------------------------------------------------

def suggested_name(now: Optional[datetime] = None) -> str:
    stamp = (now or datetime.now()).strftime("%Y-%m-%d")
    return f"lmssdr.backup.{stamp}.zip"


def exportable() -> List[DataFile]:
    """The stores that actually exist on disk right now."""
    return [entry for entry in REGISTRY if entry.path.exists()]


def export_archive(dest: Path, version: str = "") -> List[str]:
    """Write every existing store into one ZIP. Returns the names written.

    Deflated, though these files compress from nothing to nothing: it costs
    microseconds and means the archive opens the way anyone expects.
    """
    written: List[str] = []
    dest.parent.mkdir(parents=True, exist_ok=True)
    present = exportable()
    manifest = {
        "application": "lmssdr",
        "version": version,
        "exported": datetime.now().isoformat(timespec="seconds"),
        "files": [entry.filename for entry in present],
    }
    # Written to a temporary name and moved into place, so an interrupted
    # export cannot leave a half-written archive where a good one was.
    tmp = dest.with_name(dest.name + ".part")
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(MANIFEST_NAME,
                        json.dumps(manifest, indent=2, sort_keys=True))
            for entry in present:
                zf.write(entry.path, entry.filename)
                written.append(entry.filename)
        tmp.replace(dest)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    logger.info("exported %d file(s) to %s", len(written), dest)
    return written


# -- import ---------------------------------------------------------------

@dataclass(frozen=True)
class ArchiveItem:
    """One recognized store inside an archive, ready to be offered."""

    key: str
    label: str
    describe: str
    #: The name it had *in the archive*, which may be a legacy name.
    member: str
    summary: str
    payload: Any


class ArchiveError(Exception):
    """The archive cannot be used, with a sentence saying why."""


def inspect_archive(path: Path) -> List[ArchiveItem]:
    """Read an archive and return what of ours is in it.

    Raises ArchiveError when the file is not a usable ZIP. Returns an empty
    list when it is a perfectly good ZIP with nothing of ours inside -- a
    different situation, and the interface says so differently.
    """
    try:
        with zipfile.ZipFile(path) as zf:
            found: Dict[str, ArchiveItem] = {}
            for info in zf.infolist():
                if info.is_dir():
                    continue
                entry = _match(info.filename)
                if entry is None or entry.key in found:
                    continue
                if info.file_size > MAX_MEMBER_BYTES:
                    raise ArchiveError(
                        f"{Path(info.filename).name} is implausibly large "
                        f"({info.file_size} bytes) and was not read.")
                raw = zf.read(info)
                try:
                    payload = json.loads(raw)
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise ArchiveError(
                        f"{Path(info.filename).name} in this archive is not "
                        f"valid JSON: {exc}") from exc
                if not isinstance(payload, dict):
                    raise ArchiveError(
                        f"{Path(info.filename).name} in this archive does not "
                        f"contain a JSON object.")
                found[entry.key] = ArchiveItem(
                    key=entry.key, label=entry.label, describe=entry.describe,
                    member=info.filename, summary=entry.summarise(payload),
                    payload=payload)
    except ArchiveError:
        raise
    except zipfile.BadZipFile as exc:
        raise ArchiveError(f"This is not a readable ZIP file: {exc}") from exc
    except OSError as exc:
        raise ArchiveError(f"Could not open the file: {exc}") from exc

    # Registry order, not archive order: the picker should read the same way
    # every time regardless of how the zip was built.
    order = [entry.key for entry in REGISTRY]
    return sorted(found.values(), key=lambda item: order.index(item.key))


def import_items(items: Sequence[ArchiveItem],
                 keys: Optional[Sequence[str]] = None) -> List[str]:
    """Write the chosen stores into the config directory. Returns the keys.

    The payloads were parsed during inspection, so by the time anything is
    overwritten the content is known to be good. Each existing file is kept
    as `<name>.pre-import` first: importing the wrong archive is an easy
    mistake and an expensive one without an undo.
    """
    wanted = set(keys) if keys is not None else {item.key for item in items}
    done: List[str] = []
    for item in items:
        if item.key not in wanted:
            continue
        entry = registry_for(item.key)
        if entry is None:            # unreachable; a key came from REGISTRY
            continue
        target = entry.path
        if target.exists():
            try:
                backup = target.with_name(target.name + BACKUP_SUFFIX)
                backup.write_bytes(target.read_bytes())
            except OSError:
                # Not fatal. Failing the import because the undo copy could
                # not be made would be the tail wagging the dog.
                logger.warning("could not back up %s", target, exc_info=True)
        write_json(target, item.payload)
        done.append(item.key)
        logger.info("imported %s from %s", entry.filename, item.member)
    return done
