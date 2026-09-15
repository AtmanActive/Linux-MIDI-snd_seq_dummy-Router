import pytest

from lmssdr.core.alsaseq import Addr, AlsaSeqError, Port, TYPE_MIDI_GENERIC
from lmssdr.core.routing import (ApplyReport, Link, Routing, apply, is_legal,
                                live_links, set_link)


class FakeSeq:
    """A sequencer with a known set of dummy ports and subscriptions.

    Lets the apply logic be tested exactly -- including that it leaves other
    applications' links alone -- without a kernel module or a soundcard.
    """

    def __init__(self, port_numbers=range(4), links=(), foreign=()):
        self._ports = {
            n: Port(addr=Addr(14, n), name=f"Midi Through Port-{n}",
                    caps=0x63, type=TYPE_MIDI_GENERIC, client_name="Midi Through")
            for n in port_numbers
        }
        # (sender, dest) address pairs, as the real connections() returns.
        self._subs = {(Addr(14, s), Addr(14, d)) for s, d in links}
        self._subs |= set(foreign)
        self.refused = set()

    def dummy_ports(self):
        return dict(self._ports)

    def connections(self):
        return sorted(self._subs)

    def connect(self, sender, dest):
        if (sender, dest) in self.refused:
            raise AlsaSeqError("refused")
        self._subs.add((sender, dest))

    def disconnect(self, sender, dest):
        self._subs.discard((sender, dest))


# -- the model -----------------------------------------------------------


def test_self_routing_is_rejected():
    """A port subscribed to itself would feed its own output back in."""
    assert not is_legal(3, 3)
    assert is_legal(3, 4)
    r = Routing()
    assert r.add(3, 3) is False
    assert len(r) == 0


def test_add_remove_toggle():
    r = Routing()
    assert r.add(1, 2) is True
    assert r.add(1, 2) is False          # already there
    assert r.has(1, 2)
    assert r.toggle(1, 2) is False       # now removed
    assert not r.has(1, 2)
    assert r.toggle(1, 2) is True        # and back


def test_direction_matters():
    r = Routing()
    r.add(1, 2)
    assert r.has(1, 2)
    assert not r.has(2, 1)


def test_queries():
    r = Routing([Link(1, 5), Link(1, 6), Link(2, 5)])
    assert r.destinations(1) == [5, 6]
    assert r.sources(5) == [1, 2]
    assert r.destinations(9) == []


def test_drop_port_forgets_both_directions():
    r = Routing([Link(1, 5), Link(5, 2), Link(3, 4)])
    r.drop_port(5)
    assert r.links() == [Link(3, 4)]


def test_round_trip():
    r = Routing()
    r.add(1, 11)
    r.add(2, 12)
    r.save()
    assert Routing.load().links() == [Link(1, 11), Link(2, 12)]


def test_corrupt_and_junk_entries_are_skipped():
    path = Routing.path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"links": [{"from": 1, "to": 2}, {"from": "x"}, 5, '
                    '{"from": 3, "to": 3}]}')
    assert Routing.load().links() == [Link(1, 2)]


# -- applying ------------------------------------------------------------


def test_live_links_sees_only_dummy_to_dummy():
    seq = FakeSeq(links=[(0, 1)],
                  foreign=[(Addr(14, 2), Addr(128, 0)),   # dummy -> browser
                           (Addr(128, 0), Addr(14, 3))])  # browser -> dummy
    assert live_links(seq) == {Link(0, 1)}


def test_apply_adds_what_is_missing():
    seq = FakeSeq()
    report = apply(seq, Routing([Link(0, 1), Link(2, 3)]))
    assert sorted(report.added) == [Link(0, 1), Link(2, 3)]
    assert live_links(seq) == {Link(0, 1), Link(2, 3)}


def test_apply_is_idempotent():
    seq = FakeSeq(links=[(0, 1)])
    report = apply(seq, Routing([Link(0, 1)]))
    assert report.added == []
    assert report.changed is False


def test_apply_skips_ports_that_do_not_exist():
    """Lowering the port count must not discard the saved route."""
    seq = FakeSeq(port_numbers=range(2))
    routing = Routing([Link(0, 1), Link(0, 9)])
    report = apply(seq, routing)
    assert report.added == [Link(0, 1)]
    assert report.skipped == [Link(0, 9)]
    assert Link(0, 9) in routing        # still remembered


def test_apply_does_not_remove_by_default():
    """A route made by hand with aconnect survives an ordinary start."""
    seq = FakeSeq(links=[(2, 3)])
    report = apply(seq, Routing([Link(0, 1)]))
    assert report.removed == []
    assert live_links(seq) == {Link(0, 1), Link(2, 3)}


def test_apply_removes_extras_when_asked():
    seq = FakeSeq(links=[(2, 3)])
    report = apply(seq, Routing([Link(0, 1)]), remove_extra=True)
    assert report.removed == [Link(2, 3)]
    assert live_links(seq) == {Link(0, 1)}


def test_sync_never_touches_other_applications_links():
    """The critical one: a browser's subscription must survive a full sync."""
    browser = (Addr(14, 2), Addr(128, 0))
    seq = FakeSeq(links=[(2, 3)], foreign=[browser])
    apply(seq, Routing(), remove_extra=True)
    assert browser in seq.connections()
    assert live_links(seq) == set()


def test_apply_records_failures_without_stopping():
    seq = FakeSeq()
    seq.refused.add((Addr(14, 0), Addr(14, 1)))
    report = apply(seq, Routing([Link(0, 1), Link(2, 3)]))
    assert report.added == [Link(2, 3)]
    assert len(report.failed) == 1


def test_report_summary_reads_sensibly():
    assert ApplyReport().summary() == "Routing already matched"
    assert "2 connected" in ApplyReport(added=[Link(0, 1), Link(1, 2)]).summary()


def test_set_link_reports_a_missing_port_by_name():
    seq = FakeSeq(port_numbers=range(2))
    with pytest.raises(AlsaSeqError, match="Port-7"):
        set_link(seq, 0, 7, True)


def test_set_link_round_trip():
    seq = FakeSeq()
    set_link(seq, 0, 1, True)
    assert live_links(seq) == {Link(0, 1)}
    set_link(seq, 0, 1, False)
    assert live_links(seq) == set()


def test_legacy_routing_file_is_renamed_on_load():
    from lmssdr.core.paths import config_dir
    legacy = config_dir() / "lmsdr.routing.json"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text('{"links": [{"from": 1, "to": 2}]}')

    assert Routing.load().links() == [Link(1, 2)]
    assert Routing.path().exists()
    assert not legacy.exists()


# -- the pull direction --------------------------------------------------

def test_adopt_records_live_links():
    from lmssdr.core.routing import adopt
    r = Routing([Link(0, 1)])
    added = adopt(r, {Link(0, 1), Link(2, 3)})
    assert added == [Link(2, 3)]            # only what was missing
    assert set(r.links()) == {Link(0, 1), Link(2, 3)}


def test_adopt_is_idempotent():
    from lmssdr.core.routing import adopt
    r = Routing()
    adopt(r, {Link(0, 1)})
    assert adopt(r, {Link(0, 1)}) == []


def test_adopt_keeps_saved_routes_that_are_not_live():
    """A route not applied yet is not evidence the user stopped wanting it."""
    from lmssdr.core.routing import adopt
    r = Routing([Link(4, 5)])
    adopt(r, {Link(0, 1)})
    assert Link(4, 5) in r


def test_forget_inactive_drops_only_unconnected_routes():
    from lmssdr.core.routing import forget_inactive
    r = Routing([Link(0, 1), Link(2, 3)])
    removed = forget_inactive(r, {Link(0, 1)}, present=[0, 1, 2, 3])
    assert removed == [Link(2, 3)]
    assert r.links() == [Link(0, 1)]


def test_forget_inactive_spares_routes_whose_ports_are_absent():
    """Lowering the port count must not delete the setup above it."""
    from lmssdr.core.routing import forget_inactive
    r = Routing([Link(0, 1), Link(20, 21)])
    removed = forget_inactive(r, set(), present=[0, 1])
    assert removed == [Link(0, 1)]
    assert Link(20, 21) in r


def test_forget_inactive_spares_a_half_present_route():
    from lmssdr.core.routing import forget_inactive
    r = Routing([Link(1, 30)])
    assert forget_inactive(r, set(), present=[1, 2]) == []
    assert Link(1, 30) in r


# -- exporting found routes ----------------------------------------------

def test_export_writes_numbers_and_names(tmp_path):
    from lmssdr.core.routing import export_links
    out = tmp_path / "found.json"
    names = {1: "Transport", 11: "Browser Return"}
    count = export_links(out, [Link(1, 11)], name_for=lambda n: names.get(n, str(n)))
    assert count == 1

    import json
    payload = json.loads(out.read_text())
    assert payload["links"] == [{"from": 1, "to": 11,
                                 "fromName": "Transport",
                                 "toName": "Browser Return"}]
    assert "exported" in payload and payload["note"]


def test_export_is_loadable_as_a_routing_file(tmp_path, monkeypatch):
    """The file must be usable, not just readable: copying it over
    lmssdr.routing.json has to restore exactly those routes."""
    from lmssdr.core.routing import export_links
    export_links(Routing.path(), [Link(2, 3), Link(4, 5)],
                 name_for=lambda n: f"Port {n}")
    assert Routing.load().links() == [Link(2, 3), Link(4, 5)]


def test_export_without_names_still_works(tmp_path):
    from lmssdr.core.routing import export_links
    out = tmp_path / "bare.json"
    export_links(out, [Link(0, 1)])
    import json
    assert json.loads(out.read_text())["links"] == [{"from": 0, "to": 1}]


def test_export_is_atomic(tmp_path):
    from lmssdr.core.routing import export_links
    out = tmp_path / "x.json"
    export_links(out, [Link(0, 1)])
    assert out.exists()
    assert not list(tmp_path.glob("*.tmp"))


# -- ordering ------------------------------------------------------------

def test_links_keep_creation_order_not_numeric_order():
    r = Routing()
    r.add(20, 7)
    r.add(0, 1)
    r.add(9, 30)
    assert r.links() == [Link(20, 7), Link(0, 1), Link(9, 30)]


def test_order_survives_a_save_and_load():
    r = Routing()
    for pair in [(20, 7), (0, 1), (9, 30)]:
        r.add(*pair)
    r.save()
    assert Routing.load().links() == [Link(20, 7), Link(0, 1), Link(9, 30)]


def test_replace_keeps_the_position():
    """Editing one end of a route must not move its row."""
    r = Routing([Link(1, 2), Link(3, 4), Link(5, 6)])
    assert r.replace(3, 4, 3, 9) is True
    assert r.links() == [Link(1, 2), Link(3, 9), Link(5, 6)]


def test_replace_refuses_a_duplicate_or_a_self_route():
    r = Routing([Link(1, 2), Link(3, 4)])
    assert r.replace(3, 4, 1, 2) is False       # already exists
    assert r.replace(3, 4, 7, 7) is False       # self-route
    assert r.links() == [Link(1, 2), Link(3, 4)]


def test_replace_of_an_unknown_route_does_nothing():
    r = Routing([Link(1, 2)])
    assert r.replace(8, 9, 1, 3) is False
    assert r.links() == [Link(1, 2)]


def test_adding_a_duplicate_does_not_reorder():
    r = Routing([Link(1, 2), Link(3, 4)])
    r.add(1, 2)
    assert r.links() == [Link(1, 2), Link(3, 4)]


# -- swapping two ports ---------------------------------------------------

def test_swap_follows_routes_to_the_other_port():
    r = Routing([Link(1, 5), Link(9, 1), Link(3, 4)])
    r.swap_ports(1, 7)
    assert r.links() == [Link(7, 5), Link(9, 7), Link(3, 4)]


def test_swap_reverses_a_route_between_the_pair():
    r = Routing([Link(1, 2)])
    r.swap_ports(1, 2)
    assert r.links() == [Link(2, 1)]


def test_swap_exchanges_both_sides():
    r = Routing([Link(1, 9), Link(2, 9)])
    r.swap_ports(1, 2)
    assert r.links() == [Link(2, 9), Link(1, 9)]


def test_swap_keeps_positions():
    """The list must not reshuffle: a swap is not a reordering."""
    r = Routing([Link(0, 1), Link(5, 6), Link(2, 3)])
    r.swap_ports(5, 8)
    assert r.links() == [Link(0, 1), Link(8, 6), Link(2, 3)]


def test_swap_reports_what_changed():
    r = Routing([Link(1, 5), Link(3, 4)])
    changed = r.swap_ports(1, 7)
    assert changed == [Link(7, 5)]


def test_swapping_a_port_with_itself_does_nothing():
    r = Routing([Link(1, 5)])
    assert r.swap_ports(3, 3) == []
    assert r.links() == [Link(1, 5)]


def test_swap_never_creates_a_self_route_or_a_duplicate():
    r = Routing([Link(1, 2), Link(2, 1), Link(1, 5), Link(2, 5)])
    r.swap_ports(1, 2)
    links = r.links()
    assert all(l.source != l.dest for l in links)
    assert len(set(links)) == len(links)


# -- sorting --------------------------------------------------------------

def pairs(routing):
    return [(l.source, l.dest) for l in routing.links()]


def build(*routes):
    r = Routing()
    for source, dest in routes:
        r.add(source, dest)
    return r


def test_sort_by_source():
    r = build((5, 2), (1, 9), (3, 0))
    assert r.sort(by_source=True) is True
    assert pairs(r) == [(1, 9), (3, 0), (5, 2)]


def test_sort_by_destination():
    r = build((5, 2), (1, 9), (3, 0))
    assert r.sort(by_source=False) is True
    assert pairs(r) == [(3, 0), (5, 2), (1, 9)]


def test_equal_sources_break_the_tie_on_the_destination():
    """The spec's example, with a legal pair: 11->10 before 11->12.

    (11->11 cannot exist -- a port routing to itself would echo its own
    output into its input, and is_legal refuses it.)
    """
    r = build((11, 12), (11, 10), (11, 2))
    r.sort(by_source=True)
    assert pairs(r) == [(11, 2), (11, 10), (11, 12)]


def test_equal_destinations_break_the_tie_on_the_source():
    """The other example: 10->11 before 12->11."""
    r = build((12, 11), (10, 11), (2, 11))
    r.sort(by_source=False)
    assert pairs(r) == [(2, 11), (10, 11), (12, 11)]


def test_sorting_is_by_number_not_by_text():
    """9 must not land after 10, which is what string keys would do."""
    r = build((10, 0), (9, 0), (2, 0))
    r.sort(by_source=True)
    assert pairs(r) == [(2, 0), (9, 0), (10, 0)]


def test_sort_reports_when_nothing_moved():
    r = build((3, 4), (1, 2))
    assert r.sort(by_source=True) is True
    assert r.sort(by_source=True) is False      # already in that order


def test_sorting_an_empty_or_single_route_list_is_a_no_op():
    assert Routing().sort() is False
    assert build((4, 5)).sort() is False


def test_sorting_keeps_every_route():
    routes = [(5, 2), (1, 9), (3, 0), (9, 1)]
    r = build(*routes)
    r.sort(by_source=False)
    assert sorted(pairs(r)) == sorted(routes)
    assert len(r) == len(routes)


def test_the_two_orders_differ():
    r1 = build((5, 1), (2, 9))
    r2 = build((5, 1), (2, 9))
    r1.sort(by_source=True)
    r2.sort(by_source=False)
    assert pairs(r1) == [(2, 9), (5, 1)]
    assert pairs(r2) == [(5, 1), (2, 9)]


def test_a_sorted_order_survives_a_save_and_load():
    r = build((5, 2), (1, 9), (3, 0))
    r.sort(by_source=True)
    r.save()
    assert pairs(Routing.load()) == [(1, 9), (3, 0), (5, 2)]
