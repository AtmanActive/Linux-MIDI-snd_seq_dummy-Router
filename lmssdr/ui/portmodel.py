"""A list model for the ports table.

Why not just hand QML a JavaScript array: assigning a new array to a
ListView's `model` is a *reset*. Every delegate is destroyed and rebuilt and
the view jumps back to the top. Renaming a port rebuilds the row data, so
with a plain array the list scrolls to the top the moment you press Enter --
which is unusable for anything past the first screenful.

A QAbstractListModel can say "row 12 changed" instead. The view repaints one
delegate, keeps every other one alive, and does not move. Resets then happen
only when the set of rows genuinely changes -- a filter, a new port count --
where returning to the top is the right behaviour anyway.
"""

from __future__ import annotations

from typing import Dict, List

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt

#: Role name -> role id. The names are what QML sees on each delegate.
ROLE_NAMES = ("number", "kernelName", "name", "remark", "displayName",
              "colour", "colourHex", "exists")
ROLES = {name: Qt.UserRole + i for i, name in enumerate(ROLE_NAMES)}


class PortListModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: List[Dict] = []

    # -- QAbstractListModel ---------------------------------------------

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        row = self._rows[index.row()]
        for key, role_id in ROLES.items():
            if role == role_id:
                return row.get(key)
        return None

    def roleNames(self):
        return {role_id: key.encode() for key, role_id in ROLES.items()}

    # -- updating --------------------------------------------------------

    def set_rows(self, rows: List[Dict]) -> None:
        """Replace the contents, resetting only when the rows are not the same.

        "The same" means the same ports in the same order. If they are, the
        differences are edits to existing rows and each one is reported as a
        change to that row alone, which is what keeps the view still.
        """
        same_identity = ([r["number"] for r in rows]
                         == [r["number"] for r in self._rows])
        if not same_identity:
            self.beginResetModel()
            self._rows = list(rows)
            self.endResetModel()
            return

        changed = [i for i, (old, new) in enumerate(zip(self._rows, rows))
                   if old != new]
        if not changed:
            return
        self._rows = list(rows)
        # One span covering the changed rows: for the usual case of a single
        # edit that is exactly one row, and for a bulk change it is cheaper
        # than a signal per row.
        top, bottom = min(changed), max(changed)
        self.dataChanged.emit(self.index(top, 0), self.index(bottom, 0),
                              list(ROLES.values()))

    def row_at(self, position: int) -> Dict:
        return dict(self._rows[position])
