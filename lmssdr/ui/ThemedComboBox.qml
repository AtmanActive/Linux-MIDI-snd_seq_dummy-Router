import QtQuick
import QtQuick.Controls

// A ComboBox wearing the application's palette.
//
// The stock control paints itself from the Qt style's own palette, which on
// this platform is light regardless of the app theme -- so a dark theme ends
// up with white boxes, and any custom contentItem drawing in theme colours
// becomes pale text on a pale background.
ComboBox {
    id: control
    Theme { id: t }

    font.pixelSize: t.fs(12)
    implicitHeight: Math.max(30, t.fs(32))

    background: Rectangle {
        radius: 5
        color: t.isDark ? Qt.darker(t.bg, 1.12) : Qt.darker(t.bg, 1.02)
        border.color: control.activeFocus || control.hovered ? t.accent : t.line
    }

    indicator: Label {
        x: control.width - width - t.fs(10)
        y: control.topPadding + (control.availableHeight - height) / 2
        text: "▾"
        color: t.dim
        font.pixelSize: t.fs(12)
    }

    contentItem: Label {
        leftPadding: 10
        rightPadding: control.indicator.width + t.fs(14)
        text: control.displayText
        color: t.text
        font: control.font
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }

    delegate: ItemDelegate {
        required property var modelData
        required property int index
        width: control.width
        highlighted: control.highlightedIndex === index

        background: Rectangle {
            color: highlighted ? Qt.rgba(t.accent.r, t.accent.g, t.accent.b, 0.20)
                               : "transparent"
        }
        contentItem: Label {
            text: control.textRole
                  ? (modelData[control.textRole] !== undefined
                     ? modelData[control.textRole] : modelData)
                  : modelData
            color: t.text
            font.pixelSize: t.fs(12)
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
    }

    popup: Popup {
        y: control.height + 2
        width: control.width
        implicitHeight: Math.min(contentItem.implicitHeight + 2, t.fs(320))
        padding: 1

        background: Rectangle {
            color: t.surface
            border.color: t.accent
            radius: 6
        }
        contentItem: ListView {
            clip: true
            implicitHeight: contentHeight
            model: control.popup.visible ? control.delegateModel : null
            currentIndex: control.highlightedIndex
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
        }
    }
}
