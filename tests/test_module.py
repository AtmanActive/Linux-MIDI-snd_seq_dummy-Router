from pathlib import Path

import pytest

from lmssdr.core import module
from lmssdr.core.module import ModuleState, clamp_ports, manual_command


def test_clamp():
    assert clamp_ports(0) == 1
    assert clamp_ports(-5) == 1
    assert clamp_ports(32) == 32
    assert clamp_ports(1000) == 254


@pytest.mark.parametrize("state, wanted, expected", [
    (ModuleState(loaded=True, ports=32, duplex=False), 32, True),
    (ModuleState(loaded=True, ports=32, duplex=False), 20, False),
    # Duplex is always wrong: the ports are named Port-N:A/:B and cross-
    # forward to their partner, which is a different model entirely.
    (ModuleState(loaded=True, ports=32, duplex=True), 32, False),
    (ModuleState(loaded=False), 32, False),
    (ModuleState(loaded=True, ports=None, duplex=False), 32, False),
])
def test_matches(state, wanted, expected):
    assert state.matches(wanted) is expected


def test_describe():
    assert "not loaded" in ModuleState(loaded=False).describe()
    assert "20 ports" in ModuleState(loaded=True, ports=20, duplex=False).describe()
    assert "duplex" in ModuleState(loaded=True, ports=20, duplex=True).describe()


def test_manual_command_mentions_both_steps():
    text = manual_command(32)
    assert "ports=32 duplex=0" in text
    assert "modprobe -r snd_seq_dummy" in text
    assert str(module.CONF_PATH) in text


def test_manual_command_clamps():
    assert "ports=254" in manual_command(9999)


def test_conflicting_configs(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "MODPROBE_DIR", tmp_path)
    monkeypatch.setattr(module, "CONF_PATH", tmp_path / "lmssdr.conf")

    (tmp_path / "lmssdr.conf").write_text("options snd_seq_dummy ports=32 duplex=0\n")
    (tmp_path / "other.conf").write_text("options snd_seq_dummy ports=8\n")
    (tmp_path / "unrelated.conf").write_text("options snd_hda_intel foo=1\n")
    (tmp_path / "commented.conf").write_text("# options snd_seq_dummy ports=99\n")

    found = [p.name for p in module.conflicting_configs()]
    assert found == ["other.conf"]      # our own file and non-matches excluded


def test_apply_refuses_without_helper(monkeypatch):
    monkeypatch.setattr(module, "helper_path", lambda: None)
    monkeypatch.setattr(module, "read_state",
                        lambda: ModuleState(loaded=True, ports=8, duplex=False))
    result = module.apply_ports(32)
    assert result.ok is False
    assert "helper" in result.message.lower()


def test_apply_is_a_no_op_when_already_correct(monkeypatch):
    monkeypatch.setattr(module, "read_state",
                        lambda: ModuleState(loaded=True, ports=32, duplex=False))
    called = []
    monkeypatch.setattr(module.subprocess, "run",
                        lambda *a, **k: called.append(a))
    result = module.apply_ports(32)
    assert result.ok is True
    assert called == []                 # no password prompt for nothing
