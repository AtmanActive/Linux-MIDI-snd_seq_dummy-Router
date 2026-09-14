"""Pure-logic tests for the ALSA binding. Nothing here opens the sequencer."""

from lmssdr.core import alsaseq
from lmssdr.core.alsaseq import Addr, Client, Port, dummy_port_number


def test_addr_text():
    assert str(Addr(14, 7)) == "14:7"
    assert Addr.parse("14:7") == Addr(14, 7)


def test_addr_is_hashable_and_ordered():
    assert sorted({Addr(14, 2), Addr(14, 1), Addr(0, 9)}) == [
        Addr(0, 9), Addr(14, 1), Addr(14, 2)]


def test_dummy_port_number():
    assert dummy_port_number("Midi Through Port-0") == 0
    assert dummy_port_number("Midi Through Port-19") == 19
    # Duplex halves are deliberately not recognised: this app never loads the
    # module in duplex mode, and treating :A as port N would be wrong.
    assert dummy_port_number("Midi Through Port-1:A") is None
    assert dummy_port_number("mio2 DIN 1") is None
    assert dummy_port_number("") is None


def _port(caps, type_=alsaseq.TYPE_MIDI_GENERIC):
    return Port(addr=Addr(14, 0), name="Midi Through Port-0",
                caps=caps, type=type_, client_name="Midi Through")


def test_routability_requires_the_subscription_bits():
    full = alsaseq.CAP_READ | alsaseq.CAP_WRITE | alsaseq.CAP_SUBS_READ | alsaseq.CAP_SUBS_WRITE
    assert _port(full).readable and _port(full).writable
    # PipeWire's internal ports have READ|WRITE but no SUBS bits, so nothing
    # may subscribe to them and they are not routable.
    bare = alsaseq.CAP_READ | alsaseq.CAP_WRITE
    assert not _port(bare).readable and not _port(bare).writable


def test_is_midi():
    assert _port(0).is_midi
    assert not _port(0, type_=alsaseq.TYPE_APPLICATION).is_midi


def test_client_kind():
    assert Client(14, "Midi Through", alsaseq.KERNEL_CLIENT).is_kernel
    assert not Client(128, "Bome", alsaseq.USER_CLIENT).is_kernel
