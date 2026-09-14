import tomllib
from pathlib import Path

import lmssdr


def _pyproject():
    root = Path(__file__).resolve().parents[1]
    return tomllib.loads((root / "pyproject.toml").read_text())


def test_homepage_matches_package():
    assert _pyproject()["project"]["urls"]["Homepage"] == lmssdr.APP_HOMEPAGE


def test_version_is_dynamic_from_the_package():
    assert "version" in _pyproject()["project"]["dynamic"]
    assert lmssdr.__version__
