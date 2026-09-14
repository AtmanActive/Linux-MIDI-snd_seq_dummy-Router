import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// The port number, in that port's colour, which opens a colour chooser.
//
// The badge is the control because the badge is the thing being coloured --
// there is no separate swatch to hunt for, and the number stays legible
// because every palette entry is mid-tone enough for white text.
Item {
    id: control
    Theme { id: t }

    property int portNumber: -1
    property string colourName: ""
    property string colourHex: ""
    property bool exists: true
    property bool editable: true
    //: The colour used when the port has no colour of its own.
    property color fallback: t.accent

    //: While true a tap picks the port instead of opening the colour menu,
    //: and `blinkOpacity` is applied so the badge advertises that it is
    //: waiting to be chosen.
    property bool selecting: false
    property real blinkOpacity: 1
    signal selected()

    implicitWidth: t.fs(28)
    implicitHeight: t.fs(22)

    readonly property color shown: colourHex.length > 0 ? colourHex
                                 : (exists ? fallback : t.line)

    Rectangle {
        anchors.fill: parent
        radius: 4
        color: control.shown
        opacity: (control.exists ? 1 : 0.6)
                 * (control.selecting ? control.blinkOpacity : 1)
        border.color: hover.hovered && control.editable
                      ? Qt.lighter(control.shown, 1.5) : "transparent"

        Label {
            anchors.centerIn: parent
            text: control.portNumber
            color: control.colourHex.length > 0 || control.exists ? "#ffffff" : t.dim
            font.pixelSize: t.fs(11)
            font.weight: Font.DemiBold
        }
    }

    HoverHandler {
        id: hover
        enabled: control.editable || control.selecting
        cursorShape: Qt.PointingHandCursor
    }
    TapHandler {
        enabled: control.editable || control.selecting
        // Selecting wins: while a swap is being picked, a tap must not open
        // a colour menu over the top of it.
        onTapped: control.selecting ? control.selected() : menu.open()
    }

    Popup {
        id: menu
        y: control.height + 3
        width: t.fs(160)
        padding: 4
        background: Rectangle {
            color: t.surface
            border.color: t.line
            radius: 6
        }

        ColumnLayout {
            width: parent.width
            spacing: 0

            Repeater {
                model: bridge.portColourNames
                delegate: Rectangle {
                    required property string modelData
                    Layout.fillWidth: true
                    implicitHeight: t.fs(24)
                    radius: 4
                    color: swatchHover.hovered
                           ? Qt.rgba(t.accent.r, t.accent.g, t.accent.b, 0.18)
                           : "transparent"

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 6
                        anchors.rightMargin: 6
                        spacing: 8
                        Rectangle {
                            implicitWidth: t.fs(14); implicitHeight: t.fs(14)
                            radius: 3
                            color: bridge.portColours[modelData]
                        }
                        Label {
                            Layout.fillWidth: true
                            text: modelData
                            color: t.text
                            font.pixelSize: t.fs(11)
                        }
                        Label {
                            visible: control.colourName === modelData
                            text: "✓"
                            color: t.accent
                            font.pixelSize: t.fs(11)
                        }
                    }

                    HoverHandler { id: swatchHover; cursorShape: Qt.PointingHandCursor }
                    TapHandler {
                        onTapped: {
                            var chosen = modelData
                            menu.close()
                            bridge.setPortColour(control.portNumber, chosen)
                        }
                    }
                }
            }

            Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: t.line }

            Rectangle {
                Layout.fillWidth: true
                implicitHeight: t.fs(24)
                radius: 4
                color: noneHover.hovered
                       ? Qt.rgba(t.accent.r, t.accent.g, t.accent.b, 0.18)
                       : "transparent"
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 6
                    spacing: 8
                    Rectangle {
                        implicitWidth: t.fs(14); implicitHeight: t.fs(14)
                        radius: 3
                        color: "transparent"
                        border.color: t.dim
                    }
                    Label {
                        Layout.fillWidth: true
                        text: "None"
                        color: t.dim
                        font.pixelSize: t.fs(11)
                    }
                    Label {
                        visible: control.colourName === ""
                        text: "✓"
                        color: t.accent
                        font.pixelSize: t.fs(11)
                        rightPadding: 6
                    }
                }
                HoverHandler { id: noneHover; cursorShape: Qt.PointingHandCursor }
                TapHandler {
                    onTapped: {
                        menu.close()
                        bridge.setPortColour(control.portNumber, "")
                    }
                }
            }
        }
    }
}
