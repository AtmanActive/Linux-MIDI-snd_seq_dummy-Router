import QtQuick
import QtQuick.Controls

Dialog {
    id: control
    Theme { id: t }

    anchors.centerIn: Overlay.overlay
    modal: true
    width: Math.min(460, parent ? parent.width - 40 : 460)
    padding: 18

    background: Rectangle {
        color: t.surface
        border.color: t.line
        radius: 10
    }

    header: Label {
        text: control.title
        visible: control.title.length > 0
        color: t.text
        font.pixelSize: t.fs(15)
        font.weight: Font.DemiBold
        padding: 18
        bottomPadding: 0
    }
}
