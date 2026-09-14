import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// The port list: every snd_seq_dummy port, with the name and remark the user
// has given it.
//
// Both names are always on screen together. The custom name is what the user
// thinks in; the kernel name is what every other application on the system
// will show them, and hiding it would make this app a place where ports have
// names nobody else can see.
Item {
    id: page
    objectName: "portsPage"
    Theme { id: t }

    // Swap is a two-click gesture: arm it, click the port to move, click the
    // port to move it to. Modal, so it says so loudly -- every pickable
    // badge blinks in step, driven by one animation rather than 32.
    property bool swapMode: false
    property int swapSource: -1
    property real blinkOpacity: 1

    // A Timer flipping the value, not an animation interpolating it: a blink
    // should be on or off, and a fade reads as a pulse or a glow instead.
    // Nothing binds to blinkOpacity through a Behavior, so the change lands
    // in one frame.
    Timer {
        running: page.swapMode
        interval: 420
        repeat: true
        onTriggered: page.blinkOpacity = page.blinkOpacity < 1 ? 1.0 : 0.2
        onRunningChanged: if (!running) page.blinkOpacity = 1
    }

    function cancelSwap() {
        page.swapMode = false
        page.swapSource = -1
    }

    function pickForSwap(number) {
        if (page.swapSource < 0) {
            page.swapSource = number          // first click: the source
        } else if (page.swapSource === number) {
            page.swapSource = -1              // clicked it again: unchoose
        } else {
            bridge.swapPorts(page.swapSource, number)
            page.cancelSwap()
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 16
        spacing: 10

        RowLayout {
            Layout.fillWidth: true
            spacing: 10

            Label {
                text: bridge.livePortCount + " port"
                      + (bridge.livePortCount === 1 ? "" : "s") + " available"
                color: t.text
                font.pixelSize: t.fs(13)
                font.weight: Font.DemiBold
            }

            Label {
                visible: bridge.portsFilter.length > 0
                text: "· showing " + repeater.count + " of " + bridge.totalPortRowCount
                color: t.accent
                font.pixelSize: t.fs(11)
            }

            FilterField {
                label: "Filter by alias, name or remark"
                Layout.preferredWidth: Math.max(240, t.fs(280))
                text: bridge.portsFilter
                onTextChanged: bridge.setPortsFilter(text)
            }

            ActionButton {
                text: "Swap"
                primary: page.swapMode
                enabled: bridge.livePortCount >= 2
                // Blinks in step with the badges, so the button and the
                // things it is waiting on read as one state.
                opacity: page.swapMode ? page.blinkOpacity : 1
                onClicked: page.swapMode ? page.cancelSwap()
                                         : page.swapMode = true
            }

            // Beside the button rather than on its own line: adding a row
            // when swap starts shifts the whole port list down, and the list
            // moving under the pointer is exactly what this mode must not do.
            Label {
                visible: page.swapMode
                Layout.fillWidth: true
                elide: Text.ElideRight
                color: t.accent
                font.pixelSize: t.fs(11)
                text: page.swapSource < 0
                    ? "Click the port to move — its name, remark, colour and "
                      + "routing will change places with the one you pick next"
                    : "Now click the port to swap with " + page.swapSource
                      + " — or click " + page.swapSource + " again to change it"
            }

            Item { Layout.fillWidth: true; visible: !page.swapMode }

            // Hidden while swapping so the instruction has the whole width;
            // the port count is not what the user is reading at that moment.
            Label {
                visible: !page.swapMode
                text: bridge.moduleSummary
                color: t.dim
                font.pixelSize: t.fs(11)
            }
        }

        // Shown when the kernel is not providing what the settings ask for.
        // Actionable rather than decorative: it says what to do about it.
        Rectangle {
            Layout.fillWidth: true
            visible: !bridge.moduleMatches
            implicitHeight: mismatch.implicitHeight + 20
            radius: 6
            color: t.isDark ? "#332a1b" : "#fff6e6"
            border.color: t.warn

            Label {
                id: mismatch
                anchors.fill: parent
                anchors.margins: 10
                wrapMode: Text.WordWrap
                color: t.warn
                font.pixelSize: t.fs(11)
                text: bridge.moduleDuplex
                    ? "The kernel module is loaded in duplex mode, which this "
                      + "application does not use. Apply the port count in "
                      + "Settings to reload it correctly."
                    : "The kernel is providing " + bridge.livePortCount
                      + " port(s) but the settings ask for " + bridge.portCount
                      + ". Apply the port count in Settings."
            }
        }

        Rectangle {
            id: panel
            Layout.fillWidth: true
            Layout.fillHeight: true
            color: t.surface
            border.color: t.line
            radius: 8

            // Newspaper columns: ports run down a column, then continue at
            // the top of the next one. A single tall list wastes the width of
            // a window sized for the routing matrix, and makes finding port
            // 25 a scroll rather than a glance.
            //
            // The cards are a fixed height so the column arithmetic below is
            // exact rather than a guess about wrapped text.
            readonly property int minCardWidth: Math.max(240, t.fs(260))
            readonly property int cardHeight: Math.max(76, t.fs(84))
            readonly property int gap: 6

            readonly property int rowsPerColumn:
                Math.max(1, Math.floor((flick.height + gap) / (cardHeight + gap)))
            readonly property int columnCount:
                Math.max(1, Math.ceil(portFlow.itemCount / rowsPerColumn))

            // Stretch the cards to fill the width when every column fits, and
            // fall back to the minimum (with a horizontal scroll) when they
            // do not. Ragged empty space on the right looks like a bug.
            readonly property int cardWidth: {
                var available = flick.width - (columnCount - 1) * gap
                var fitted = Math.floor(available / columnCount)
                return fitted >= minCardWidth ? fitted : minCardWidth
            }

            Flickable {
                id: flick
                objectName: "portFlick"
                anchors.fill: parent
                anchors.margins: 8
                clip: true
                contentWidth: portFlow.width
                contentHeight: height              // never scrolls vertically
                flickableDirection: Flickable.HorizontalFlick
                boundsBehavior: Flickable.StopAtBounds

                readonly property bool overflowing: contentWidth > width + 1
                readonly property real maxContentX: Math.max(0, contentWidth - width)

                // Always on when there is more to see. AsNeeded renders a bar
                // so faint that the columns look like all there is, which is
                // indistinguishable from the list simply being cut off.
                ScrollBar.horizontal: ScrollBar {
                    policy: flick.overflowing ? ScrollBar.AlwaysOn
                                              : ScrollBar.AlwaysOff
                }

                // The content only moves sideways, and a vertical wheel is
                // the only wheel most mice have -- so map one onto the other.
                // Without this the panel is scrollable in principle and inert
                // in practice: spinning the wheel does nothing at all.
                WheelHandler {
                    acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
                    onWheel: function (event) {
                        var delta = event.angleDelta.y !== 0 ? event.angleDelta.y
                                                             : event.angleDelta.x
                        flick.contentX = Math.max(
                            0, Math.min(flick.maxContentX, flick.contentX - delta))
                    }
                }

                Flow {
                    id: portFlow
                objectName: "portFlow"
                    height: flick.height
                    flow: Flow.TopToBottom
                    spacing: panel.gap
                    property int itemCount: repeater.count

                    Repeater {
                        id: repeater
                        // Still the QAbstractListModel, so renaming a port
                        // updates one card instead of rebuilding every one
                        // and throwing away the scroll position.
                        model: bridge.portsModel

                        delegate: Rectangle {
                            id: card
                            required property int index
                            required property int number
                            required property string kernelName
                            required property string name
                            required property string remark
                            required property string colour
                            required property string colourHex
                            required property bool exists

                            width: panel.cardWidth
                            height: panel.cardHeight
                            radius: 6
                            color: t.isDark ? Qt.lighter(t.surface, 1.08)
                                            : Qt.darker(t.surface, 1.02)
                            border.color: t.line

                            RowLayout {
                                anchors.fill: parent
                                anchors.margins: 7
                                spacing: 8

                                // Click to tag the port with a colour; the
                                // tag then shows on every screen.
                                PortColourBadge {
                                    Layout.alignment: Qt.AlignVCenter
                                    // Qualified with the delegate's id: the
                                    // badge has properties of the same names,
                                    // so bare `colourHex` would bind to
                                    // itself.
                                    portNumber: card.number
                                    colourName: card.colour
                                    colourHex: card.colourHex
                                    exists: card.exists

                                    // The already-chosen source stops
                                    // blinking, so the two clicks of a swap
                                    // are visibly different steps.
                                    selecting: page.swapMode && card.exists
                                               && card.number !== page.swapSource
                                    blinkOpacity: page.blinkOpacity
                                    editable: !page.swapMode
                                    onSelected: page.pickForSwap(card.number)
                                }

                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 0

                                    TextField {
                                        Layout.fillWidth: true
                                        text: name
                                        placeholderText: "Custom name"
                                        color: t.text
                                        placeholderTextColor: t.dim
                                        font.pixelSize: t.fs(12)
                                        font.weight: Font.DemiBold
                                        enabled: exists
                                        padding: 2
                                        background: Rectangle {
                                            color: "transparent"
                                            border.color: parent.activeFocus ? t.accent : "transparent"
                                            radius: 3
                                        }
                                        // Commit on focus loss as well as
                                        // Enter: someone who types a name and
                                        // clicks the next field has decided.
                                        onEditingFinished: bridge.setPortName(number, text)
                                    }

                                    // Order is alias, kernel name, remark:
                                    // identity first, then the annotation.
                                    Label {
                                        Layout.fillWidth: true
                                        text: kernelName
                                              + (exists ? "" : "   \u2014 not present")
                                        color: exists ? t.dim : t.warn
                                        font.pixelSize: t.fs(9)
                                        leftPadding: 2
                                        elide: Text.ElideRight
                                    }

                                    TextField {
                                        Layout.fillWidth: true
                                        text: remark
                                        id: remarkField
                                        placeholderText: "Remark"
                                        color: remarkField.text.length > 0 ? t.text : t.dim
                                        placeholderTextColor: t.dim
                                        font.pixelSize: t.fs(10)
                                        font.italic: true
                                        enabled: exists
                                        padding: 2
                                        background: Rectangle {
                                            color: "transparent"
                                            border.color: parent.activeFocus ? t.accent : "transparent"
                                            radius: 3
                                        }
                                        onEditingFinished: bridge.setPortRemark(number, text)
                                    }

                                }
                            }
                        }
                    }
                }
            }

            Label {
                anchors.centerIn: parent
                visible: repeater.count === 0
                width: parent.width - 60
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                color: t.dim
                font.pixelSize: t.fs(12)
                text: bridge.sequencerError.length > 0
                    ? bridge.sequencerError
                    : bridge.portsFilter.length > 0
                    ? "No ports match the filter. Searching covers the custom "
                      + "name, the kernel name and the remark."
                    : "No MIDI Through ports. Set a port count in Settings and apply it."
            }
        }
    }
}
