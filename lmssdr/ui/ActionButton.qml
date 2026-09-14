import QtQuick
import QtQuick.Controls

Button {
    id: control
    Theme { id: t }

    property bool primary: false
    property bool danger: false

    implicitHeight: Math.max(32, t.fs(34))
    implicitWidth: Math.max(96, contentLabel.implicitWidth + t.fs(28))
    enabled: true

    HoverHandler { cursorShape: control.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor }

    background: Rectangle {
        radius: 6
        border.color: control.danger ? t.danger
                    : control.primary ? t.accent : t.line
        // A disabled button keeps its fill. Dropping to a transparent
        // background left it reading as a label with a faint outline, which
        // is not how a control that is merely unavailable should look.
        color: {
            if (control.primary)
                return control.pressed ? Qt.darker(t.accent, 1.25) : t.accent
            if (control.pressed) return t.line
            // Raised off the surface rather than level with it, so a button
            // is a button on any background the app puts it on.
            return t.isDark ? Qt.lighter(t.surface, 1.35)
                            : Qt.darker(t.surface, 1.06)
        }
        opacity: control.enabled ? 1 : 0.42
    }

    contentItem: Label {
        id: contentLabel
        text: control.text
        // On a filled accent button the label must not use the theme text
        // colour: in light mode that is near-black on a mid-tone accent.
        color: control.primary ? "#ffffff"
             : control.danger ? t.danger : t.text
        opacity: control.enabled ? 1 : 0.5
        font.pixelSize: t.fs(12)
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
    }
}
