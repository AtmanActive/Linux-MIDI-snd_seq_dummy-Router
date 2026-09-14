import pytest

from lmssdr.core.ports import PortInfo, PortNames, kernel_name


def test_kernel_name():
    assert kernel_name(0) == "Midi Through Port-0"
    assert kernel_name(17) == "Midi Through Port-17"


def test_display_name_falls_back_to_kernel_name():
    assert PortInfo(3).display_name == "Midi Through Port-3"
    assert PortInfo(3, name="Reaper Send").display_name == "Reaper Send"
    # Whitespace is not a name.
    assert PortInfo(3, name="   ").display_name == "Midi Through Port-3"


def test_label_shows_both_names_when_named():
    assert PortInfo(3).label == "Midi Through Port-3"
    assert PortInfo(3, name="Reaper Send").label == "Reaper Send  (Midi Through Port-3)"


def test_round_trip():
    db = PortNames.load()
    db.set_name(1, "Transport")
    db.set_remark(1, "Mackie play/stop from Reaper")
    db.set_name(11, "Transport Return")
    db.save()

    again = PortNames.load()
    assert again.get(1).name == "Transport"
    assert again.get(1).remark == "Mackie play/stop from Reaper"
    assert again.get(11).name == "Transport Return"


def test_blank_entries_are_not_persisted():
    db = PortNames.load()
    db.get(5)                      # touched but never filled in
    db.set_name(6, "Real")
    db.save()
    assert set(PortNames.load()._entries) == {6}


def test_names_survive_shrinking_the_port_count():
    """Lowering the port count must not destroy names for ports above it."""
    db = PortNames.load()
    db.set_name(30, "Spare")
    db.save()

    shrunk = PortNames.load()
    assert [i.number for i in shrunk.rows(4)] == [0, 1, 2, 3]
    shrunk.save()                  # a save while small must not drop port 30

    assert PortNames.load().get(30).name == "Spare"


def test_rows_are_contiguous_and_ordered():
    db = PortNames.load()
    rows = db.rows(5)
    assert [r.number for r in rows] == [0, 1, 2, 3, 4]


def test_named_lists_only_named_ports_in_order():
    db = PortNames.load()
    db.set_name(9, "Nine")
    db.set_name(2, "Two")
    db.set_remark(4, "remark only, no name")
    assert [i.number for i in db.named()] == [2, 9]


def test_corrupt_file_falls_back_to_empty(tmp_path, monkeypatch):
    path = PortNames.path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json")
    assert len(PortNames.load()) == 0


def test_junk_keys_are_ignored():
    path = PortNames.path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"ports": {"abc": {"name": "x"}, "2": "not a dict", "3": {"name": "ok"}}}')
    db = PortNames.load()
    assert [i.number for i in db.named()] == [3]


# -- filtering -----------------------------------------------------------

def test_matches_searches_all_three_fields():
    from lmssdr.core.ports import matches
    info = PortInfo(7, name="Drums Send", remark="from the kit room")
    assert matches(info, "drums")           # custom name
    assert matches(info, "kit")             # remark
    assert matches(info, "Port-7")          # kernel name
    assert matches(info, "7")               # bare number, via the kernel name
    assert not matches(info, "keys")


def test_matches_is_case_insensitive():
    from lmssdr.core.ports import matches
    assert matches(PortInfo(1, name="Talkback"), "TALK")
    assert matches(PortInfo(1, name="Talkback"), "tAlKbAcK")


def test_matches_ands_multiple_terms_across_fields():
    """Terms may come from different fields; all must be present."""
    from lmssdr.core.ports import matches
    info = PortInfo(3, name="Keys Return", remark="stage left")
    assert matches(info, "keys return")
    assert matches(info, "keys stage")      # one term per field
    assert not matches(info, "keys drums")


def test_empty_query_matches_everything():
    from lmssdr.core.ports import matches
    assert matches(PortInfo(0), "")
    assert matches(PortInfo(0), "   ")


def test_filter_preserves_order_and_falls_back_to_all():
    db = PortNames.load()
    db.set_name(1, "Drums Send")
    db.set_name(5, "Drums Return")
    db.set_name(9, "Keys Send")
    assert db.filter([1, 5, 9], "drums") == [1, 5]
    assert db.filter([9, 5, 1], "drums") == [5, 1]      # order preserved
    assert db.filter([1, 5, 9], "") == [1, 5, 9]


def test_filter_matches_unnamed_ports_by_kernel_name():
    db = PortNames.load()
    assert db.filter(range(15), "port-1") == [1, 10, 11, 12, 13, 14]


# -- migration from the pre-0.2 file names --------------------------------

@pytest.mark.parametrize("legacy_name", ["lmsdr.ports.json", "ports.json"])
def test_legacy_file_is_renamed_on_load(legacy_name):
    """Both older names migrate: pre-0.2, and the lmssdr spelling."""
    from lmssdr.core.paths import config_dir
    legacy = config_dir() / legacy_name
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text('{"ports": {"4": {"name": "Kept", "remark": "r"}}}')

    db = PortNames.load()
    assert db.get(4).name == "Kept"
    assert db.get(4).remark == "r"
    assert PortNames.path().exists()
    assert not legacy.exists()          # renamed, not copied


def test_migration_never_clobbers_an_existing_file():
    from lmssdr.core.paths import config_dir
    LEGACY_FILE_NAME = "lmsdr.ports.json"
    PortNames.path().parent.mkdir(parents=True, exist_ok=True)
    PortNames.path().write_text('{"ports": {"1": {"name": "Current", "remark": ""}}}')
    legacy = config_dir() / LEGACY_FILE_NAME
    legacy.write_text('{"ports": {"1": {"name": "Old", "remark": ""}}}')

    assert PortNames.load().get(1).name == "Current"
    assert legacy.exists()              # left alone, not deleted


# -- colours --------------------------------------------------------------

def test_fifteen_named_colours():
    from lmssdr.core.ports import PORT_COLOURS, PORT_COLOUR_NAMES
    assert len(PORT_COLOURS) == 15
    assert len(set(PORT_COLOURS.values())) == 15        # all distinct
    assert PORT_COLOUR_NAMES[0] == "Red"
    for name, value in PORT_COLOURS.items():
        assert value.startswith("#") and len(value) == 7, (name, value)


def test_colour_hex_lookup():
    from lmssdr.core.ports import colour_hex
    assert colour_hex("Teal") == "#21a5b8"
    assert colour_hex("Nonexistent") == ""
    assert colour_hex("") == ""


def test_set_and_clear_a_colour():
    db = PortNames.load()
    db.set_colour(3, "Violet")
    assert db.get(3).colour == "Violet"
    assert db.get(3).colour_hex == "#9b7ede"
    db.set_colour(3, "")
    assert db.get(3).colour == "" and db.get(3).colour_hex == ""


def test_unknown_colour_name_untags_rather_than_raising():
    db = PortNames.load()
    db.set_colour(3, "Chartreuse")
    assert db.get(3).colour == ""


def test_colour_round_trips():
    db = PortNames.load()
    db.set_colour(9, "Amber")
    db.save()
    assert PortNames.load().get(9).colour == "Amber"


def test_a_colour_alone_is_worth_persisting():
    """Tagging a port with no name or remark must still be saved."""
    db = PortNames.load()
    db.set_colour(12, "Pink")
    db.save()
    assert PortNames.load().get(12).colour == "Pink"


def test_a_colour_from_an_unknown_palette_is_dropped_on_load():
    path = PortNames.path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"ports": {"4": {"name": "x", "remark": "", "colour": "Puce"}}}')
    info = PortNames.load().get(4)
    assert info.name == "x" and info.colour == ""


# -- swapping two ports ---------------------------------------------------

def test_swap_exchanges_alias_remark_and_colour():
    db = PortNames.load()
    db.set_name(1, "Drums"); db.set_remark(1, "kit room"); db.set_colour(1, "Red")
    db.set_name(9, "Keys");  db.set_remark(9, "stage left"); db.set_colour(9, "Blue")
    assert db.swap(1, 9) is True

    assert (db.get(1).name, db.get(1).remark, db.get(1).colour) == ("Keys", "stage left", "Blue")
    assert (db.get(9).name, db.get(9).remark, db.get(9).colour) == ("Drums", "kit room", "Red")


def test_swap_leaves_the_kernel_name_and_number_alone():
    """Those belong to ALSA; only the user's own labels move."""
    db = PortNames.load()
    db.set_name(1, "Drums")
    db.swap(1, 9)
    assert db.get(1).kernel_name == "Midi Through Port-1"
    assert db.get(9).kernel_name == "Midi Through Port-9"
    assert db.get(1).number == 1 and db.get(9).number == 9


def test_swap_with_an_empty_port_moves_the_identity_across():
    db = PortNames.load()
    db.set_name(3, "Talkback"); db.set_colour(3, "Green")
    db.swap(3, 20)
    assert db.get(20).name == "Talkback" and db.get(20).colour == "Green"
    assert db.get(3).name == "" and db.get(3).colour == ""


def test_swapping_a_port_with_itself_is_refused():
    db = PortNames.load()
    db.set_name(4, "Keep")
    assert db.swap(4, 4) is False
    assert db.get(4).name == "Keep"
