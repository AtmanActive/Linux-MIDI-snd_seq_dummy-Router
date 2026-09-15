"""The bridge's routing presentation logic.

Runs against a real Bridge but never opens the sequencer: the point is the
translation from model state into what QML renders, which is where an
off-by-one or a reversed direction would actually show up.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from lmssdr.core.routing import Link, Routing            # noqa: E402
from lmssdr.core.settings import Settings                # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def bridge(qapp):
    from lmssdr.ui.bridge import Bridge
    b = Bridge(Settings.load())
    # Stand in for the sequencer rather than opening one.
    b._live_ports = [0, 1, 2, 3]
    b._live_links = set()
    b._routing = Routing()
    return b


def test_matrix_is_square_and_empty_by_default(bridge):
    m = bridge.matrix
    assert len(m) == 4
    assert all(len(row) == 4 for row in m)
    assert all(cell == 0 for row in m for cell in row)


def test_matrix_marks_saved_but_not_live(bridge):
    bridge._routing.add(1, 2)
    assert bridge.matrix[1][2] == 1


def test_matrix_marks_live_but_not_saved(bridge):
    bridge._live_links = {Link(1, 2)}
    assert bridge.matrix[1][2] == 2


def test_matrix_marks_saved_and_live(bridge):
    bridge._routing.add(1, 2)
    bridge._live_links = {Link(1, 2)}
    assert bridge.matrix[1][2] == 3


def test_matrix_rows_are_sources_not_destinations(bridge):
    """The one mistake that would silently reverse every route.

    Masked to the connection bits: the mirror cell also carries bit 2, which
    marks that its reverse is routed, and that is not a connection.
    """
    bridge._routing.add(0, 3)
    assert bridge.matrix[0][3] & 3 == 1
    assert bridge.matrix[3][0] & 3 == 0


def test_matrix_indexes_by_position_not_port_number(bridge):
    """With a sparse port list, row 0 is the first port, not port 0."""
    bridge._live_ports = [5, 9]
    bridge._routing.add(5, 9)
    m = bridge.matrix
    assert len(m) == 2
    assert m[0][1] & 3 == 1
    assert m[1][0] & 3 == 0


def test_links_merges_saved_and_live(bridge):
    bridge._routing.add(0, 1)
    bridge._live_links = {Link(2, 3)}
    links = {(l["from"], l["to"]): l for l in bridge.links}
    assert links[(0, 1)]["saved"] and not links[(0, 1)]["live"]
    assert links[(2, 3)]["live"] and not links[(2, 3)]["saved"]


def test_unmanaged_count_counts_only_unsaved_live_links(bridge):
    bridge._routing.add(0, 1)
    bridge._live_links = {Link(0, 1), Link(2, 3)}
    assert bridge.savedLinkCount == 1
    assert bridge.unmanagedLinkCount == 1


def test_routable_ports_use_custom_names(bridge):
    bridge._names.set_name(2, "Talkback")
    ports = {p["number"]: p for p in bridge.routablePorts}
    assert ports[2]["displayName"] == "Talkback"
    assert ports[2]["kernelName"] == "Midi Through Port-2"
    # Unnamed ports fall back so the column is never blank.
    assert ports[3]["displayName"] == "Midi Through Port-3"


def test_toggling_a_port_onto_itself_is_refused(bridge):
    errors = []
    bridge.errorRaised.connect(errors.append)
    bridge._seq = None
    bridge.toggleLink(2, 2)
    assert len(errors) == 1
    assert "itself" in errors[0]
    assert bridge.savedLinkCount == 0


# -- filtering -----------------------------------------------------------

@pytest.fixture
def named_bridge(bridge):
    bridge._live_ports = [0, 1, 2, 3, 4, 5]
    bridge._names.set_name(1, "Drums Send")
    bridge._names.set_name(2, "Keys Send")
    bridge._names.set_name(4, "Drums Return")
    bridge._names.set_remark(5, "spare for drums overflow")
    return bridge


def test_filters_narrow_each_axis_independently(named_bridge):
    named_bridge.setFilterFrom("drums")
    assert [p["number"] for p in named_bridge.sourcePorts] == [1, 4, 5]
    # The other axis is untouched, so cross-group routing stays possible.
    assert [p["number"] for p in named_bridge.destPorts] == [0, 1, 2, 3, 4, 5]

    named_bridge.setFilterTo("keys")
    assert [p["number"] for p in named_bridge.destPorts] == [2]


def test_matrix_shape_follows_the_filters(named_bridge):
    named_bridge.setFilterFrom("drums")     # 1, 4, 5
    named_bridge.setFilterTo("keys")        # 2
    m = named_bridge.matrix
    assert len(m) == 3
    assert all(len(row) == 1 for row in m)


def test_filtered_matrix_still_addresses_the_right_ports(named_bridge):
    """The bug that would silently route the wrong pair.

    With rows [1, 4, 5] and columns [2], cell [1][0] must mean 4 -> 2.
    """
    named_bridge._routing.add(4, 2)
    named_bridge.setFilterFrom("drums")
    named_bridge.setFilterTo("keys")
    m = named_bridge.matrix
    assert m[1][0] == 1
    assert m[0][0] == 0 and m[2][0] == 0


def test_remark_only_match_is_included(named_bridge):
    """Port 5 has no name, only a remark mentioning drums."""
    named_bridge.setFilterFrom("drums")
    assert 5 in [p["number"] for p in named_bridge.sourcePorts]


def test_graph_shows_every_live_port_when_unfiltered(named_bridge):
    """A picture of the whole machine, where an unrouted port looks it."""
    assert [p["number"] for p in named_bridge.graphPorts] == [0, 1, 2, 3, 4, 5]


def test_graph_narrows_to_the_ports_the_surviving_routes_touch(named_bridge):
    named_bridge._routing.add(2, 1)         # Keys Send -> Drums Send
    named_bridge._routing.add(0, 3)         # neither end matches
    named_bridge.setFilterFrom("keys")      # 2
    named_bridge.setFilterTo("drums")       # 1, 4, 5
    assert [p["number"] for p in named_bridge.graphPorts] == [1, 2]


def test_every_drawn_edge_has_both_of_its_nodes(named_bridge):
    """An edge referencing a missing node would silently not be drawn."""
    for pair in [(2, 1), (1, 4), (0, 3), (5, 2)]:
        named_bridge._routing.add(*pair)
    named_bridge.setFilterTo("drums")
    nodes = {p["number"] for p in named_bridge.graphPorts}
    for link in named_bridge.links:
        assert link["from"] in nodes and link["to"] in nodes


def test_a_filter_matching_ports_with_no_routes_empties_the_graph(named_bridge):
    named_bridge._routing.add(0, 3)
    named_bridge.setFilterFrom("drums")     # 1, 4, 5 -- none of them route
    assert named_bridge.graphPorts == []
    assert named_bridge.links == []


def test_filters_active_flag(named_bridge):
    assert named_bridge.filtersActive is False
    named_bridge.setFilterFrom("   ")
    assert named_bridge.filtersActive is False    # whitespace is not a filter
    named_bridge.setFilterFrom("drums")
    assert named_bridge.filtersActive is True


def test_no_match_gives_an_empty_axis_not_an_error(named_bridge):
    named_bridge.setFilterFrom("nothing matches this")
    assert named_bridge.sourcePorts == []
    assert named_bridge.matrix == []


def test_ports_page_filter(named_bridge):
    total = named_bridge.totalPortRowCount
    named_bridge.setPortsFilter("drums")
    numbers = [row["number"] for row in named_bridge.ports]
    assert numbers == [1, 4, 5]
    assert named_bridge.totalPortRowCount == total    # unfiltered total
    named_bridge.setPortsFilter("")
    assert len(named_bridge.ports) == total


def test_filters_are_not_persisted(named_bridge):
    """Reopening to a hidden half of your ports would be a bad surprise."""
    named_bridge.setFilterFrom("drums")
    named_bridge._settings.save()
    from lmssdr.core.settings import Settings
    assert not hasattr(Settings.load(), "filter_from")


# -- sync from kernel ----------------------------------------------------

def test_sync_from_kernel_saves_unmanaged_links(bridge):
    bridge._live_links = {Link(0, 1), Link(2, 3)}
    bridge.syncFromKernel(False)
    assert bridge.savedLinkCount == 2
    assert bridge.unmanagedLinkCount == 0


def test_sync_from_kernel_keeps_inactive_routes_by_default(bridge):
    bridge._routing.add(2, 3)                 # saved, not connected
    bridge._live_links = {Link(0, 1)}
    bridge.syncFromKernel(False)
    assert bridge.savedLinkCount == 2


def test_sync_from_kernel_can_forget_inactive_routes(bridge):
    bridge._routing.add(2, 3)
    bridge._live_links = {Link(0, 1)}
    bridge.syncFromKernel(True)
    assert [(l.source, l.dest) for l in bridge._routing.links()] == [(0, 1)]


def test_inactive_saved_count_ignores_absent_ports(bridge):
    bridge._live_ports = [0, 1]
    bridge._routing.add(0, 1)                 # present, not connected
    bridge._routing.add(20, 21)               # ports absent entirely
    bridge._live_links = set()
    assert bridge.inactiveSavedCount == 1


def test_sync_from_kernel_reports_when_nothing_changed(bridge):
    notices = []
    bridge.noticeRaised.connect(notices.append)
    bridge.syncFromKernel(False)
    assert "already matched" in notices[-1]


# -- apply is authoritative ----------------------------------------------

class RecordingSeq:
    """Captures what apply asked the sequencer to do."""

    def __init__(self, live):
        from lmssdr.core.alsaseq import Port, TYPE_MIDI_GENERIC, Addr
        self._ports = {n: Port(addr=Addr(14, n), name=f"Midi Through Port-{n}",
                               caps=0x63, type=TYPE_MIDI_GENERIC,
                               client_name="Midi Through")
                       for n in range(16)}
        from lmssdr.core.alsaseq import Addr as A
        self._subs = {(A(14, s), A(14, d)) for s, d in live}
        self.disconnected = []

    def dummy_ports(self):
        return dict(self._ports)

    def connections(self):
        return sorted(self._subs)

    def connect(self, sender, dest):
        self._subs.add((sender, dest))

    def disconnect(self, sender, dest):
        self.disconnected.append((sender.port, dest.port))
        self._subs.discard((sender, dest))


def test_apply_removes_connections_not_in_the_saved_routing(bridge):
    """Apply is authoritative: a merge would let phantom routes persist."""
    bridge._seq = RecordingSeq(live=[(4, 5)])
    bridge._routing.add(0, 1)
    bridge.applySavedRouting()
    assert bridge._seq.disconnected == [(4, 5)]


def test_apply_keeps_what_is_saved(bridge):
    bridge._seq = RecordingSeq(live=[(0, 1), (4, 5)])
    bridge._routing.add(0, 1)
    bridge.applySavedRouting()
    assert bridge._seq.disconnected == [(4, 5)]


def test_clearing_the_routing_disconnects_everything(bridge):
    bridge._seq = RecordingSeq(live=[(0, 1), (2, 3)])
    bridge._routing.add(0, 1)
    bridge._routing.add(2, 3)
    bridge.clearRouting()
    assert sorted(bridge._seq.disconnected) == [(0, 1), (2, 3)]
    assert bridge.savedLinkCount == 0


# -- start-up restore ----------------------------------------------------

def test_startup_restore_is_authoritative(bridge):
    """A stale connection must not survive restart after restart."""
    bridge._seq = RecordingSeq(live=[(4, 5)])
    bridge._routing.add(0, 1)
    bridge._restore_routing()
    assert bridge._seq.disconnected == [(4, 5)]


def test_startup_restore_says_out_loud_what_it_removed(bridge):
    notices = []
    bridge.noticeRaised.connect(notices.append)
    bridge._seq = RecordingSeq(live=[(4, 5)])
    bridge._routing.add(0, 1)
    bridge._restore_routing()
    assert "1 connection" in notices[-1] and "removed" in notices[-1]


def test_startup_restore_is_silent_when_nothing_was_removed(bridge):
    notices = []
    bridge.noticeRaised.connect(notices.append)
    bridge._seq = RecordingSeq(live=[(0, 1)])
    bridge._routing.add(0, 1)
    bridge._restore_routing()
    assert notices == []


def test_empty_routing_does_not_wipe_the_sequencer_at_startup(bridge):
    """First run must not destroy a setup built with aconnect beforehand."""
    bridge._seq = RecordingSeq(live=[(4, 5)])
    bridge._restore_routing()
    assert bridge._seq.disconnected == []


def test_apply_with_empty_routing_still_sweeps(bridge):
    """The button is an explicit act, so it does sweep."""
    bridge._seq = RecordingSeq(live=[(4, 5)])
    bridge.applySavedRouting()
    assert bridge._seq.disconnected == [(4, 5)]


# -- routes found at start-up --------------------------------------------

def test_found_routes_are_announced_when_nothing_is_saved(bridge):
    seen = []
    bridge.foundRoutesOnStart.connect(seen.append)
    bridge._live_links = {Link(4, 5), Link(6, 7)}
    bridge._offer_to_record_found_routes()
    assert seen == [2]


def test_no_announcement_once_anything_is_saved(bridge):
    """After that point start-up is authoritative and the moment has passed."""
    seen = []
    bridge.foundRoutesOnStart.connect(seen.append)
    bridge._routing.add(0, 1)
    bridge._live_links = {Link(4, 5)}
    bridge._offer_to_record_found_routes()
    assert seen == []


def test_no_announcement_when_there_is_nothing_to_report(bridge):
    seen = []
    bridge.foundRoutesOnStart.connect(seen.append)
    bridge._live_links = set()
    bridge._offer_to_record_found_routes()
    assert seen == []


def test_do_not_ask_again_is_honoured(bridge):
    bridge.dismissFoundRoutes(True)
    seen = []
    bridge.foundRoutesOnStart.connect(seen.append)
    bridge._live_links = {Link(4, 5)}
    bridge._offer_to_record_found_routes()
    assert seen == []
    from lmssdr.core.settings import Settings
    assert Settings.load().warn_about_found_routes is False


def test_dismiss_without_the_box_ticked_keeps_asking(bridge):
    bridge.dismissFoundRoutes(False)
    from lmssdr.core.settings import Settings
    assert Settings.load().warn_about_found_routes is not False


def test_export_accepts_a_file_url(bridge, tmp_path):
    bridge._live_links = {Link(1, 2)}
    target = tmp_path / "out.json"
    assert bridge.exportFoundRoutes(f"file://{target}") is True
    assert target.exists()


def test_export_reports_a_write_failure(bridge):
    errors = []
    bridge.errorRaised.connect(errors.append)
    bridge._live_links = {Link(1, 2)}
    assert bridge.exportFoundRoutes("/proc/nope/out.json") is False
    assert errors and "Could not write" in errors[0]


def test_suggested_name_is_dated_and_json(bridge):
    name = bridge.suggestedExportName
    assert name.startswith("lmssdr.found-routes.") and name.endswith(".json")


# -- two-way pair warning ------------------------------------------------

def test_would_create_loop_when_the_reverse_is_saved(bridge):
    bridge._routing.add(2, 3)
    assert bridge.wouldCreateLoop(3, 2) is True


def test_would_create_loop_when_the_reverse_is_only_live(bridge):
    """A connection made outside the app still makes a loop."""
    bridge._live_links = {Link(2, 3)}
    assert bridge.wouldCreateLoop(3, 2) is True


def test_no_warning_without_a_reverse(bridge):
    bridge._routing.add(2, 3)
    assert bridge.wouldCreateLoop(0, 1) is False


def test_no_warning_when_turning_a_link_off(bridge):
    """Clicking a connected cell disconnects it; that cannot make a loop."""
    bridge._routing.add(2, 3)
    bridge._routing.add(3, 2)
    assert bridge.wouldCreateLoop(3, 2) is False


def test_matrix_marks_both_halves_of_a_loop(bridge):
    bridge._routing.add(1, 2)
    bridge._routing.add(2, 1)
    assert bridge.matrix[1][2] & 4      # reverse exists
    assert bridge.matrix[2][1] & 4


def test_matrix_marks_the_mirror_of_a_one_way_route(bridge):
    """The empty mirror cell is flagged too: clicking it is what makes the loop."""
    bridge._routing.add(1, 2)
    assert bridge.matrix[2][1] & 4
    assert bridge.matrix[2][1] & 3 == 0     # but it is not itself connected


def test_loop_warning_does_not_block_the_connection(bridge):
    """Reported, not refused."""
    bridge._seq = None
    bridge._routing.add(2, 3)
    bridge.toggleLink(3, 2)
    assert bridge._routing.has(3, 2)


# -- notification wiring -------------------------------------------------

class PortsOnlySeq:
    """A sequencer with ports and no connections."""

    def __init__(self, numbers):
        from lmssdr.core.alsaseq import Addr, Port, TYPE_MIDI_GENERIC
        self._ports = {n: Port(addr=Addr(14, n), name=f"Midi Through Port-{n}",
                               caps=0x63, type=TYPE_MIDI_GENERIC,
                               client_name="Midi Through")
                       for n in numbers}

    def dummy_ports(self):
        return dict(self._ports)

    def connections(self):
        return []


def test_ports_appearing_notifies_the_routing_views(bridge):
    """Regression: the matrix showed "no ports to route" with 32 ports live.

    sourcePorts, destPorts and totalRoutablePortCount are notified by
    routingChanged, so a change to the port list has to emit it. Without
    this the matrix keeps the empty list it was constructed with, and the
    only reason it ever looked right was a saved route emitting the signal
    on the way past.
    """
    bridge._live_ports = []
    bridge._seq = PortsOnlySeq(range(4))
    fired = []
    bridge.routingChanged.connect(lambda: fired.append(True))

    bridge.refresh()

    assert bridge.totalRoutablePortCount == 4
    assert fired, "routingChanged was not emitted when the ports appeared"


def test_no_saved_routes_still_populates_the_matrix(bridge):
    """The exact failing case: nothing saved, so nothing else emits."""
    bridge._live_ports = []
    bridge._seq = PortsOnlySeq(range(3))
    assert len(bridge._routing) == 0
    bridge.refresh()
    assert len(bridge.sourcePorts) == 3
    assert len(bridge.destPorts) == 3
    assert len(bridge.matrix) == 3


# -- window size ---------------------------------------------------------

def test_saving_the_window_size_persists_it(bridge):
    from lmssdr.core.settings import Settings
    bridge.saveWindowSize(1366, 968)
    assert (Settings.load().window_width, Settings.load().window_height) == (1366, 968)


def test_a_collapsed_window_is_not_saved(bridge):
    """Minimising or a transient zero-size must not become the new default."""
    from lmssdr.core.settings import Settings
    bridge.saveWindowSize(1366, 968)
    bridge.saveWindowSize(0, 0)
    bridge.saveWindowSize(100, 50)
    assert Settings.load().window_width == 1366


def test_window_size_has_a_floor(bridge):
    bridge._settings.window_width = 10
    bridge._settings.window_height = 10
    assert bridge.windowWidth >= 480 and bridge.windowHeight >= 360


def test_unchanged_size_is_not_rewritten(bridge, tmp_path):
    from lmssdr.core.settings import Settings
    bridge.saveWindowSize(1200, 900)
    before = Settings.path().stat().st_mtime_ns
    bridge.saveWindowSize(1200, 900)
    assert Settings.path().stat().st_mtime_ns == before


# -- list view editing ---------------------------------------------------

def test_route_rows_carry_both_ports_in_full(bridge):
    bridge._names.set_name(2, "Drums Send")
    bridge._names.set_remark(2, "from the kit room")
    bridge._routing.add(2, 3)
    row = bridge.routeRows[0]
    assert row["source"]["number"] == 2
    assert row["source"]["name"] == "Drums Send"
    assert row["source"]["kernelName"] == "Midi Through Port-2"
    assert row["source"]["remark"] == "from the kit room"
    assert row["dest"]["number"] == 3
    assert row["dest"]["displayName"] == "Midi Through Port-3"


def test_route_rows_show_only_assigned_pairs(bridge):
    assert bridge.routeRows == []
    bridge._routing.add(0, 1)
    assert len(bridge.routeRows) == 1


def test_add_route_picks_a_free_pair(bridge):
    bridge._seq = RecordingSeq(live=[])
    assert bridge.addRoute() is True
    assert bridge.savedLinkCount == 1
    first = bridge._routing.links()[0]
    assert first.source != first.dest


def test_add_route_does_not_duplicate(bridge):
    bridge._seq = RecordingSeq(live=[])
    bridge.addRoute()
    bridge.addRoute()
    links = bridge._routing.links()
    assert len(links) == 2 and links[0] != links[1]


def test_add_route_needs_two_ports(bridge):
    errors = []
    bridge.errorRaised.connect(errors.append)
    bridge._live_ports = [0]
    assert bridge.addRoute() is False
    assert "two ports" in errors[0]


def test_remove_route(bridge):
    bridge._seq = RecordingSeq(live=[(0, 1)])
    bridge._routing.add(0, 1)
    bridge.removeRoute(0, 1)
    assert bridge.savedLinkCount == 0
    assert bridge._seq.disconnected == [(0, 1)]


def test_retarget_changes_one_end(bridge):
    bridge._seq = RecordingSeq(live=[(0, 1)])
    bridge._routing.add(0, 1)
    bridge.retargetRoute(0, 1, 0, 2)
    assert [(l.source, l.dest) for l in bridge._routing.links()] == [(0, 2)]
    assert bridge._seq.disconnected == [(0, 1)]


def test_retarget_refuses_a_self_route(bridge):
    errors = []
    bridge.errorRaised.connect(errors.append)
    bridge._seq = RecordingSeq(live=[(0, 1)])
    bridge._routing.add(0, 1)
    bridge.retargetRoute(0, 1, 2, 2)
    assert "itself" in errors[0]
    assert bridge._routing.has(0, 1)          # unchanged


def test_retarget_refuses_a_duplicate(bridge):
    errors = []
    bridge.errorRaised.connect(errors.append)
    bridge._seq = RecordingSeq(live=[])
    bridge._routing.add(0, 1)
    bridge._routing.add(2, 3)
    bridge.retargetRoute(0, 1, 2, 3)
    assert "already routes" in errors[0]
    assert bridge.savedLinkCount == 2


# -- list ordering -------------------------------------------------------

def test_new_route_appears_last(bridge):
    """A new pair belongs at the bottom, where the user just added it."""
    bridge._seq = RecordingSeq(live=[])
    bridge._live_ports = [0, 1, 2, 3]
    bridge._routing.add(2, 3)
    added = []
    bridge.routeAdded.connect(lambda s, d: added.append((s, d)))

    bridge.addRoute()

    rows = bridge.routeRows
    assert (rows[0]["source"]["number"], rows[0]["dest"]["number"]) == (2, 3)
    last = (rows[-1]["source"]["number"], rows[-1]["dest"]["number"])
    assert last == added[0]
    # Numerically it would have sorted first; creation order puts it last.
    assert last == (0, 1)


def test_retargeting_does_not_move_the_row(bridge):
    bridge._seq = RecordingSeq(live=[])
    bridge._routing.add(1, 2)
    bridge._routing.add(3, 4)
    bridge._routing.add(5, 0)
    bridge.retargetRoute(3, 4, 3, 0)
    pairs = [(r["source"]["number"], r["dest"]["number"]) for r in bridge.routeRows]
    assert pairs == [(1, 2), (3, 0), (5, 0)]


def test_unsaved_live_routes_come_after_saved_ones(bridge):
    bridge._routing.add(9, 8)
    bridge._live_links = {Link(9, 8), Link(0, 1)}
    pairs = [(r["source"]["number"], r["dest"]["number"]) for r in bridge.routeRows]
    assert pairs == [(9, 8), (0, 1)]


# -- port colours --------------------------------------------------------

def test_colour_reaches_every_description(bridge):
    bridge._live_ports = [0, 1, 2, 3]
    bridge.setPortColour(2, "Violet")
    assert {p["number"]: p["colourHex"] for p in bridge.routablePorts}[2] == "#9b7ede"
    assert {r["number"]: r["colourHex"] for r in bridge.ports}[2] == "#9b7ede"
    bridge._routing.add(2, 3)
    assert bridge.routeRows[0]["source"]["colourHex"] == "#9b7ede"
    assert bridge.routeRows[0]["dest"]["colourHex"] == ""


def test_setting_a_colour_notifies_the_routing_views(bridge):
    """The tag shows on every screen, so every screen has to hear about it."""
    fired = []
    bridge.routingChanged.connect(lambda: fired.append(True))
    bridge.setPortColour(1, "Lime")
    assert fired


def test_setting_the_same_colour_twice_is_a_no_op(bridge):
    bridge.setPortColour(1, "Lime")
    fired = []
    bridge.routingChanged.connect(lambda: fired.append(True))
    bridge.setPortColour(1, "Lime")
    assert fired == []


def test_palette_is_exposed_to_qml(bridge):
    assert len(bridge.portColourNames) == 15
    assert bridge.portColours["Teal"] == "#21a5b8"


# -- swapping ports ------------------------------------------------------

def test_swap_moves_identity_and_routes_and_applies_them(bridge):
    from lmssdr.core.alsaseq import Addr
    bridge._live_ports = [0, 1, 2, 3, 9]
    bridge._seq = RecordingSeq(live=[(1, 2)])
    bridge._names.set_name(1, "Drums"); bridge._names.set_colour(1, "Red")
    bridge._routing.add(1, 2)

    assert bridge.swapPorts(1, 9) is True

    assert bridge._names.get(9).name == "Drums"
    assert bridge._names.get(9).colour == "Red"
    assert bridge._names.get(1).name == ""
    assert [(l.source, l.dest) for l in bridge._routing.links()] == [(9, 2)]
    # The kernel was moved too, not just the file.
    assert bridge._seq.disconnected == [(1, 2)]
    assert (Addr(14, 9), Addr(14, 2)) in bridge._seq.connections()


def test_swap_persists_both_files(bridge):
    from lmssdr.core.ports import PortNames
    from lmssdr.core.routing import Routing
    bridge._live_ports = [0, 1, 2, 9]
    bridge._seq = RecordingSeq(live=[])
    bridge._names.set_name(1, "Drums")
    bridge._routing.add(1, 2)
    bridge.swapPorts(1, 9)
    assert PortNames.load().get(9).name == "Drums"
    assert Routing.load().links()[0].source == 9


def test_swap_only_touches_the_routes_it_moved(bridge):
    """An unrelated connection must survive; a swap is not an Apply."""
    from lmssdr.core.alsaseq import Addr
    bridge._live_ports = [0, 1, 2, 3, 9]
    bridge._seq = RecordingSeq(live=[(3, 0)])          # not saved, not involved
    bridge._routing.add(1, 2)
    bridge.swapPorts(1, 9)
    # 1->2 became 9->2, so dropping the old wiring is the swap doing its job.
    assert bridge._seq.disconnected == [(1, 2)]
    # The link this app never made is still there.
    assert (Addr(14, 3), Addr(14, 0)) in bridge._seq.connections()


def test_swap_refuses_a_port_that_does_not_exist(bridge):
    errors = []
    bridge.errorRaised.connect(errors.append)
    bridge._live_ports = [0, 1]
    assert bridge.swapPorts(0, 40) is False
    assert "have to exist" in errors[0]


def test_swap_with_itself_is_refused(bridge):
    bridge._live_ports = [0, 1]
    assert bridge.swapPorts(1, 1) is False


def test_swap_reports_how_many_routes_moved(bridge):
    notices = []
    bridge.noticeRaised.connect(notices.append)
    bridge._live_ports = [0, 1, 2, 9]
    bridge._seq = RecordingSeq(live=[])
    bridge._routing.add(1, 2)
    bridge.swapPorts(1, 9)
    assert "1 route" in notices[-1]


# -- the default microphone ----------------------------------------------

def test_default_is_offered_first(bridge, monkeypatch):
    from lmssdr.core import audio
    monkeypatch.setattr(audio, "sources",
                        lambda include_monitors=False: [
                            audio.AudioSource("alsa_input.a", "Mic A", False)])
    monkeypatch.setattr(audio, "default_source", lambda: "alsa_input.a")
    choices = bridge.audioSources
    assert choices[0]["name"] == audio.DEFAULT_SOURCE
    assert "Mic A" in choices[0]["description"]
    assert choices[1]["name"] == "alsa_input.a"


def test_default_is_resolved_when_the_listener_is_configured(bridge, monkeypatch):
    from lmssdr.core import audio
    monkeypatch.setattr(audio, "default_source", lambda: "alsa_input.current")
    bridge._settings.mute_source = audio.DEFAULT_SOURCE
    bridge._configure_mute()
    assert bridge._mute._source == "alsa_input.current"


def test_the_stored_setting_stays_the_sentinel(bridge, monkeypatch):
    """The file records the intent, not the device it happened to resolve to."""
    from lmssdr.core import audio
    from lmssdr.core.settings import Settings
    monkeypatch.setattr(audio, "default_source", lambda: "alsa_input.current")
    bridge.setMuteSource(audio.DEFAULT_SOURCE)
    assert Settings.load().mute_source == audio.DEFAULT_SOURCE
    assert bridge.muteSourceIsDefault is True


def test_a_missing_default_is_reported(bridge, monkeypatch):
    from lmssdr.core import audio
    monkeypatch.setattr(audio, "default_source", lambda: "")
    bridge._settings.mute_source = audio.DEFAULT_SOURCE
    bridge._configure_mute()
    assert "default input" in bridge.muteError


def test_start_announces_the_mute_state(bridge, monkeypatch):
    """Without this the Mute page shows "switch it on" while it is running."""
    fired = []
    bridge.muteChanged.connect(lambda: fired.append(True))
    monkeypatch.setattr(bridge, "_open_sequencer", lambda: None)
    monkeypatch.setattr(bridge, "refresh", lambda: None)
    monkeypatch.setattr(bridge, "_restore_routing", lambda: None)
    monkeypatch.setattr(bridge, "_offer_to_record_found_routes", lambda: None)
    bridge.start()
    bridge._timer.stop()
    assert fired, "muteChanged was not emitted on start"


# -- the From/To filters reach all three views ---------------------------

@pytest.fixture
def filtered(bridge):
    """Four live ports, two named, and three routes between them."""
    bridge._names.set_name(0, "Drums")
    bridge._names.set_name(1, "Keys")
    bridge._names.set_name(2, "Vox")
    bridge._routing.add(0, 1)      # Drums -> Keys
    bridge._routing.add(1, 2)      # Keys  -> Vox
    bridge._routing.add(2, 0)      # Vox   -> Drums
    return bridge


def pairs_of(rows):
    return [(r["source"]["number"], r["dest"]["number"]) for r in rows]


def edges_of(links):
    return [(l["from"], l["to"]) for l in links]


def test_the_list_is_unfiltered_by_default(filtered):
    assert pairs_of(filtered.routeRows) == [(0, 1), (1, 2), (2, 0)]


def test_the_from_filter_narrows_the_list(filtered):
    filtered.setFilterFrom("Keys")
    assert pairs_of(filtered.routeRows) == [(1, 2)]


def test_the_to_filter_narrows_the_list(filtered):
    filtered.setFilterTo("Drums")
    assert pairs_of(filtered.routeRows) == [(2, 0)]


def test_both_filters_are_ANDed_in_the_list(filtered):
    filtered.setFilterFrom("Drums")
    filtered.setFilterTo("Vox")
    assert pairs_of(filtered.routeRows) == []
    filtered.setFilterTo("Keys")
    assert pairs_of(filtered.routeRows) == [(0, 1)]


def test_the_graph_edges_follow_the_same_filters(filtered):
    """List and graph must never disagree about which routes exist."""
    assert edges_of(filtered.links) == [(0, 1), (1, 2), (2, 0)]
    filtered.setFilterFrom("Keys")
    assert edges_of(filtered.links) == [(1, 2)]
    assert pairs_of(filtered.routeRows) == edges_of(filtered.links)


def test_the_matrix_and_the_list_agree_under_a_filter(filtered):
    """The matrix shows cells, the list shows routes; the same ones."""
    filtered.setFilterFrom("Keys")
    sources = [p["number"] for p in filtered.sourcePorts]
    dests = [p["number"] for p in filtered.destPorts]
    from_matrix = [(sources[r], dests[c])
                   for r, row in enumerate(filtered.matrix)
                   for c, cell in enumerate(row) if cell & 1]
    assert sorted(from_matrix) == sorted(pairs_of(filtered.routeRows))


def test_clearing_the_filters_restores_every_route(filtered):
    filtered.setFilterFrom("Drums")
    filtered.setFilterTo("Keys")
    assert len(filtered.routeRows) == 1
    filtered.setFilterFrom("")
    filtered.setFilterTo("")
    assert len(filtered.routeRows) == 3


def test_a_filter_matches_the_kernel_name_and_the_remark_too(filtered):
    """Same search as the matrix axes: all three of a port's names."""
    filtered._names.set_remark(1, "from the live room")
    filtered.setFilterFrom("live room")
    assert pairs_of(filtered.routeRows) == [(1, 2)]
    filtered.setFilterFrom("Port-2")          # the kernel name
    assert pairs_of(filtered.routeRows) == [(2, 0)]


def test_a_route_to_an_absent_port_stays_in_the_list(bridge):
    """The list is the only place such a route can be seen and deleted.

    Filtering by membership of sourcePorts would drop it, because those
    lists hold live ports only -- which is right for the matrix axes and
    wrong here.
    """
    bridge._routing.add(9, 8)              # neither port is live
    assert pairs_of(bridge.routeRows) == [(9, 8)]
    assert edges_of(bridge.links) == [(9, 8)]
    assert bridge.routeRows[0]["source"]["exists"] is False


def test_an_absent_port_can_still_be_filtered_for(bridge):
    bridge._routing.add(9, 8)
    bridge._names.set_name(9, "Unplugged")
    bridge.setFilterFrom("Unplugged")
    assert pairs_of(bridge.routeRows) == [(9, 8)]
    bridge.setFilterFrom("something else")
    assert pairs_of(bridge.routeRows) == []


def test_changing_a_filter_tells_the_views_to_redraw(filtered):
    """routingChanged is what the list model and the canvas listen to."""
    fired = []
    filtered.routingChanged.connect(lambda: fired.append(1))
    filtered.setFilterFrom("Keys")
    assert fired


# -- sorting the list ----------------------------------------------------

def test_sort_by_source_reorders_and_saves(bridge):
    for pair in [(3, 1), (1, 2), (2, 0)]:
        bridge._routing.add(*pair)
    bridge.sortRouting(True)
    assert pairs_of(bridge.routeRows) == [(1, 2), (2, 0), (3, 1)]
    # The file, not just the object: sorting is meant to survive a restart.
    assert [(l.source, l.dest) for l in Routing.load().links()] == \
        [(1, 2), (2, 0), (3, 1)]


def test_sort_by_destination_reorders_and_saves(bridge):
    for pair in [(3, 1), (1, 2), (2, 0)]:
        bridge._routing.add(*pair)
    bridge.sortRouting(False)
    assert pairs_of(bridge.routeRows) == [(2, 0), (3, 1), (1, 2)]
    assert [(l.source, l.dest) for l in Routing.load().links()] == \
        [(2, 0), (3, 1), (1, 2)]


def test_sorting_tells_the_views_to_redraw(bridge):
    for pair in [(3, 1), (1, 2)]:
        bridge._routing.add(*pair)
    fired = []
    bridge.routingChanged.connect(lambda: fired.append(1))
    bridge.sortRouting(True)
    assert fired


def test_sorting_an_already_sorted_list_says_so_and_does_not_rewrite(bridge):
    for pair in [(1, 2), (3, 1)]:
        bridge._routing.add(*pair)
    bridge._routing.save()
    before = Routing.path().stat().st_mtime_ns
    notices = []
    bridge.noticeRaised.connect(notices.append)
    bridge.sortRouting(True)
    assert "already in that order" in notices[-1]
    assert Routing.path().stat().st_mtime_ns == before


def test_sorting_does_not_touch_the_kernel(bridge):
    """Order is presentation. The same routes are connected either way."""
    seq = RecordingSeq(live=[(3, 1), (1, 2)])
    bridge._seq = seq
    for pair in [(3, 1), (1, 2)]:
        bridge._routing.add(*pair)
    before = seq.connections()
    bridge.sortRouting(True)
    assert seq.connections() == before
    assert seq.disconnected == []


def test_sorting_leaves_unsaved_live_routes_at_the_end(bridge):
    """They are not in the file, so there is nowhere to sort them to."""
    bridge._routing.add(3, 1)
    bridge._routing.add(1, 2)
    bridge._live_links = {Link(0, 3)}
    bridge.sortRouting(True)
    assert pairs_of(bridge.routeRows) == [(1, 2), (3, 1), (0, 3)]


def test_the_notice_counts_what_was_sorted(bridge):
    for pair in [(3, 1), (1, 2), (2, 0)]:
        bridge._routing.add(*pair)
    notices = []
    bridge.noticeRaised.connect(notices.append)
    bridge.sortRouting(True)
    assert "3 routes sorted by source" in notices[-1]
    bridge.sortRouting(False)
    assert "sorted by destination" in notices[-1]
