"""XDG autostart entry management.

The Exec line points at however this copy is actually runnable: the installed
console script if there is one, otherwise the interpreter and module running
right now, so a checkout started with `python -m lmssdr` autostarts correctly
too.
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
from pathlib import Path

from .. import APP_TITLE

logger = logging.getLogger(__name__)

ENTRY_NAME = "lmssdr.desktop"


def autostart_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
    return Path(base) / "autostart"


def entry_path() -> Path:
    return autostart_dir() / ENTRY_NAME


def exec_command() -> str:
    script = shutil.which("lmssdr")
    if script:
        return script
    return f"{sys.executable} -m lmssdr"


def is_enabled() -> bool:
    return entry_path().exists()


def set_enabled(enabled: bool) -> bool:
    """Create or remove the autostart entry. Returns the resulting state."""
    path = entry_path()
    if not enabled:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            logger.warning("could not remove %s", path, exc_info=True)
        return is_enabled()

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "[Desktop Entry]\n"
            "Type=Application\n"
            f"Name={APP_TITLE}\n"
            "Comment=Route ALSA MIDI Through ports and mute on DAW transport\n"
            f"Exec={exec_command()}\n"
            "Icon=lmssdr\n"
            "Terminal=false\n"
            "X-GNOME-Autostart-enabled=true\n"
        )
    except OSError:
        logger.warning("could not write %s", path, exc_info=True)
    return is_enabled()
