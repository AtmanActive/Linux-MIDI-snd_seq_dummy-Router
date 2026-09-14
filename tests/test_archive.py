"""Exporting and importing the configuration as a ZIP.

The import half is the one worth being paranoid about: it overwrites files
the user cannot easily reconstruct, from a file that arrived from somewhere
else. So the tests here spend most of their time on archives that are wrong.
"""

import json
import zipfile

import pytest

from lmssdr.core import archive, paths, ports, routing, settings


@pytest.fixture
def config(tmp_path, monkeypatch):
    """Point the whole application at a throwaway config directory."""
    home = tmp_path / "config"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home))
    return home / paths.APP_DIR_NAME


def write_all(config):
    """A complete, plausible configuration on disk."""
    s = settings.Settings()
    s.port_count = 24
    s.theme_name = "Ocean"
    s.save()
    names = ports.PortNames()
    names.set_name(3, "Drums")
    names.set_remark(3, "from the kit")
    names.set_colour(3, "Red")
    names.save()
    route = routing.Routing()
    route.add(1, 2)
    route.add(3, 4)
    route.save()
    return config


# -- export ---------------------------------------------------------------

def test_export_writes_every_saved_file(config, tmp_path):
    write_all(config)
    dest = tmp_path / "backup.zip"
    written = archive.export_archive(dest, "1.2.3")
    assert sorted(written) == sorted(e.filename for e in archive.REGISTRY)
    with zipfile.ZipFile(dest) as zf:
        assert archive.MANIFEST_NAME in zf.namelist()
        manifest = json.loads(zf.read(archive.MANIFEST_NAME))
    assert manifest["application"] == "lmssdr"
    assert manifest["version"] == "1.2.3"


def test_export_skips_files_that_do_not_exist(config, tmp_path):
    """A fresh install has no routing yet; that is not an error."""
    settings.Settings().save()
    dest = tmp_path / "backup.zip"
    written = archive.export_archive(dest, "")
    assert written == [settings.FILE_NAME]


def test_export_leaves_no_part_file_behind(config, tmp_path):
    write_all(config)
    dest = tmp_path / "backup.zip"
    archive.export_archive(dest, "")
    assert list(tmp_path.glob("*.part")) == []


def test_export_does_not_clobber_a_good_archive_when_it_fails(config, tmp_path,
                                                              monkeypatch):
    write_all(config)
    dest = tmp_path / "backup.zip"
    archive.export_archive(dest, "")
    good = dest.read_bytes()

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(zipfile.ZipFile, "writestr", boom)
    with pytest.raises(OSError):
        archive.export_archive(dest, "")
    assert dest.read_bytes() == good
    assert list(tmp_path.glob("*.part")) == []


def test_suggested_name_is_a_zip():
    assert archive.suggested_name().startswith("lmssdr.backup.")
    assert archive.suggested_name().endswith(".zip")


# -- inspection -----------------------------------------------------------

def test_a_round_trip_finds_everything(config, tmp_path):
    write_all(config)
    dest = tmp_path / "backup.zip"
    archive.export_archive(dest, "")
    items = archive.inspect_archive(dest)
    assert [item.key for item in items] == ["settings", "ports", "routing"]


def test_items_come_back_in_registry_order(config, tmp_path):
    """However the zip was built, the picker reads the same way."""
    dest = tmp_path / "jumbled.zip"
    with zipfile.ZipFile(dest, "w") as zf:
        zf.writestr(routing.FILE_NAME, json.dumps({"links": []}))
        zf.writestr(ports.FILE_NAME, json.dumps({"ports": {}}))
        zf.writestr(settings.FILE_NAME, json.dumps({}))
    assert [i.key for i in archive.inspect_archive(dest)] == \
        ["settings", "ports", "routing"]


def test_a_zip_with_nothing_of_ours_returns_no_items(tmp_path):
    dest = tmp_path / "holiday.zip"
    with zipfile.ZipFile(dest, "w") as zf:
        zf.writestr("photo.jpg", b"not json")
    assert archive.inspect_archive(dest) == []


def test_a_file_that_is_not_a_zip_is_refused(tmp_path):
    dest = tmp_path / "notes.txt"
    dest.write_text("hello")
    with pytest.raises(archive.ArchiveError):
        archive.inspect_archive(dest)


def test_a_missing_file_is_refused(tmp_path):
    with pytest.raises(archive.ArchiveError):
        archive.inspect_archive(tmp_path / "nope.zip")


def test_a_member_that_is_not_json_is_refused(tmp_path):
    """Better to fail loudly than to overwrite a config with rubbish."""
    dest = tmp_path / "broken.zip"
    with zipfile.ZipFile(dest, "w") as zf:
        zf.writestr(settings.FILE_NAME, "{ truncated")
    with pytest.raises(archive.ArchiveError, match="not valid JSON"):
        archive.inspect_archive(dest)


def test_a_member_that_is_not_an_object_is_refused(tmp_path):
    dest = tmp_path / "broken.zip"
    with zipfile.ZipFile(dest, "w") as zf:
        zf.writestr(ports.FILE_NAME, "[1, 2, 3]")
    with pytest.raises(archive.ArchiveError, match="JSON object"):
        archive.inspect_archive(dest)


def test_an_implausibly_large_member_is_refused(tmp_path):
    """A zip bomb must not be read into memory to find out what it is."""
    dest = tmp_path / "bomb.zip"
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(settings.FILE_NAME, b"{}" + b" " * (archive.MAX_MEMBER_BYTES + 1))
    with pytest.raises(archive.ArchiveError, match="implausibly large"):
        archive.inspect_archive(dest)


def test_legacy_names_are_recognized(tmp_path):
    """A backup taken before the lmsdr -> lmssdr rename still restores."""
    dest = tmp_path / "old.zip"
    with zipfile.ZipFile(dest, "w") as zf:
        zf.writestr("lmsdr.routing.json", json.dumps({"links": [{"from": 1, "to": 2}]}))
    items = archive.inspect_archive(dest)
    assert [i.key for i in items] == ["routing"]
    assert items[0].member == "lmsdr.routing.json"


def test_a_nested_member_is_still_recognized(tmp_path):
    """Zipping the config *directory* is the obvious thing to do by hand."""
    dest = tmp_path / "dir.zip"
    with zipfile.ZipFile(dest, "w") as zf:
        zf.writestr(f"lmssdr/{ports.FILE_NAME}", json.dumps({"ports": {}}))
    assert [i.key for i in archive.inspect_archive(dest)] == ["ports"]


def test_summaries_describe_the_contents(config, tmp_path):
    write_all(config)
    dest = tmp_path / "backup.zip"
    archive.export_archive(dest, "")
    summaries = {i.key: i.summary for i in archive.inspect_archive(dest)}
    assert "24 ports" in summaries["settings"]
    assert "1 named port" in summaries["ports"]
    assert summaries["routing"] == "2 routes"


# -- writing --------------------------------------------------------------

def test_import_overwrites_the_chosen_files_only(config, tmp_path):
    write_all(config)
    dest = tmp_path / "backup.zip"
    archive.export_archive(dest, "")

    # Now change everything, then import only the routing back.
    s = settings.Settings.load()
    s.port_count = 8
    s.save()
    routing.Routing().save()

    items = archive.inspect_archive(dest)
    done = archive.import_items(items, ["routing"])
    assert done == ["routing"]
    assert len(routing.Routing.load()) == 2
    # Untouched.
    assert settings.Settings.load().port_count == 8


def test_import_defaults_to_everything(config, tmp_path):
    write_all(config)
    dest = tmp_path / "backup.zip"
    archive.export_archive(dest, "")
    routing.Routing().save()
    archive.import_items(archive.inspect_archive(dest))
    assert len(routing.Routing.load()) == 2


def test_import_restores_what_was_saved(config, tmp_path):
    write_all(config)
    dest = tmp_path / "backup.zip"
    archive.export_archive(dest, "")
    ports.PortNames().save()

    archive.import_items(archive.inspect_archive(dest), ["ports"])
    restored = ports.PortNames.load().get(3)
    assert restored.name == "Drums"
    assert restored.remark == "from the kit"
    assert restored.colour == "Red"


def test_import_keeps_one_undo_copy(config, tmp_path):
    write_all(config)
    dest = tmp_path / "backup.zip"
    archive.export_archive(dest, "")
    routing.Routing().save()      # wipe it

    archive.import_items(archive.inspect_archive(dest), ["routing"])
    backup = routing.Routing.path().with_name(
        routing.FILE_NAME + archive.BACKUP_SUFFIX)
    assert backup.exists()
    assert json.loads(backup.read_text())["links"] == []


def test_import_writes_a_legacy_member_under_the_current_name(config, tmp_path):
    dest = tmp_path / "old.zip"
    with zipfile.ZipFile(dest, "w") as zf:
        zf.writestr("lmsdr.routing.json",
                    json.dumps({"links": [{"from": 5, "to": 6}]}))
    archive.import_items(archive.inspect_archive(dest))
    assert routing.Routing.path().name == routing.FILE_NAME
    assert routing.Routing.path().exists()
    assert len(routing.Routing.load()) == 1


def test_a_traversing_member_is_never_written(config, tmp_path):
    """The destination comes from the registry, never from the archive."""
    outside = tmp_path / "victim.json"
    outside.write_text("untouched")
    dest = tmp_path / "evil.zip"
    with zipfile.ZipFile(dest, "w") as zf:
        zf.writestr(f"../../../{outside}", json.dumps({"links": []}))
        zf.writestr(f"../../{settings.FILE_NAME}", json.dumps({"port_count": 4}))

    items = archive.inspect_archive(dest)
    # The traversing path whose base name is ours is still recognized -- and
    # still lands in the config directory, because that is where the
    # registry says it goes.
    assert [i.key for i in items] == ["settings"]
    archive.import_items(items)
    assert outside.read_text() == "untouched"
    assert settings.Settings.load().port_count == 4
    assert settings.Settings.path().parent == config


def test_import_of_an_unknown_key_does_nothing(config, tmp_path):
    write_all(config)
    dest = tmp_path / "backup.zip"
    archive.export_archive(dest, "")
    assert archive.import_items(archive.inspect_archive(dest), ["nonsense"]) == []


def test_every_registry_entry_has_a_distinct_file_and_key():
    keys = [e.key for e in archive.REGISTRY]
    names = [e.filename for e in archive.REGISTRY]
    assert len(set(keys)) == len(keys)
    assert len(set(names)) == len(names)
    assert all(e.label and e.describe for e in archive.REGISTRY)
