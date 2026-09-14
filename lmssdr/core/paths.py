"""Where the application keeps its state.

Three separate files rather than one, because they have different lifetimes
and different blast radii: losing the routing should never cost you the port
names you spent an evening choosing.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

APP_DIR_NAME = "lmssdr"

#: Directories earlier versions used, newest first.
LEGACY_APP_DIR_NAMES = ("lmsdr",)


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
    return Path(base) / APP_DIR_NAME


def migrate_config_dir() -> None:
    """Rename the whole configuration directory from an earlier name.

    Done before any file is read, and only when the current directory does
    not exist -- so it cannot merge two sets of settings, and running an
    older build afterwards simply finds nothing rather than half a config.
    """
    current = config_dir()
    if current.exists():
        return
    for name in LEGACY_APP_DIR_NAMES:
        legacy = current.parent / name
        if not legacy.is_dir():
            continue
        try:
            current.parent.mkdir(parents=True, exist_ok=True)
            legacy.replace(current)
            logger.info("renamed config directory %s to %s", legacy, current)
        except OSError:
            logger.warning("could not rename %s to %s", legacy, current,
                           exc_info=True)
        return


def migrate(legacy: Path, current: Path) -> None:
    """Rename a config file that an earlier version wrote under another name.

    Done once, on load, and only when the new name does not already exist --
    so it cannot clobber a real file, and running an old build afterwards
    simply sees no config rather than a corrupted one.
    """
    if current.exists() or not legacy.exists():
        return
    try:
        current.parent.mkdir(parents=True, exist_ok=True)
        legacy.replace(current)
        logger.info("renamed %s to %s", legacy.name, current.name)
    except OSError:
        logger.warning("could not rename %s to %s", legacy, current, exc_info=True)


def read_json(path: Path, default: Any) -> Any:
    """Load JSON, falling back to `default` on anything unreadable.

    A corrupt file must never stop the application starting: the user would
    have no way to fix it from an app that will not open.
    """
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return default
    except (OSError, json.JSONDecodeError):
        logger.warning("could not read %s; using defaults", path, exc_info=True)
        return default


def write_json(path: Path, payload: Any) -> None:
    """Write JSON atomically, so a crash mid-write cannot truncate the file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
    tmp.replace(path)
