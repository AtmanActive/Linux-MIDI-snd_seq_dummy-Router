import pytest

from lmssdr.ui import theming


@pytest.mark.parametrize("name", theming.THEME_NAMES)
@pytest.mark.parametrize("dark", [True, False])
def test_palette_is_complete(name, dark):
    pal = theming.build_palette(name, dark)
    for key in ("bg", "surface", "line", "text", "dim", "accent",
                "warn", "ok", "danger", "isDark"):
        assert key in pal
    for key, value in pal.items():
        if key == "isDark":
            continue
        assert value.startswith("#") and len(value) == 7, (key, value)


def test_is_dark_flag_is_a_qml_friendly_string():
    # QML reads the palette as a string map, so booleans travel as "1"/"0".
    assert theming.build_palette("Ocean", True)["isDark"] == "1"
    assert theming.build_palette("Ocean", False)["isDark"] == "0"


def test_unknown_theme_falls_back_rather_than_raising():
    assert theming.build_palette("Nonexistent", True)["accent"] == theming.THEMES["Ocean"]


def test_light_and_dark_differ():
    assert theming.build_palette("Ocean", True) != theming.build_palette("Ocean", False)


def test_status_colours_do_not_follow_the_accent():
    """A red danger badge must stay red in the Forest theme."""
    a = theming.build_palette("Forest", True)
    b = theming.build_palette("Crimson", True)
    assert a["danger"] == b["danger"]
    assert a["ok"] == b["ok"]
    assert a["accent"] != b["accent"]


@pytest.mark.parametrize("mode, system_dark, expected", [
    ("dark", False, True),
    ("light", True, False),
    ("system", True, True),
    ("system", False, False),
])
def test_resolve_mode(mode, system_dark, expected):
    assert theming.resolve_mode(mode, system_dark) is expected


def test_text_sizes_include_default_at_unity():
    assert theming.TEXT_SIZES["default"] == 1.0
