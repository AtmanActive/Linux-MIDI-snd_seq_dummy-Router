import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// A port chooser that shows what the Ports page shows: the number, the alias,
// and the colour the port was tagged with.
//
// The number is zero-padded to three digits and monospaced so the aliases
// line up in a column; a ragged left edge is hard to scan when the list is
// long, which is the situation this control exists for.
ThemedComboBox {
    id: control
    objectName: "portCombo"
    Theme { id: t }

    property var ports: []
    property int portNumber: -1
    //: Offer a "None" entry, for settings that are optional.
    property bool allowNone: false
    property string noneLabel: "None"
    signal picked(int number)

    readonly property var entries:
        allowNone ? [{ number: -1, displayName: noneLabel, colourHex: "" }]
                    .concat(ports)
                  : ports

    function pad(number) {
        return number < 0 ? "---" : ("00" + number).slice(-3)
    }
    function indexOfPort(number) {
        for (var i = 0; i < entries.length; i++)
            if (entries[i].number === number) return i
        return -1
    }
    readonly property var current: entries[currentIndex] || null

    model: entries
    font.pixelSize: t.fs(12)

    // currentIndex is re-asserted rather than bound. ComboBox assigns it
    // itself whenever the model changes -- including when the port list
    // arrives, which happens after this loads -- and that assignment would
    // replace a binding with a constant. So it is set explicitly at the
    // three moments it can go stale.
    // Deferred with Qt.callLater, not called directly: when the model
    // changes, ComboBox resets currentIndex to 0 as part of its own update,
    // and that reset lands *after* this handler runs. Setting the index
    // immediately is therefore overwritten a moment later; setting it on the
    // next tick is not.
    function syncIndex() { currentIndex = indexOfPort(portNumber) }
    Component.onCompleted: Qt.callLater(syncIndex)
    onEntriesChanged: Qt.callLater(syncIndex)
    onPortNumberChanged: Qt.callLater(syncIndex)

    onActivated: function (index) {
        if (index >= 0 && index < entries.length)
            control.picked(entries[index].number)
    }

    contentItem: RowLayout {
        spacing: 8

        Label {
            // RowLayout has no padding of its own; the inset goes on the
            // first child.
            Layout.leftMargin: 10
            text: control.current ? control.pad(control.current.number) + ":" : "—"
            color: t.dim
            font.pixelSize: t.fs(12)
            font.family: "monospace"
        }
        Label {
            Layout.fillWidth: true
            text: control.current ? control.current.displayName
                                  : "Choose a port…"
            color: control.current ? t.text : t.dim
            font.pixelSize: t.fs(12)
            elide: Text.ElideRight
        }
        // The LED trails the alias rather than leading it, so the aliases
        // still start at one column.
        Rectangle {
            visible: control.current && control.current.colourHex.length > 0
            implicitWidth: t.fs(10); implicitHeight: t.fs(10)
            radius: width / 2
            color: control.current ? control.current.colourHex : "transparent"
            Layout.rightMargin: t.fs(20)
        }
    }

    delegate: ItemDelegate {
        required property var modelData
        required property int index
        width: control.width
        highlighted: control.highlightedIndex === index

        contentItem: RowLayout {
            spacing: 8
            Label {
                text: control.pad(modelData.number) + ":"
                color: t.dim
                font.pixelSize: t.fs(12)
                font.family: "monospace"
            }
            Label {
                Layout.fillWidth: true
                text: modelData.displayName
                color: t.text
                font.pixelSize: t.fs(12)
                elide: Text.ElideRight
            }
            Rectangle {
                visible: modelData.colourHex.length > 0
                implicitWidth: t.fs(10); implicitHeight: t.fs(10)
                radius: width / 2
                color: modelData.colourHex
            }
        }
    }
}
