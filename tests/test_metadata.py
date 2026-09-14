import tomllib
from pathlib import Path

import pytest

import lmssdr


def _pyproject():
    root = Path(__file__).resolve().parents[1]
    return tomllib.loads((root / "pyproject.toml").read_text())


def test_homepage_matches_package():
    assert _pyproject()["project"]["urls"]["Homepage"] == lmssdr.APP_HOMEPAGE


def test_version_is_dynamic_from_the_package():
    assert "version" in _pyproject()["project"]["dynamic"]
    assert lmssdr.__version__


def test_the_alsa_client_names_follow_the_app_title():
    """What other MIDI software sees must be the application's own name.

    These are the two places the name is not read from APP_TITLE at the point
    of use, and they are exactly the two that were missed the last time the
    application was renamed.
    """
    import inspect

    from lmssdr.core import mute
    from lmssdr.core.alsaseq import Seq

    # The binding's fallback, for anyone importing it on its own.
    default = inspect.signature(Seq.__init__).parameters["name"].default
    assert default == lmssdr.APP_TITLE

    # The mute listener's own client, built from APP_TITLE at run time.
    assert "APP_TITLE" in inspect.getsource(mute.MuteService._run)


def test_the_packaged_desktop_entry_matches_the_app():
    """The start-menu name and the window title must not disagree."""
    entry = Path(__file__).resolve().parents[1] / "packaging" / "lmssdr.desktop"
    fields = dict(line.split("=", 1) for line in entry.read_text().splitlines()
                  if "=" in line and not line.startswith("#"))
    assert fields["Name"] == lmssdr.APP_TITLE
    assert fields["Icon"] == "lmssdr"


def test_the_packaged_desktop_entry_is_valid():
    """Checked by the real validator rather than a hand-rolled imitation.

    An earlier version of this test reimplemented the freedesktop category
    rules and got them wrong: Audio *is* a main category, but pairing it with
    AudioVideo is what the spec asks for. desktop-file-validate knows that
    and a dozen other rules; skipped where it is not installed.
    """
    import shutil
    import subprocess

    tool = shutil.which("desktop-file-validate")
    if tool is None:
        pytest.skip("desktop-file-utils is not installed")
    entry = Path(__file__).resolve().parents[1] / "packaging" / "lmssdr.desktop"
    result = subprocess.run([tool, str(entry)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    # Hints are printed on success, so an empty output is the real bar.
    assert not result.stdout.strip(), result.stdout
