"""The export/import slots QML calls.

Runs against a real Bridge with no sequencer: what matters here is that the
right dialog is asked for, that nothing is written before the user chooses,
and that everything in memory is rebuilt afterwards.
"""

import json
import os
import zipfile

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from lmssdr.core import archive, ports, routing, settings     # noqa: E402
from lmssdr.core.settings import Settings                     # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def bridge(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    from lmssdr.ui.bridge import Bridge
    b = Bridge(Settings.load())
    b._live_ports = [0, 1, 2, 3]
    b._live_links = set()
    return b


@pytest.fixture
def signals(bridge):
    """Everything the archive flow can emit, recorded."""
    seen = {"error": [], "notice": [], "rejected": [], "opened": []}
    bridge.errorRaised.connect(lambda m: seen["error"].append(m))
    bridge.noticeRaised.connect(lambda m: seen["notice"].append(m))
    bridge.archiveRejected.connect(lambda m: seen["rejected"].append(m))
    bridge.archiveOpened.connect(lambda n: seen["opened"].append(n))
    return seen


def full_config():
    s = Settings.load()
    s.port_count = 24
    s.save()
    names = ports.PortNames()
    names.set_name(3, "Drums")
    names.save()
    route = routing.Routing()
    route.add(1, 2)
    route.save()


# -- export ---------------------------------------------------------------

def test_export_accepts_a_file_url(bridge, signals, tmp_path):
    full_config()
    dest = tmp_path / "out.zip"
    assert bridge.exportArchive(f"file://{dest}") is True
    assert dest.exists()
    assert signals["error"] == []
    assert "exported to" in signals["notice"][0]


def test_export_accepts_a_plain_path(bridge, signals, tmp_path):
    full_config()
    dest = tmp_path / "out.zip"
    assert bridge.exportArchive(str(dest)) is True


def test_export_with_no_file_chosen_is_an_error(bridge, signals):
    assert bridge.exportArchive("") is False
    assert signals["error"]


def test_export_with_nothing_saved_says_so(bridge, signals, tmp_path):
    """A first run has written no files at all."""
    for entry in archive.REGISTRY:
        entry.path.unlink(missing_ok=True)
    assert bridge.exportArchive(str(tmp_path / "out.zip")) is False
    assert "nothing saved" in signals["error"][0].lower()


def test_exportable_files_lists_what_exists(bridge):
    full_config()
    assert bridge.exportableFiles == [e.filename for e in archive.REGISTRY]


# -- opening --------------------------------------------------------------

def test_opening_a_good_archive_offers_its_contents(bridge, signals, tmp_path):
    full_config()
    dest = tmp_path / "out.zip"
    bridge.exportArchive(str(dest))
    bridge.openArchive(f"file://{dest}")
    assert signals["opened"] == [3]
    assert signals["rejected"] == []
    assert [i["key"] for i in bridge.archiveItems] == \
        ["settings", "ports", "routing"]
    assert bridge.archiveName == "out.zip"


def test_opening_writes_nothing(bridge, signals, tmp_path):
    """The user has not chosen anything yet."""
    full_config()
    dest = tmp_path / "out.zip"
    bridge.exportArchive(str(dest))
    routing.Routing().save()
    bridge.openArchive(str(dest))
    assert len(routing.Routing.load()) == 0


def test_a_zip_without_our_files_is_rejected(bridge, signals, tmp_path):
    dest = tmp_path / "holiday.zip"
    with zipfile.ZipFile(dest, "w") as zf:
        zf.writestr("photo.jpg", b"x")
    bridge.openArchive(str(dest))
    assert signals["opened"] == []
    assert "does not contain" in signals["rejected"][0]
    assert bridge.archiveItems == []


def test_a_broken_archive_is_rejected_with_the_reason(bridge, signals, tmp_path):
    dest = tmp_path / "notes.txt"
    dest.write_text("hello")
    bridge.openArchive(str(dest))
    assert signals["opened"] == []
    assert "ZIP" in signals["rejected"][0]


def test_opening_a_second_archive_replaces_the_first(bridge, signals, tmp_path):
    full_config()
    good = tmp_path / "good.zip"
    bridge.exportArchive(str(good))
    bridge.openArchive(str(good))
    assert bridge.archiveItems

    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr("photo.jpg", b"x")
    bridge.openArchive(str(bad))
    assert bridge.archiveItems == [], "stale items would be imported by mistake"


# -- importing ------------------------------------------------------------

def test_import_without_an_open_archive_is_an_error(bridge, signals):
    bridge.importArchive(["routing"])
    assert signals["error"]


def test_import_with_nothing_chosen_is_an_error(bridge, signals, tmp_path):
    full_config()
    dest = tmp_path / "out.zip"
    bridge.exportArchive(str(dest))
    bridge.openArchive(str(dest))
    bridge.importArchive([])
    assert signals["error"]


def test_importing_routing_reloads_it(bridge, signals, tmp_path):
    full_config()
    dest = tmp_path / "out.zip"
    bridge.exportArchive(str(dest))
    routing.Routing().save()
    bridge._routing = routing.Routing.load()
    assert len(bridge._routing) == 0

    bridge.openArchive(str(dest))
    bridge.importArchive(["routing"])
    assert len(bridge._routing) == 1, "the bridge kept its old routing object"
    assert signals["error"] == []
    assert "Imported routing" in signals["notice"][-1]


def test_importing_ports_reloads_the_names(bridge, signals, tmp_path):
    full_config()
    dest = tmp_path / "out.zip"
    bridge.exportArchive(str(dest))
    ports.PortNames().save()
    bridge._names = ports.PortNames.load()

    bridge.openArchive(str(dest))
    bridge.importArchive(["ports"])
    assert bridge._names.get(3).name == "Drums"


def test_importing_settings_rebinds_the_settings_object(bridge, signals, tmp_path):
    full_config()
    dest = tmp_path / "out.zip"
    bridge.exportArchive(str(dest))
    s = Settings.load()
    s.port_count = 8
    s.save()
    bridge._settings = s
    assert bridge.portCount == 8

    bridge.openArchive(str(dest))
    bridge.importArchive(["settings"])
    assert bridge.portCount == 24


def test_importing_settings_emits_what_the_interface_binds_to(bridge, tmp_path):
    full_config()
    dest = tmp_path / "out.zip"
    bridge.exportArchive(str(dest))
    bridge.openArchive(str(dest))

    fired = []
    for name in ("settingsChanged", "paletteChanged", "fontScaleChanged",
                 "moduleChanged", "muteChanged"):
        getattr(bridge, name).connect(lambda n=name: fired.append(n))
    bridge.importArchive(["settings"])
    assert set(fired) >= {"settingsChanged", "paletteChanged",
                          "fontScaleChanged", "moduleChanged", "muteChanged"}


def test_importing_ports_emits_portsChanged(bridge, tmp_path):
    full_config()
    dest = tmp_path / "out.zip"
    bridge.exportArchive(str(dest))
    bridge.openArchive(str(dest))
    fired = []
    bridge.portsChanged.connect(lambda: fired.append(1))
    bridge.importArchive(["ports"])
    assert fired


def test_importing_only_one_item_leaves_the_others_alone(bridge, signals,
                                                         tmp_path):
    full_config()
    dest = tmp_path / "out.zip"
    bridge.exportArchive(str(dest))
    s = Settings.load()
    s.port_count = 8
    s.save()
    bridge._settings = s

    bridge.openArchive(str(dest))
    bridge.importArchive(["routing"])
    assert bridge.portCount == 8


def test_the_notice_names_what_was_imported(bridge, signals, tmp_path):
    full_config()
    dest = tmp_path / "out.zip"
    bridge.exportArchive(str(dest))
    bridge.openArchive(str(dest))
    bridge.importArchive(["ports", "routing"])
    message = signals["notice"][-1]
    assert "port names" in message and "routing" in message
    assert "out.zip" in message


def test_a_port_count_that_needs_a_kernel_reload_is_flagged(bridge, signals,
                                                            tmp_path,
                                                            monkeypatch):
    """An import must not trigger a password prompt on its own."""
    full_config()
    dest = tmp_path / "out.zip"
    bridge.exportArchive(str(dest))
    s = Settings.load()
    s.port_count = 8
    s.save()
    bridge._settings = s
    # Whatever the kernel really has, it is not 24.
    monkeypatch.setattr(type(bridge), "moduleMatches",
                        property(lambda self: False))

    bridge.openArchive(str(dest))
    bridge.importArchive(["settings"])
    assert "press Apply" in signals["notice"][-1]


def test_import_survives_a_config_written_by_a_newer_version(bridge, signals,
                                                             tmp_path):
    """Unknown keys are kept on disk and ignored on load, not an error."""
    dest = tmp_path / "future.zip"
    payload = {"port_count": 12, "some_future_setting": True}
    with zipfile.ZipFile(dest, "w") as zf:
        zf.writestr(settings.FILE_NAME, json.dumps(payload))
    bridge.openArchive(str(dest))
    bridge.importArchive(["settings"])
    assert signals["error"] == []
    assert bridge.portCount == 12
    on_disk = json.loads(Settings.path().read_text())
    assert on_disk["some_future_setting"] is True
