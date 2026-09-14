import QtQuick
import QtQuick.Controls

// A checkbox in the application palette. The stock one paints from the
// system style, which on a dark theme leaves an unreadable tick.
//
// Separate from ThemedSwitch because these say different things: a switch
// turns a feature on, a checkbox picks items out of a set.
CheckBox {
    id: control
    Theme { id: t }

    property bool partial: false

    implicitHeight: Math.max(t.fs(24), contentLabel.implicitHeight)
    spacing: t.fs(8)

    HoverHandler { cursorShape: control.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor }

    indicator: Rectangle {
        implicitWidth: t.fs(18); implicitHeight: t.fs(18)
        x: control.leftPadding
        y: control.topPadding + (control.availableHeight - height) / 2
        radius: 4
        color: (control.checked || control.partial) ? t.accent : "transparent"
        border.color: (control.checked || control.partial) ? t.accent : t.line
        opacity: control.enabled ? 1 : 0.45
        Behavior on color { ColorAnimation { duration: 110 } }

        // A tick when checked, a dash when some-but-not-all are.
        Label {
            anchors.centerIn: parent
            visible: control.checked || control.partial
            text: control.checked ? "✓" : "–"
            color: "#ffffff"
            font.pixelSize: t.fs(13)
            font.weight: Font.Bold
        }
    }

    contentItem: Label {
        id: contentLabel
        text: control.text
        color: t.text
        opacity: control.enabled ? 1 : 0.5
        font.pixelSize: t.fs(12)
        verticalAlignment: Text.AlignVCenter
        leftPadding: control.indicator.width + control.spacing
    }
}
