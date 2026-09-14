from lmssdr.core import autostart


def test_round_trip():
    assert autostart.is_enabled() is False
    assert autostart.set_enabled(True) is True
    assert autostart.entry_path().exists()
    assert autostart.set_enabled(False) is False
    assert not autostart.entry_path().exists()


def test_disabling_twice_is_harmless():
    autostart.set_enabled(False)
    assert autostart.set_enabled(False) is False


def test_entry_contents():
    autostart.set_enabled(True)
    text = autostart.entry_path().read_text()
    assert "[Desktop Entry]" in text
    assert "Type=Application" in text
    assert "Exec=" in text
    assert "Icon=lmssdr" in text


def test_exec_command_is_runnable_as_written():
    """Falls back to the running interpreter, so a checkout autostarts too."""
    command = autostart.exec_command()
    assert command
    assert command.startswith("/") or " -m lmssdr" in command
