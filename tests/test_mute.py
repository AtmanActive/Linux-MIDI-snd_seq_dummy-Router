"""The mute rule engine.

Exhaustive on purpose: the failure mode of this feature is a live microphone
during a take, or a dead one during a talkback, and neither announces itself.
"""

import pytest

from lmssdr.core.alsaseq import Addr, MidiEvent
from lmssdr.core.mute import (STATE_IDLE, STATE_MUTED, STATE_OPEN,
                             STATE_TALKBACK, MuteEngine, MuteRules)

SRC = Addr(14, 1)


def play(velocity=127, channel=1, note=94):
    return MidiEvent("noteon", channel, note, velocity, SRC)


def stop(velocity=127, channel=1, note=93):
    return MidiEvent("noteon", channel, note, velocity, SRC)


def talkback(value, channel=14, cc=14):
    return MidiEvent("cc", channel, cc, value, SRC)


@pytest.fixture
def engine():
    return MuteEngine()


# -- transport ------------------------------------------------------------

def test_starts_idle(engine):
    """Not "open": nothing has said where the transport is."""
    assert engine.state == STATE_IDLE
    assert engine.should_mute is False


def test_the_first_recognized_message_leaves_idle(engine):
    """Even a Stop, which does not move play/talkback, ends the idle state."""
    assert engine.on_transport(stop()) is True
    assert engine.state == STATE_OPEN
    assert engine.seen is True


def test_a_second_stop_reports_no_change(engine):
    engine.on_transport(stop())
    assert engine.on_transport(stop()) is False


def test_an_unrecognized_message_leaves_the_engine_idle(engine):
    """Blue means nothing was heard -- not that nothing arrived."""
    engine.on_transport(play(channel=2))
    engine.on_transport(play(note=60))
    engine.on_talkback(talkback(127, cc=7))
    assert engine.state == STATE_IDLE
    assert engine.seen is False


def test_play_mutes_and_stop_unmutes(engine):
    assert engine.on_transport(play()) is True
    assert engine.state == STATE_MUTED and engine.should_mute is True
    assert engine.on_transport(stop()) is True
    assert engine.state == STATE_OPEN and engine.should_mute is False


def test_repeated_play_does_not_report_a_change(engine):
    engine.on_transport(play())
    assert engine.on_transport(play()) is False


def test_transport_ignores_the_wrong_channel(engine):
    assert engine.on_transport(play(channel=2)) is False
    assert engine.state == STATE_IDLE


def test_transport_ignores_the_wrong_note(engine):
    assert engine.on_transport(play(note=60)) is False


def test_transport_ignores_a_low_velocity(engine):
    """Mackie sends 127; anything else is a different gesture."""
    assert engine.on_transport(play(velocity=64)) is False
    assert engine.state == STATE_IDLE


def test_a_note_off_never_moves_the_transport(engine):
    engine.on_transport(play())
    off = MidiEvent("noteoff", 1, 94, 0, SRC)
    assert engine.on_transport(off) is False
    assert engine.state == STATE_MUTED


def test_a_zero_velocity_note_on_is_a_note_off(engine):
    """Decoded upstream as noteoff, so it must not trigger the transport."""
    assert engine.on_transport(MidiEvent("noteoff", 1, 94, 0, SRC)) is False


# -- talkback -------------------------------------------------------------

def test_talkback_opens_the_microphone_while_playing(engine):
    engine.on_transport(play())
    assert engine.on_talkback(talkback(127)) is True
    assert engine.state == STATE_TALKBACK
    assert engine.should_mute is False


def test_releasing_talkback_restores_the_mute(engine):
    engine.on_transport(play())
    engine.on_talkback(talkback(127))
    assert engine.on_talkback(talkback(0)) is True
    assert engine.state == STATE_MUTED and engine.should_mute is True


def test_talkback_is_ignored_while_stopped(engine):
    """Nothing to hold open, and nothing to restore on release."""
    engine.on_transport(stop())
    assert engine.on_talkback(talkback(127)) is False
    assert engine.state == STATE_OPEN
    assert engine.on_talkback(talkback(0)) is False
    assert engine.state == STATE_OPEN


def test_talkback_from_idle_only_ends_the_idle_state(engine):
    """It counts as heard, but it must not hold anything open."""
    assert engine.on_talkback(talkback(127)) is True
    assert engine.state == STATE_OPEN
    assert engine.talkback is False


def test_talkback_ignores_the_wrong_channel_or_controller(engine):
    engine.on_transport(play())
    assert engine.on_talkback(talkback(127, channel=1)) is False
    assert engine.on_talkback(talkback(127, cc=7)) is False
    assert engine.state == STATE_MUTED


def test_talkback_ignores_intermediate_values(engine):
    """It is a switch, not a fader."""
    engine.on_transport(play())
    assert engine.on_talkback(talkback(64)) is False
    assert engine.state == STATE_MUTED


def test_a_note_is_not_a_talkback_message(engine):
    engine.on_transport(play())
    assert engine.on_talkback(play()) is False


# -- the two together -----------------------------------------------------

def test_stop_releases_a_held_talkback(engine):
    """Otherwise the next take opens the microphone because of an old press."""
    engine.on_transport(play())
    engine.on_talkback(talkback(127))
    engine.on_transport(stop())
    assert engine.talkback is False
    engine.on_transport(play())
    assert engine.state == STATE_MUTED and engine.should_mute is True


def test_talkback_held_across_a_stop_and_play_does_not_leak(engine):
    engine.on_transport(play())
    engine.on_talkback(talkback(127))
    engine.on_transport(stop())
    engine.on_transport(play())
    assert engine.should_mute is True


def test_reset_returns_to_idle(engine):
    """Stopping and restarting the listener forgets what it was told."""
    engine.on_transport(play())
    engine.on_talkback(talkback(127))
    engine.reset()
    assert engine.state == STATE_IDLE
    assert engine.seen is False


def test_a_full_take(engine):
    """Play, talk over it twice, stop."""
    seen = []
    for event, feed in [(play(), "t"), (talkback(127), "b"), (talkback(0), "b"),
                        (talkback(127), "b"), (talkback(0), "b"), (stop(), "t")]:
        (engine.on_transport if feed == "t" else engine.on_talkback)(event)
        seen.append(engine.state)
    assert seen == [STATE_MUTED, STATE_TALKBACK, STATE_MUTED,
                    STATE_TALKBACK, STATE_MUTED, STATE_OPEN]


# -- configurable rules ---------------------------------------------------

def test_rules_can_be_retargeted():
    engine = MuteEngine(MuteRules(transport_channel=5, play_note=60,
                                  stop_note=61, transport_velocity=100,
                                  talkback_channel=2, talkback_cc=64))
    assert engine.on_transport(MidiEvent("noteon", 5, 60, 100, SRC)) is True
    assert engine.state == STATE_MUTED
    assert engine.on_talkback(MidiEvent("cc", 2, 64, 127, SRC)) is True
    assert engine.state == STATE_TALKBACK


def test_describe_covers_every_state(engine):
    assert "Waiting" in engine.describe()
    engine.on_transport(stop())
    assert "live" in engine.describe()
    engine.on_transport(play())
    assert "muted" in engine.describe()
    engine.on_talkback(talkback(127))
    assert "Talkback" in engine.describe()
