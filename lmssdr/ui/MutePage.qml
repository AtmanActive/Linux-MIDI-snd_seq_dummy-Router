import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// Mute a microphone from DAW transport messages.
//
// Three choices carry the feature -- which microphone, which port carries
// the transport, which carries talkback -- so they are the page. The message
// numbers are below them, defaulted to Mackie and rarely touched.
Item {
    id: page
    Theme { id: t }

    // Blue while the listener is up but has heard nothing: the same reading
    // as the tray icon, so the page and the icon never disagree.
    readonly property color stateColour:
        bridge.muteState === "muted" ? t.danger
      : bridge.muteState === "talkback" ? "#9b7ede"
      : bridge.muteState === "idle" ? "#5a8dea"
      : t.ok

    ScrollView {
        id: scroll
        objectName: "muteScroll"
        anchors.fill: parent
        contentWidth: availableWidth
        clip: true

        ColumnLayout {
            // availableWidth, not page.width: the latter ignores the space a
            // vertical scrollbar takes, so the content runs under it.
            width: scroll.availableWidth
            spacing: 10

            ColumnLayout {
                Layout.fillWidth: true
                Layout.margins: 16
                spacing: 10

                // ---- the live state, first: it is what you glance at -----
                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: stateRow.implicitHeight + 22
                    radius: 8
                    color: t.surface
                    border.color: bridge.muteEnabled ? page.stateColour : t.line

                    RowLayout {
                        id: stateRow
                        anchors.fill: parent
                        anchors.margins: 12
                        spacing: 12

                        Rectangle {
                            implicitWidth: t.fs(14); implicitHeight: t.fs(14)
                            radius: width / 2
                            color: bridge.muteEnabled ? page.stateColour : t.line
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 2
                            Label {
                                text: !bridge.muteEnabled ? "Off"
                                    : bridge.muteState === "muted" ? "Microphone muted"
                                    : bridge.muteState === "talkback" ? "Talkback — microphone live"
                                    : bridge.muteState === "idle" ? "Waiting for transport"
                                    : "Microphone live"
                                color: t.text
                                font.pixelSize: t.fs(14)
                                font.weight: Font.DemiBold
                            }
                            Label {
                                Layout.fillWidth: true
                                wrapMode: Text.WordWrap
                                color: t.dim
                                font.pixelSize: t.fs(11)
                                text: !bridge.muteEnabled
                                    ? "Enable below to mute on transport play."
                                    : bridge.muteError.length > 0 ? bridge.muteError
                                    : !bridge.muteRunning
                                      ? "Not listening — check the port and microphone."
                                    : bridge.muteState === "idle"
                                      ? "Listening — no transport message heard yet."
                                      : "Listening for transport messages."
                            }
                        }

                        ThemedSwitch {
                            checked: bridge.muteEnabled
                            enabled: bridge.audioAvailable
                            onToggled: bridge.setMuteEnabled(checked)
                        }
                    }
                }

                Label {
                    Layout.fillWidth: true
                    visible: !bridge.audioAvailable
                    wrapMode: Text.WordWrap
                    color: t.warn
                    font.pixelSize: t.fs(11)
                    text: "pactl was not found, so this feature cannot control "
                        + "any audio device. On Debian it is in pulseaudio-utils."
                }

                SectionLabel { text: "Microphone" }

                ThemedComboBox {
                    Layout.fillWidth: true
                    Layout.maximumWidth: t.fs(420)
                    enabled: bridge.audioAvailable
                    model: bridge.audioSources
                    textRole: "description"
                    valueRole: "name"
                    currentIndex: {
                        for (var i = 0; i < model.length; i++)
                            if (model[i].name === bridge.muteSource) return i
                        return -1
                    }
                    displayText: currentIndex >= 0 ? currentText
                                                   : "Choose a microphone…"
                    onActivated: bridge.setMuteSource(currentValue)
                }

                // With the default chosen, the setting reads "<default>" and
                // the device it resolved to is what the user needs to see.
                Label {
                    Layout.fillWidth: true
                    visible: bridge.muteSourceIsDefault
                    wrapMode: Text.WordWrap
                    color: t.dim
                    font.pixelSize: t.fs(11)
                    text: "Follows the desktop's default input, looked up when "
                        + "the application starts or when this feature is "
                        + "switched on. Right now that is: "
                        + (bridge.muteSourceLabel || "nothing")
                }

                SectionLabel { text: "Transport port" }

                Label {
                    Layout.fillWidth: true
                    wrapMode: Text.WordWrap
                    color: t.dim
                    font.pixelSize: t.fs(11)
                    text: "The MIDI Through port your DAW sends Mackie "
                        + "transport to. Play mutes the microphone, Stop "
                        + "unmutes it."
                }

                PortComboBox {
                    Layout.fillWidth: true
                    Layout.maximumWidth: t.fs(420)
                    ports: bridge.routablePorts
                    portNumber: bridge.muteTransportPort
                    onPicked: function (n) { bridge.setMuteTransportPort(n) }
                }

                SectionLabel { text: "Talkback port" }

                Label {
                    Layout.fillWidth: true
                    wrapMode: Text.WordWrap
                    color: t.dim
                    font.pixelSize: t.fs(11)
                    text: "Optional, and it may be the same port. Holding the "
                        + "talkback control opens the microphone while the "
                        + "transport is playing; releasing it mutes again. "
                        + "It does nothing while stopped."
                }

                PortComboBox {
                    Layout.fillWidth: true
                    Layout.maximumWidth: t.fs(420)
                    ports: bridge.routablePorts
                    portNumber: bridge.muteTalkbackPort
                    allowNone: true
                    onPicked: function (n) { bridge.setMuteTalkbackPort(n) }
                }

                Rectangle { Layout.fillWidth: true; height: 1; color: t.line
                            Layout.topMargin: 8 }

                Rectangle { Layout.fillWidth: true; height: 1; color: t.line
                            Layout.topMargin: 8 }

                SectionLabel { text: "Messages" }

                Label {
                    Layout.fillWidth: true
                    wrapMode: Text.WordWrap
                    color: t.dim
                    font.pixelSize: t.fs(11)
                    text: "Mackie Control defaults. Change these only if your "
                        + "DAW sends something else."
                }

                GridLayout {
                    // Two label-and-field pairs per row. Four fits only on a
                    // very wide window and silently runs off the edge below
                    // that.
                    columns: 2
                    columnSpacing: 10
                    rowSpacing: 6

                    Repeater {
                        model: [
                            { key: "transportChannel", label: "Transport channel", from: 1, to: 16 },
                            { key: "velocity",         label: "Velocity",          from: 1, to: 127 },
                            { key: "playNote",         label: "Play note",         from: 0, to: 127 },
                            { key: "stopNote",         label: "Stop note",         from: 0, to: 127 },
                            { key: "talkbackChannel",  label: "Talkback channel",  from: 1, to: 16 },
                            { key: "talkbackCc",       label: "Talkback CC",       from: 0, to: 127 }
                        ]
                        delegate: RowLayout {
                            required property var modelData
                            spacing: 6
                            Label {
                                text: modelData.label
                                color: t.text
                                font.pixelSize: t.fs(11)
                                Layout.preferredWidth: t.fs(120)
                            }
                            SpinBox {
                                from: modelData.from
                                to: modelData.to
                                value: bridge.muteRuleValues[modelData.key]
                                editable: true
                                font.pixelSize: t.fs(11)
                                Layout.preferredWidth: t.fs(110)
                                onValueModified: bridge.setMuteRule(modelData.key, value)
                            }
                        }
                    }
                }

                Rectangle { Layout.fillWidth: true; height: 1; color: t.line
                            Layout.topMargin: 8 }

                SectionLabel { text: "Test" }

                Label {
                    Layout.fillWidth: true
                    wrapMode: Text.WordWrap
                    color: t.dim
                    font.pixelSize: t.fs(11)
                    text: bridge.muteRunning
                        ? "These send the real message to the port above, so "
                          + "they exercise the whole path — not just the rule."
                        : "Switch the feature on to test: these send real MIDI, "
                          + "and with nothing listening they do nothing."
                }

                GridLayout {
                    columns: 2
                    columnSpacing: 8
                    rowSpacing: 6

                    ActionButton {
                        text: "Test Transport Play (Mute)"
                        enabled: bridge.muteRunning
                        implicitWidth: Math.max(250, t.fs(260))
                        onClicked: bridge.sendMuteTest("play")
                    }
                    ActionButton {
                        text: "Test Transport Stop (Unmute)"
                        enabled: bridge.muteRunning
                        implicitWidth: Math.max(250, t.fs(260))
                        onClicked: bridge.sendMuteTest("stop")
                    }
                    ActionButton {
                        text: "Test Talkback Engage (Unmute in Play)"
                        enabled: bridge.muteRunning && bridge.muteTalkbackPort >= 0
                        implicitWidth: Math.max(250, t.fs(260))
                        onClicked: bridge.sendMuteTest("talkback_on")
                    }
                    ActionButton {
                        text: "Test Talkback Disengage (Mute in Play)"
                        enabled: bridge.muteRunning && bridge.muteTalkbackPort >= 0
                        implicitWidth: Math.max(250, t.fs(260))
                        onClicked: bridge.sendMuteTest("talkback_off")
                    }
                }

                Item { Layout.preferredHeight: 10 }
            }
        }
    }
}
