import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts

Item {
    id: page
    Theme { id: t }

    ScrollView {
        anchors.fill: parent
        contentWidth: availableWidth
        clip: true

        ColumnLayout {
            width: page.width
            spacing: 8

            ColumnLayout {
                Layout.fillWidth: true
                Layout.margins: 16
                spacing: 8

                SectionLabel { text: "MIDI ports" }

                Label {
                    Layout.fillWidth: true
                    wrapMode: Text.WordWrap
                    color: t.dim
                    font.pixelSize: t.fs(11)
                    text: "Changing this reloads the snd_seq_dummy kernel "
                        + "module, which needs your password. Every existing "
                        + "MIDI connection in the system is dropped, and "
                        + "browsers must be restarted before they will see "
                        + "the new ports."
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 12

                    Label {
                        text: "Number of ports"
                        color: t.text
                        font.pixelSize: t.fs(12)
                    }

                    SpinBox {
                        id: portSpin
                        from: 1
                        to: bridge.maxPorts
                        value: bridge.portCount
                        editable: true
                        enabled: !bridge.busy
                        font.pixelSize: t.fs(12)
                        onValueModified: bridge.setPortCount(value)
                        // Keep in step when something else changes it.
                        Connections {
                            target: bridge
                            function onSettingsChanged() {
                                if (portSpin.value !== bridge.portCount)
                                    portSpin.value = bridge.portCount
                            }
                        }
                    }

                    ActionButton {
                        text: bridge.busy ? "Applying…" : "Apply"
                        primary: true
                        enabled: !bridge.busy && !bridge.moduleMatches
                        onClicked: bridge.applyPortCount()
                    }

                    Item { Layout.fillWidth: true }
                }

                Label {
                    Layout.fillWidth: true
                    color: bridge.moduleMatches ? t.ok : t.warn
                    font.pixelSize: t.fs(11)
                    text: bridge.moduleMatches
                        ? "Kernel matches: " + bridge.moduleSummary
                        : "Kernel: " + bridge.moduleSummary + " — not what the setting asks for"
                }

                // A leftover file in /etc/modprobe.d can silently win at the
                // next boot, so say so rather than letting the user wonder.
                Rectangle {
                    Layout.fillWidth: true
                    visible: bridge.conflictingConfigs.length > 0
                    implicitHeight: conflictText.implicitHeight + 20
                    radius: 6
                    color: t.isDark ? "#332a1b" : "#fff6e6"
                    border.color: t.warn
                    Label {
                        id: conflictText
                        anchors.fill: parent
                        anchors.margins: 10
                        wrapMode: Text.WordWrap
                        color: t.warn
                        font.pixelSize: t.fs(11)
                        text: "Another file also configures this module and may "
                            + "override the port count at the next boot:\n"
                            + bridge.conflictingConfigs.join("\n")
                    }
                }

                ActionButton {
                    text: "Copy manual commands"
                    onClicked: {
                        bridge.copyToClipboard(bridge.manualCommand)
                        page.copied()
                    }
                }

                Rectangle { Layout.fillWidth: true; height: 1; color: t.line
                            Layout.topMargin: 8 }

                SectionLabel { text: "Startup" }

                ThemedSwitch {
                    text: "Start automatically at login"
                    checked: bridge.autostart
                    onToggled: bridge.setAutostart(checked)
                }

                ThemedSwitch {
                    text: "Start minimised to the tray"
                    checked: bridge.startMinimised
                    onToggled: bridge.setStartMinimised(checked)
                }

                Rectangle { Layout.fillWidth: true; height: 1; color: t.line
                            Layout.topMargin: 8 }

                SectionLabel { text: "Appearance" }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 12
                    Label { text: "Mode"; color: t.text; font.pixelSize: t.fs(12)
                            Layout.preferredWidth: t.fs(70) }
                    ComboBox {
                        Layout.preferredWidth: t.fs(150)
                        model: ["system", "light", "dark"]
                        currentIndex: model.indexOf(bridge.themeMode)
                        font.pixelSize: t.fs(12)
                        onActivated: bridge.setThemeMode(currentValue)
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 12
                    Label { text: "Colour"; color: t.text; font.pixelSize: t.fs(12)
                            Layout.preferredWidth: t.fs(70) }
                    ComboBox {
                        Layout.preferredWidth: t.fs(150)
                        model: bridge.themeNames
                        currentIndex: model.indexOf(bridge.themeName)
                        font.pixelSize: t.fs(12)
                        onActivated: bridge.setThemeName(currentValue)
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 12
                    Label { text: "Text size"; color: t.text; font.pixelSize: t.fs(12)
                            Layout.preferredWidth: t.fs(70) }
                    ComboBox {
                        Layout.preferredWidth: t.fs(150)
                        model: bridge.textSizeNames
                        currentIndex: model.indexOf(bridge.textSize)
                        font.pixelSize: t.fs(12)
                        onActivated: bridge.setTextSize(currentValue)
                    }
                }

                Rectangle { Layout.fillWidth: true; height: 1; color: t.line
                            Layout.topMargin: 8 }

                SectionLabel { text: "Backup" }

                Label {
                    Layout.fillWidth: true
                    wrapMode: Text.WordWrap
                    color: t.dim
                    font.pixelSize: t.fs(11)
                    text: "Export writes everything this application has "
                        + "saved — settings, port names and routing — into "
                        + "one ZIP file. Import reads one back, and lets you "
                        + "choose which parts to take."
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 10

                    ActionButton {
                        text: "Export…"
                        onClicked: exportDialog.open()
                    }
                    ActionButton {
                        text: "Import…"
                        onClicked: importDialog.open()
                    }
                    Item { Layout.fillWidth: true }
                }

                Label {
                    Layout.fillWidth: true
                    wrapMode: Text.WordWrap
                    color: t.dim
                    font.pixelSize: t.fs(11)
                    text: bridge.exportableFiles.length > 0
                        ? "Will export: " + bridge.exportableFiles.join(", ")
                        : "Nothing has been saved yet, so there is nothing to export."
                }

                Rectangle { Layout.fillWidth: true; height: 1; color: t.line
                            Layout.topMargin: 8 }

                SectionLabel { text: "About" }

                Label {
                    text: bridge.appName + " " + bridge.appVersion
                    color: t.dim
                    font.pixelSize: t.fs(11)
                }
                Label {
                    text: bridge.homepage
                    color: t.accent
                    font.pixelSize: t.fs(11)
                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: bridge.openHomepage()
                    }
                }
                Item { Layout.preferredHeight: 8 }
            }
        }
    }

    // -- backup and restore ----------------------------------------------

    FileDialog {
        id: exportDialog
        title: "Export " + bridge.appName + " data"
        fileMode: FileDialog.SaveFile
        defaultSuffix: "zip"
        nameFilters: ["ZIP archives (*.zip)", "All files (*)"]
        // An absolute URL, so the dialog opens in a known folder with the
        // filename already filled in and only the folder left to choose.
        currentFolder: bridge.suggestedArchiveUrl.replace(/\/[^\/]*$/, "")
        selectedFile: bridge.suggestedArchiveUrl
        onAccepted: bridge.exportArchive(selectedFile.toString())
    }

    FileDialog {
        id: importDialog
        title: "Import " + bridge.appName + " data"
        fileMode: FileDialog.OpenFile
        nameFilters: ["ZIP archives (*.zip)", "All files (*)"]
        onAccepted: bridge.openArchive(selectedFile.toString())
    }

    Connections {
        target: bridge
        function onArchiveRejected(message) {
            // Whatever was on offer is gone; a picker still showing it would
            // be describing a file the application is no longer holding.
            importPicker.close()
            importError.message = message
            importError.open()
        }
        function onArchiveOpened(count) {
            // Built whole and assigned once: mutating the object in place
            // changes nothing QML can see, so the checkboxes would open
            // unticked however carefully the keys were set.
            var next = {}
            for (var i = 0; i < bridge.archiveItems.length; i++)
                next[bridge.archiveItems[i].key] = true
            importPicker.selected = next
            importPicker.open()
        }
    }

    ThemedDialog {
        id: importError
        property string message: ""
        title: "Nothing to import"
        width: Math.min(520, page.width - 40)

        contentItem: ColumnLayout {
            spacing: 16
            Label {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                color: t.text
                font.pixelSize: t.fs(12)
                text: importError.message
            }
            ActionButton {
                Layout.alignment: Qt.AlignRight
                text: "Close"
                primary: true
                onClicked: importError.close()
            }
        }
    }

    ThemedDialog {
        id: importPicker
        title: "Import from " + bridge.archiveName
        width: Math.min(560, page.width - 40)

        // key -> bool. A plain object rather than a model: the set is three
        // items at most, and the dialog is the only thing that reads it.
        property var selected: ({})
        readonly property int chosenCount: {
            var n = 0
            for (var k in selected) if (selected[k]) n++
            return n
        }
        readonly property bool allChosen:
            chosenCount === bridge.archiveItems.length && chosenCount > 0

        function setChosen(key, on) {
            var next = {}
            for (var k in selected) next[k] = selected[k]
            next[key] = on
            selected = next
        }

        contentItem: ColumnLayout {
            spacing: 12

            Label {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                color: t.text
                font.pixelSize: t.fs(12)
                text: "This archive holds the following. Choose what to "
                    + "import — each one replaces what you have now."
            }

            ThemedCheckBox {
                text: "All"
                checked: importPicker.allChosen
                partial: importPicker.chosenCount > 0 && !importPicker.allChosen
                font.weight: Font.DemiBold
                onToggled: {
                    var next = {}
                    for (var i = 0; i < bridge.archiveItems.length; i++)
                        next[bridge.archiveItems[i].key] = checked
                    importPicker.selected = next
                }
            }

            Rectangle { Layout.fillWidth: true; height: 1; color: t.line }

            Repeater {
                model: bridge.archiveItems
                delegate: ColumnLayout {
                    required property var modelData
                    Layout.fillWidth: true
                    spacing: 0

                    ThemedCheckBox {
                        text: modelData.label
                        checked: importPicker.selected[modelData.key] === true
                        onToggled: importPicker.setChosen(modelData.key, checked)
                    }
                    Label {
                        Layout.fillWidth: true
                        Layout.leftMargin: t.fs(26)
                        wrapMode: Text.WordWrap
                        color: t.dim
                        font.pixelSize: t.fs(11)
                        text: modelData.summary + " — " + modelData.describe
                    }
                }
            }

            Rectangle { Layout.fillWidth: true; height: 1; color: t.line }

            Label {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                color: t.warn
                font.pixelSize: t.fs(11)
                text: "Importing routing re-applies it to the kernel and "
                    + "removes connections it does not contain. The files "
                    + "being replaced are kept alongside as .pre-import."
            }

            RowLayout {
                Layout.alignment: Qt.AlignRight
                spacing: 10
                ActionButton {
                    text: "Cancel"
                    onClicked: importPicker.close()
                }
                ActionButton {
                    text: importPicker.allChosen ? "Import all"
                        : "Import " + importPicker.chosenCount + " item"
                          + (importPicker.chosenCount === 1 ? "" : "s")
                    primary: true
                    enabled: importPicker.chosenCount > 0
                    onClicked: {
                        var keys = []
                        for (var k in importPicker.selected)
                            if (importPicker.selected[k]) keys.push(k)
                        importPicker.close()
                        bridge.importArchive(keys)
                    }
                }
            }
        }
    }

    signal copied()
}
