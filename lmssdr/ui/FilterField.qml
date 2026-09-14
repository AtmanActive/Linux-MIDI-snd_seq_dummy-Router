import QtQuick
import QtQuick.Controls

// A search box with a clear button.
//
// Deliberately not debounced: filtering is a local list comprehension over a
// few hundred items at most, and seeing the list narrow as you type is the
// whole point.
TextField {
    id: control
    Theme { id: t }

    property string label: "Filter"

    placeholderText: label + "…"
    color: t.text
    placeholderTextColor: t.dim
    font.pixelSize: t.fs(11)
    leftPadding: t.fs(24)
    rightPadding: clear.visible ? t.fs(24) : t.fs(8)
    implicitHeight: Math.max(28, t.fs(30))

    background: Rectangle {
        radius: 5
        color: t.isDark ? Qt.darker(t.bg, 1.1) : Qt.darker(t.bg, 1.02)
        border.color: control.activeFocus ? t.accent : t.line
    }

    Label {
        x: t.fs(7)
        anchors.verticalCenter: parent.verticalCenter
        text: "⌕"                      // magnifier
        color: t.dim
        font.pixelSize: t.fs(13)
    }

    Label {
        id: clear
        anchors.right: parent.right
        anchors.rightMargin: t.fs(8)
        anchors.verticalCenter: parent.verticalCenter
        visible: control.text.length > 0
        text: "×"
        color: t.dim
        font.pixelSize: t.fs(14)
        MouseArea {
            anchors.fill: parent
            anchors.margins: -4
            cursorShape: Qt.PointingHandCursor
            onClicked: { control.text = ""; control.editingFinished() }
        }
    }
}
