"""The PulseAudio wrapper. No pactl is run: subprocess is stubbed."""

import json
import subprocess

import pytest

from lmssdr.core import audio

SAMPLE = json.dumps([
    {"name": "alsa_input.usb-webcam.analog-stereo",
     "description": "ViewSonic HD webcam Analog Stereo", "mute": False},
    {"name": "alsa_output.pci-0000_00_1f.3.iec958-stereo.monitor",
     "description": "Built-in Audio Monitor", "mute": False},
    {"name": "alsa_input.pci-0000_0a_00.0.multichannel-input",
     "description": "RME Hammerfall DSP MADI Multichannel", "mute": True},
])


@pytest.fixture
def fake_pactl(monkeypatch):
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        if args[1:3] == ["-f", "json"]:
            return subprocess.CompletedProcess(args, 0, SAMPLE, "")
        if args[1] == "get-source-mute":
            return subprocess.CompletedProcess(args, 0, "Mute: yes\n", "")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(audio.shutil, "which", lambda _: "/usr/bin/pactl")
    monkeypatch.setattr(audio.subprocess, "run", run)
    return calls


def test_monitors_are_excluded_by_default(fake_pactl):
    names = [s.name for s in audio.sources()]
    assert len(names) == 2
    assert not any(n.endswith(".monitor") for n in names)


def test_monitors_can_be_included(fake_pactl):
    assert len(audio.sources(include_monitors=True)) == 3


def test_mute_state_is_read(fake_pactl):
    sources = {s.name: s for s in audio.sources()}
    assert sources["alsa_input.pci-0000_0a_00.0.multichannel-input"].muted is True


def test_set_mute_passes_the_right_argument(fake_pactl):
    audio.set_mute("dev", True)
    audio.set_mute("dev", False)
    assert fake_pactl[-2] == ["pactl", "set-source-mute", "dev", "1"]
    assert fake_pactl[-1] == ["pactl", "set-source-mute", "dev", "0"]


def test_set_mute_refuses_an_empty_name(fake_pactl):
    assert audio.set_mute("", True) is False


def test_is_muted_parses_the_answer(fake_pactl):
    assert audio.is_muted("dev") is True


def test_everything_degrades_when_pactl_is_missing(monkeypatch):
    monkeypatch.setattr(audio.shutil, "which", lambda _: None)
    assert audio.available() is False
    assert audio.sources() == []
    assert audio.is_muted("dev") is None
    assert audio.set_mute("dev", True) is False


def test_unparseable_output_is_survived(monkeypatch):
    monkeypatch.setattr(audio.shutil, "which", lambda _: "/usr/bin/pactl")
    monkeypatch.setattr(audio.subprocess, "run",
                        lambda a, **k: subprocess.CompletedProcess(a, 0, "{{{", ""))
    assert audio.sources() == []


def test_a_timeout_does_not_raise(monkeypatch):
    monkeypatch.setattr(audio.shutil, "which", lambda _: "/usr/bin/pactl")

    def boom(*a, **k):
        raise subprocess.TimeoutExpired("pactl", 4)

    monkeypatch.setattr(audio.subprocess, "run", boom)
    assert audio.sources() == []
    assert audio.set_mute("dev", True) is False


# -- the default-input sentinel -------------------------------------------

def test_sentinel_cannot_collide_with_a_device_name():
    """PulseAudio names are ASCII identifiers; angle brackets never appear."""
    assert audio.DEFAULT_SOURCE == "<default>"


def test_resolve_looks_up_the_default(monkeypatch):
    monkeypatch.setattr(audio, "default_source", lambda: "alsa_input.real")
    assert audio.resolve(audio.DEFAULT_SOURCE) == "alsa_input.real"


def test_resolve_passes_an_explicit_name_through(monkeypatch):
    monkeypatch.setattr(audio, "default_source", lambda: "alsa_input.other")
    assert audio.resolve("alsa_input.chosen") == "alsa_input.chosen"


def test_resolve_survives_having_no_default(monkeypatch):
    monkeypatch.setattr(audio, "default_source", lambda: "")
    assert audio.resolve(audio.DEFAULT_SOURCE) == ""


def test_describe_the_default_names_the_real_device(fake_pactl, monkeypatch):
    monkeypatch.setattr(audio, "default_source",
                        lambda: "alsa_input.usb-webcam.analog-stereo")
    assert audio.describe(audio.DEFAULT_SOURCE) == "ViewSonic HD webcam Analog Stereo"


def test_describe_the_default_with_none_set(fake_pactl, monkeypatch):
    monkeypatch.setattr(audio, "default_source", lambda: "")
    assert audio.describe(audio.DEFAULT_SOURCE) == "system default input"
