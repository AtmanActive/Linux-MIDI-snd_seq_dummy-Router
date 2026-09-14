"""The ports list model.

The property that matters is narrow and easy to lose: editing a name must
report a *change to one row*, never a model reset. A reset makes the view
destroy every delegate and scroll back to the top, which is what this model
exists to prevent.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from lmssdr.ui.portmodel import ROLES, PortListModel      # noqa: E402


def rows(*specs):
    return [{"number": n, "kernelName": f"Midi Through Port-{n}", "name": name,
             "remark": "", "displayName": name or f"Midi Through Port-{n}",
             "exists": True}
            for n, name in specs]


@pytest.fixture
def model(qapp_fixture):
    return PortListModel()


@pytest.fixture(scope="module")
def qapp_fixture():
    from PySide6.QtCore import QCoreApplication
    return QCoreApplication.instance() or QCoreApplication([])


class Watcher:
    """Records which structural signals a model emitted."""

    def __init__(self, model):
        self.resets = 0
        self.changes = []
        model.modelAboutToBeReset.connect(self._reset)
        model.dataChanged.connect(
            lambda top, bottom, roles=None: self.changes.append((top.row(), bottom.row())))

    def _reset(self):
        self.resets += 1


def test_populating_an_empty_model_resets(model):
    w = Watcher(model)
    model.set_rows(rows((0, ""), (1, "")))
    assert w.resets == 1
    assert model.rowCount() == 2


def test_editing_one_name_does_not_reset(model):
    model.set_rows(rows((0, ""), (1, ""), (2, "")))
    w = Watcher(model)
    model.set_rows(rows((0, ""), (1, "Drums"), (2, "")))
    assert w.resets == 0                      # the whole point
    assert w.changes == [(1, 1)]              # exactly the row that changed


def test_identical_rows_emit_nothing(model):
    model.set_rows(rows((0, "a"), (1, "b")))
    w = Watcher(model)
    model.set_rows(rows((0, "a"), (1, "b")))
    assert w.resets == 0 and w.changes == []


def test_changing_the_row_set_does_reset(model):
    """A filter or a new port count should return to the top."""
    model.set_rows(rows((0, ""), (1, ""), (2, "")))
    w = Watcher(model)
    model.set_rows(rows((1, "")))
    assert w.resets == 1


def test_reordering_counts_as_a_new_row_set(model):
    model.set_rows(rows((0, ""), (1, "")))
    w = Watcher(model)
    model.set_rows(rows((1, ""), (0, "")))
    assert w.resets == 1


def test_multiple_edits_report_one_span(model):
    model.set_rows(rows((0, ""), (1, ""), (2, ""), (3, "")))
    w = Watcher(model)
    model.set_rows(rows((0, "x"), (1, ""), (2, ""), (3, "y")))
    assert w.resets == 0
    assert w.changes == [(0, 3)]


def test_roles_reach_qml_by_name(model):
    model.set_rows(rows((7, "Talkback")))
    index = model.index(0, 0)
    assert model.data(index, ROLES["number"]) == 7
    assert model.data(index, ROLES["name"]) == "Talkback"
    assert model.data(index, ROLES["kernelName"]) == "Midi Through Port-7"
    names = {v.decode() for v in model.roleNames().values()}
    assert {"number", "name", "kernelName", "remark", "displayName", "exists"} <= names


def test_out_of_range_is_safe(model):
    model.set_rows(rows((0, "")))
    assert model.data(model.index(5, 0), ROLES["name"]) is None
