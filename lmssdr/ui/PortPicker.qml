import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// A port shown in full -- number, custom name, kernel name, remark -- that
// opens a chooser when clicked.
//
// The whole badge is the button, not just the triangle: a 10 px glyph is a
// poor target, and anyone who wants to change the port will aim at the port.
Item {
    id: control
    objectName: "portPicker"
    Theme { id: t }

    property int portNumber: -1
    property var ports: []            // [{number, name, kernelName, remark}]
    property bool editable: true
    signal picked(int number)

    implicitHeight: badge.implicitHeight
    implicitWidth: Math.max(220, t.fs(240))

    function detailFor(number) {
        for (var i = 0; i < ports.length; i++)
            if (ports[i].number === number) return ports[i]
        return null
    }
    function indexOf(number) {
        for (var i = 0; i < ports.length; i++)
            if (ports[i].number === number) return i
        return -1
    }

    readonly property var detail: detailFor(portNumber)

    Rectangle {
        id: badge
        anchors.fill: parent
        radius: 6
        color: mouse.containsMouse && control.editable
               ? (t.isDark ? Qt.lighter(t.surface, 1.25) : Qt.darker(t.surface, 1.04))
               : t.surface
        border.color: chooser.visible ? t.accent : t.line
        implicitHeight: layout.implicitHeight + 14

        RowLayout {
            id: layout
            anchors.fill: parent
            anchors.margins: 7
            spacing: 8

            PortColourBadge {
                Layout.alignment: Qt.AlignVCenter
                portNumber: control.portNumber
                colourName: control.detail ? control.detail.colour : ""
                colourHex: control.detail ? control.detail.colourHex : ""
                exists: control.detail ? control.detail.exists : false
                editable: false          // set it on the Ports page
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 1

                // Line 1: the name the user chose, or the kernel name when
                // they have not chosen one -- never blank.
                Label {
                    Layout.fillWidth: true
                    text: control.detail ? control.detail.displayName : "no port"
                    color: t.text
                    font.pixelSize: t.fs(12)
                    elide: Text.ElideRight
                }
                // Line 2: what the rest of the system calls it. Suppressed
                // when it is already line 1, rather than printed twice.
                Label {
                    Layout.fillWidth: true
                    visible: control.detail && control.detail.name.length > 0
                    text: control.detail ? control.detail.kernelName : ""
                    color: t.dim
                    font.pixelSize: t.fs(10)
                    elide: Text.ElideRight
                }
                Label {
                    Layout.fillWidth: true
                    visible: control.detail && control.detail.remark.length > 0
                    text: control.detail ? control.detail.remark : ""
                    color: t.dim
                    font.pixelSize: t.fs(10)
                    font.italic: true
                    elide: Text.ElideRight
                }
            }

            Label {
                visible: control.editable
                text: "▾"                 // black down-pointing small triangle
                color: t.dim
                font.pixelSize: t.fs(12)
                Layout.alignment: Qt.AlignVCenter
            }
        }

        MouseArea {
            id: mouse
            anchors.fill: parent
            hoverEnabled: true
            enabled: control.editable
            cursorShape: Qt.PointingHandCursor
            onClicked: chooser.open()
        }
    }

    Popup {
        id: chooser
        objectName: "portChooser"
        y: badge.height + 2
        width: Math.max(control.width, t.fs(260))
        height: Math.min(t.fs(300), control.ports.length * t.fs(46) + 2)
        padding: 1
        modal: false
        focus: true

        background: Rectangle {
            color: t.surface
            border.color: t.accent
            radius: 6
        }

        // Open showing the port that is already selected, centred. Starting
        // at the top would mean scrolling to find where you are every time,
        // which for 32 ports is most of the work of changing one.
        //
        // Positioned twice on purpose: at the moment the popup opens the
        // ListView may not have been laid out yet, and positionViewAtIndex
        // silently does nothing when it has no geometry to work with.
        // Qt.callLater runs the second attempt after that layout pass.
        function centreOnSelection() {
            var i = control.indexOf(control.portNumber)
            if (i < 0)
                return
            list.currentIndex = i
            list.positionViewAtIndex(i, ListView.Center)
        }

        onOpened: {
            centreOnSelection()
            Qt.callLater(centreOnSelection)
        }

        ListView {
            id: list
            objectName: "portChooserList"
            anchors.fill: parent
            clip: true
            model: control.ports
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

            delegate: Rectangle {
                required property var modelData
                required property int index
                width: list.width
                height: rowLayout.implicitHeight + 10
                color: index === list.currentIndex
                       ? Qt.rgba(t.accent.r, t.accent.g, t.accent.b, 0.22)
                       : (rowMouse.containsMouse
                          ? Qt.rgba(t.accent.r, t.accent.g, t.accent.b, 0.10)
                          : "transparent")

                RowLayout {
                    id: rowLayout
                    anchors.fill: parent
                    anchors.leftMargin: 8
                    anchors.rightMargin: 8
                    spacing: 8

                    PortColourBadge {
                        portNumber: modelData.number
                        colourName: modelData.colour
                        colourHex: modelData.colourHex
                        exists: modelData.exists
                        editable: false
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 0
                        Label {
                            Layout.fillWidth: true
                            text: modelData.displayName
                            color: t.text
                            font.pixelSize: t.fs(11)
                            elide: Text.ElideRight
                        }
                        Label {
                            Layout.fillWidth: true
                            visible: modelData.remark.length > 0
                            text: modelData.remark
                            color: t.dim
                            font.pixelSize: t.fs(9)
                            font.italic: true
                            elide: Text.ElideRight
                        }
                    }
                }

                MouseArea {
                    id: rowMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    // Close first, emit second, and read the number before
                    // either. Picking a port retargets the route, which
                    // rebuilds the row this picker lives in -- so by the time
                    // the signal returns, `chooser` and `modelData` have both
                    // been destroyed underneath us.
                    onClicked: {
                        var chosen = modelData.number
                        chooser.close()
                        control.picked(chosen)
                    }
                }
            }
        }
    }
}
