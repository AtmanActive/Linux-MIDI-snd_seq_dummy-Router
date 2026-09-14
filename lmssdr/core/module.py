"""Ownership of the snd_seq_dummy kernel module.

snd_seq_dummy is the only source of MIDI ports this application can offer,
for a reason worth writing down: ALSA reserves sequencer client ids 0-15 for
the kernel, and Chromium's Web MIDI only ever exposes ports whose client id
is below 16. snd_seq_dummy takes id 14. Sound cards land at 16 and above and
userspace clients at 128 and above, so ports from `snd-virmidi`, from JACK,
or from any userspace helper are invisible to browsers. Reaper, separately,
ignores userspace clients too. snd_seq_dummy is the one place both agree on.

Its port count is a module parameter with mode 0444 -- read-only once
loaded -- so changing it means unloading and reloading the module, which
needs root. That is what the polkit helper is for.

Two consequences the user interface must be honest about:

* Reloading destroys every subscription in the sequencer, so saved routing
  has to be re-applied afterwards.
* Chromium enumerates MIDI ports once, when its MIDI service starts, and
  will not see ports created after that. A reload therefore means restarting
  the browser.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

MODULE = "snd_seq_dummy"
SYS_MODULE = Path("/sys/module") / MODULE

#: Our own modprobe.d file, so the port count survives a reboot.
CONF_PATH = Path("/etc/modprobe.d/lmssdr.conf")
MODPROBE_DIR = Path("/etc/modprobe.d")

#: SNDRV_SEQ_MAX_PORTS in include/sound/seq_kernel.h. The module itself only
#: rejects `ports < 1`; this is the kernel's per-client ceiling.
MAX_PORTS = 254
MIN_PORTS = 1
DEFAULT_PORTS = 32

HELPER_NAME = "lmssdr-module-helper"
#: Where the packaged helper lands. Kept in step with the polkit action's
#: exec.path annotation, which must match the binary exactly or the action
#: does not apply and pkexec falls back to asking for the admin password.
HELPER_INSTALLED = Path("/usr/libexec/lmssdr") / HELPER_NAME


@dataclass(frozen=True)
class ModuleState:
    """What the kernel currently has loaded."""

    loaded: bool
    ports: Optional[int] = None
    duplex: Optional[bool] = None
    refcount: int = 0

    def matches(self, wanted_ports: int) -> bool:
        """True when the kernel already provides exactly what we want.

        Duplex mode is always wrong for us: it renames the ports to
        "Port-N:A"/"Port-N:B" and cross-forwards each pair to its partner,
        which is a different routing model from the one this app presents.
        """
        return (self.loaded and self.duplex is False
                and self.ports == wanted_ports)

    def describe(self) -> str:
        if not self.loaded:
            return f"{MODULE} is not loaded"
        duplex = "duplex" if self.duplex else "plain"
        return f"{MODULE}: {self.ports} ports, {duplex}"


def _read(path: Path) -> Optional[str]:
    try:
        return path.read_text().strip()
    except OSError:
        return None


def read_state() -> ModuleState:
    if not SYS_MODULE.is_dir():
        return ModuleState(loaded=False)
    ports = _read(SYS_MODULE / "parameters" / "ports")
    duplex = _read(SYS_MODULE / "parameters" / "duplex")
    refcount = _read(SYS_MODULE / "refcnt")
    return ModuleState(
        loaded=True,
        ports=int(ports) if ports and ports.isdigit() else None,
        # The kernel prints bool parameters as Y/N.
        duplex=None if duplex is None else duplex.upper().startswith("Y"),
        refcount=int(refcount) if refcount and refcount.isdigit() else 0)


def clamp_ports(value: int) -> int:
    return max(MIN_PORTS, min(MAX_PORTS, int(value)))


def conflicting_configs() -> List[Path]:
    """Other modprobe.d files that also set options for this module.

    modprobe concatenates every file in the directory, so a leftover config
    from some earlier experiment can silently win and leave the user staring
    at a port count they did not choose. Worth surfacing rather than
    overwriting someone else's file.
    """
    found = []
    pattern = re.compile(rf"^\s*options\s+{re.escape(MODULE)}\b", re.MULTILINE)
    try:
        candidates = sorted(MODPROBE_DIR.glob("*.conf"))
    except OSError:
        return found
    for path in candidates:
        if path == CONF_PATH:
            continue
        text = _read(path)
        if text and pattern.search(text):
            found.append(path)
    return found


def helper_path() -> Optional[Path]:
    """The privileged helper, installed or running from a checkout."""
    if HELPER_INSTALLED.is_file():
        return HELPER_INSTALLED
    # Development: the copy in the source tree, so the app is usable before
    # anything has been installed.
    local = Path(__file__).resolve().parents[2] / "packaging" / "polkit" / HELPER_NAME
    if local.is_file():
        return local
    return None


@dataclass(frozen=True)
class ApplyResult:
    ok: bool
    message: str
    cancelled: bool = False
    state: Optional[ModuleState] = None


def manual_command(ports: int) -> str:
    """The equivalent commands, for when the helper cannot be run."""
    ports = clamp_ports(ports)
    return (f"echo 'options {MODULE} ports={ports} duplex=0' | "
            f"sudo tee {CONF_PATH}\n"
            f"sudo modprobe -r {MODULE} && sudo modprobe {MODULE} "
            f"ports={ports} duplex=0")


def apply_ports(ports: int, *, timeout: float = 120.0) -> ApplyResult:
    """Reload the module with `ports` ports, asking polkit for permission.

    Returns rather than raises: every failure here is something the user can
    act on, and the interface needs the text either way.
    """
    ports = clamp_ports(ports)
    state = read_state()
    if state.matches(ports):
        return ApplyResult(True, f"Already providing {ports} ports.", state=state)

    helper = helper_path()
    if helper is None:
        return ApplyResult(
            False,
            "The privileged helper is missing, so the port count cannot be "
            "changed from here. Run the commands manually instead.",
            state=state)

    if not shutil.which("pkexec"):
        return ApplyResult(
            False,
            "pkexec is not installed, so the port count cannot be changed "
            "from here. Run the commands manually instead.",
            state=state)

    try:
        proc = subprocess.run(
            ["pkexec", str(helper), "--ports", str(ports)],
            capture_output=True, text=True, timeout=timeout,
            # pkexec needs to find the user's authentication agent.
            env={**os.environ})
    except subprocess.TimeoutExpired:
        return ApplyResult(False, "Timed out waiting for authentication.",
                           state=read_state())
    except OSError as exc:
        return ApplyResult(False, f"Could not run pkexec: {exc}", state=state)

    # 126 is pkexec's "not authorised / dismissed" exit. Treated separately
    # because a cancelled password prompt is a decision, not a failure, and
    # should not be reported as an error.
    if proc.returncode == 126:
        return ApplyResult(False, "Authentication was cancelled.",
                           cancelled=True, state=read_state())

    new_state = read_state()
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        reason = detail[-1] if detail else f"exit code {proc.returncode}"
        if "in use" in reason.lower():
            reason += ("  Close anything using the MIDI Through ports "
                       "(browsers especially) and try again.")
        return ApplyResult(False, reason, state=new_state)

    if not new_state.matches(ports):
        return ApplyResult(
            False,
            f"The helper reported success but the kernel now says "
            f"{new_state.describe()}.", state=new_state)

    return ApplyResult(True, f"Now providing {ports} ports.", state=new_state)
