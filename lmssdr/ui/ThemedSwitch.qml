import QtQuick
import QtQuick.Controls

Switch {
    id: control
    Theme { id: t }

    HoverHandler { cursorShape: Qt.PointingHandCursor }

    indicator: Rectangle {
        implicitWidth: t.fs(40); implicitHeight: t.fs(22)
        x: control.width - width - control.rightPadding
        y: control.topPadding + (control.availableHeight - height) / 2
        radius: height / 2
        color: control.checked ? t.accent : t.line
        Behavior on color { ColorAnimation { duration: 120 } }

        Rectangle {
            x: control.checked ? parent.width - width - 2 : 2
            y: 2
            width: parent.height - 4; height: width
            radius: width / 2
            color: "#ffffff"
            Behavior on x { NumberAnimation { duration: 120; easing.type: Easing.OutQuad } }
        }
    }

    contentItem: Label {
        text: control.text
        color: t.text
        font.pixelSize: t.fs(12)
        verticalAlignment: Text.AlignVCenter
        rightPadding: control.indicator.width + t.fs(10)
    }
}
