import QtQuick
import QtQuick.Controls
import QtQuick.Window
import QtQuick.Dialogs
import QtQuick.Layouts

ApplicationWindow {
    id: root
    // Seeded from the last session and clamped to the screen, so a size
    // remembered from a bigger monitor cannot open off the edge of this one.
    width: Math.min(bridge.windowWidth, Screen.desktopAvailableWidth - 40)
    height: Math.min(bridge.windowHeight, Screen.desktopAvailableHeight - 80)
    minimumWidth: 640; minimumHeight: 460
    visible: true
    title: bridge.appName

    // Written back after a pause rather than on every pixel of a drag: a
    // resize is hundreds of events and each one would be a file write.
    onWidthChanged: sizeSaver.restart()
    onHeightChanged: sizeSaver.restart()
    Timer {
        id: sizeSaver
        interval: 700
        onTriggered: if (root.visibility !== Window.Minimized)
                         bridge.saveWindowSize(root.width, root.height)
    }

    Theme { id: t }
    color: t.bg
    Behavior on color { ColorAnimation { duration: 160 } }

    // Tabs rather than a single settings flip: this app grows two more pages
    // (routing and mute), and a flip only has two sides.
    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        Rectangle {
            Layout.fillWidth: true
            implicitHeight: header.implicitHeight + 20
            color: t.surface

            RowLayout {
                id: header
                anchors.fill: parent
                anchors.leftMargin: 16
                anchors.rightMargin: 16
                spacing: 14

                Image {
                    // Relative to this .qml file, so it works from a checkout.
                    source: "../resources/lmssdr.png"
                    sourceSize.width: t.fs(24); sourceSize.height: t.fs(24)
                    fillMode: Image.PreserveAspectFit
                    visible: status === Image.Ready
                }

                Label {
                    text: bridge.appName
                    color: t.text
                    font.pixelSize: t.fs(15)
                    font.weight: Font.DemiBold
                }

                Item { Layout.fillWidth: true }

                Repeater {
                    model: ["Ports", "Routing", "Mute", "Settings"]
                    delegate: ActionButton {
                        required property int index
                        required property string modelData
                        text: modelData
                        primary: pages.currentIndex === index
                        onClicked: pages.currentIndex = index
                    }
                }
            }

            Rectangle {
                anchors.bottom: parent.bottom
                width: parent.width; height: 1
                color: t.line
            }
        }

        StackLayout {
            id: pages
            objectName: "pages"          // so tests and screenshots can drive it
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: 0

            PortsPage { }
            RoutingPage { }
            MutePage { }
            SettingsPage { onCopied: toast.show("Commands copied to the clipboard", false) }
        }
    }

    Connections {
        target: bridge
        function onErrorRaised(message) { toast.show(message, true) }
        function onNoticeRaised(message) { toast.show(message, false) }
        function onFoundRoutesOnStart(count) {
            foundRoutes.count = count
            // The window may be hidden to the tray at launch. A modal dialog
            // behind a hidden window is a dialog nobody answers, so show the
            // window first -- this is the one moment the information is
            // still available.
            root.show(); root.raise(); root.requestActivate()
            foundRoutes.open()
        }
    }

    // Shown once, at the only moment the app can still see routes that
    // predate it: nothing saved yet, but connections already exist.
    ThemedDialog {
        id: foundRoutes
        property int count: 0
        width: Math.min(540, root.width - 40)
        title: count + " existing MIDI connection" + (count === 1 ? "" : "s") + " found"
        standardButtons: Dialog.Close
        onClosed: bridge.dismissFoundRoutes(neverAgain.checked)

        contentItem: ColumnLayout {
            spacing: 12

            Label {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                color: t.text
                font.pixelSize: t.fs(12)
                text: "There " + (foundRoutes.count === 1 ? "is" : "are") + " "
                    + foundRoutes.count + " connection"
                    + (foundRoutes.count === 1 ? "" : "s")
                    + " between MIDI Through ports that this application did "
                    + "not make — from aconnect, a patchbay, or an earlier "
                    + "session.\n\nNothing has been changed. But once you "
                    + "save any routing here, startup becomes authoritative "
                    + "and will remove connections it does not know about."
            }

            Label {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                color: t.dim
                font.pixelSize: t.fs(11)
                text: "Save them to a file now and you can look at them later "
                    + "and decide. The file lists the port names as well as "
                    + "the numbers, and can be copied over "
                    + "lmssdr.routing.json to restore them."
            }

            RowLayout {
                spacing: 10
                ActionButton {
                    text: "Save to file…"
                    primary: true
                    onClicked: saveFound.open()
                }
                ActionButton {
                    text: "Adopt into routing"
                    onClicked: { bridge.syncFromKernel(false); foundRoutes.close() }
                }
            }

            ThemedSwitch {
                id: neverAgain
                text: "Do not ask again"
            }
        }
    }

    FileDialog {
        id: saveFound
        title: "Save found MIDI connections"
        fileMode: FileDialog.SaveFile
        defaultSuffix: "json"
        nameFilters: ["JSON files (*.json)", "All files (*)"]
        currentFile: "file://" + bridge.suggestedExportName
        onAccepted: {
            if (bridge.exportFoundRoutes(selectedFile.toString()))
                foundRoutes.close()
        }
    }

    // Closing hides to the tray; quitting is an explicit choice from there.
    onClosing: function (close) {
        close.accepted = false
        root.hide()
    }

    Rectangle {
        id: toast
        anchors.bottom: parent.bottom; anchors.bottomMargin: 20
        anchors.horizontalCenter: parent.horizontalCenter
        radius: 6
        property bool isError: true
        color: isError ? (t.isDark ? "#33191b" : "#fdecec")
                       : (t.isDark ? "#1b2a20" : "#e9f7ee")
        border.color: isError ? t.warn : t.ok
        width: Math.min(root.width - 40, label.implicitWidth + 28)
        height: label.implicitHeight + 18
        opacity: 0
        visible: opacity > 0

        Label {
            id: label
            anchors.centerIn: parent
            width: toast.width - 28
            wrapMode: Text.WordWrap
            horizontalAlignment: Text.AlignHCenter
            color: toast.isError ? t.warn : t.ok
            font.pixelSize: t.fs(12)
        }

        Behavior on opacity { NumberAnimation { duration: 180 } }
        Timer { id: hideTimer; interval: 6000; onTriggered: toast.opacity = 0 }

        function show(message, error) {
            isError = error === undefined ? true : error
            label.text = message
            opacity = 1
            hideTimer.restart()
        }
    }
}
