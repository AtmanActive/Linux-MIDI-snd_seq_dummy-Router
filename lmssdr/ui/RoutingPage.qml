import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// Routing: a matrix to assign it, a graph to see it.
//
// The matrix is the editor because routing is a relation, and a grid is the
// only layout where every possible pair is one click away and the absence of
// a connection is as visible as its presence. The graph is the read-only
// view, because that is the shape the question "where does port 3 go?" has.
Item {
    id: page
    Theme { id: t }

    property int cell: Math.max(20, t.fs(22))
    property int rowHeaderWidth: Math.max(150, t.fs(170))
    property int selected: -1          // graph node index under the pointer
    property int hoverRow: -1         // matrix crosshair
    property int hoverCol: -1

    // The route just added, as "source->dest", so its row can announce
    // itself. Cleared on a timer: a highlight that never fades stops being
    // a highlight and becomes a state.
    property string flashRoute: ""

    Connections {
        target: bridge
        function onRouteAdded(source, dest) {
            page.flashRoute = source + "->" + dest
            flashClear.restart()
            // Adding appends, so the new row is at the end -- and off screen
            // once there are more routes than fit.
            routeList.positionViewAtEnd()
        }
    }

    Timer { id: flashClear; interval: 1400; onTriggered: page.flashRoute = "" }

    // Rows and columns are filtered independently. One filter across both
    // axes could never show a route from a port in one group to a port in
    // another, which is most of what routing is for.
    readonly property var sources: bridge.sourcePorts
    readonly property var dests: bridge.destPorts
    readonly property var nodes: bridge.graphPorts
    readonly property var grid: bridge.matrix

    function sourceAt(i) { return sources[i] }
    function destAt(i) { return dests[i] }

    // The matrix and the two axis lists are three separate properties that
    // update in sequence, so for one frame a row can be longer than the
    // column list. Guarded lookups keep that frame silent rather than
    // spraying TypeErrors.
    function sourceNumberAt(i) { var p = sources[i]; return p ? p.number : -1 }
    function destNumberAt(i)   { var p = dests[i];   return p ? p.number : -1 }
    function sourceNameAt(i)   { var p = sources[i]; return p ? p.displayName : "" }
    function destNameAt(i)     { var p = dests[i];   return p ? p.displayName : "" }

    // "001: Alias (remark)" -- everything known about a port on one line.
    //
    // Shared by the matrix crosshair and the graph, so hovering the same
    // port in two views says the same thing. The number is padded to three
    // digits as it is everywhere else in the app, which also keeps the
    // readout from shifting sideways as the pointer moves between ports.
    //
    // The kernel name is not repeated here: at 254 ports it is always
    // "Midi Through Port-N", which the number has already said.
    function describePort(p) {
        if (!p) return ""
        var text = ("00" + p.number).slice(-3) + ": " + p.displayName
        return (p.remark && p.remark.length > 0)
            ? text + " (" + p.remark + ")" : text
    }
    function sourceDescAt(i) { return describePort(sources[i]) }
    function destDescAt(i)   { return describePort(dests[i]) }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 16
        spacing: 10

        // ---- toolbar ---------------------------------------------------
        RowLayout {
            Layout.fillWidth: true
            spacing: 10

            Label {
                text: bridge.savedLinkCount + " saved route"
                      + (bridge.savedLinkCount === 1 ? "" : "s")
                color: t.text
                font.pixelSize: t.fs(13)
                font.weight: Font.DemiBold
            }

            Label {
                visible: bridge.unmanagedLinkCount > 0
                text: "· " + bridge.unmanagedLinkCount + " not saved"
                color: t.warn
                font.pixelSize: t.fs(11)
            }

            // What the filter is currently hiding, counted in the units the
            // view in front of you actually has: the matrix is a grid of
            // ports, the other two are lists of routes.
            Label {
                visible: bridge.filtersActive
                text: views.currentIndex === 1
                    ? "· showing " + page.sources.length + "×" + page.dests.length
                      + " of " + bridge.totalRoutablePortCount + " ports"
                    : "· showing " + bridge.routeRows.length + " of "
                      + bridge.totalRouteCount + " routes"
                color: t.accent
                font.pixelSize: t.fs(11)
            }

            Item { Layout.fillWidth: true }

            ActionButton {
                text: "List Edit"
                primary: views.currentIndex === 0
                onClicked: views.currentIndex = 0
            }
            ActionButton {
                text: "Matrix Edit"
                primary: views.currentIndex === 1
                onClicked: views.currentIndex = 1
            }
            ActionButton {
                text: "Graph View"
                primary: views.currentIndex === 2
                onClicked: views.currentIndex = 2
            }
            ActionButton {
                text: "Apply to Kernel"
                // Only stops to ask when it would actually remove something.
                // Confirming a no-op teaches people to dismiss dialogs.
                onClicked: bridge.unmanagedLinkCount > 0
                           ? applyDialog.open() : bridge.applySavedRouting()
            }
            ActionButton {
                text: "Sync from Kernel"
                onClicked: { pullForget.checked = false; pullDialog.open() }
            }
        }

        // Filters sit on their own row rather than in the toolbar: two
        // search boxes and four buttons do not fit one line at the smaller
        // window sizes, and the labels need room to say which axis they act
        // on.
        RowLayout {
            Layout.fillWidth: true
            // On every view, not just the matrix. The three views show the
            // same routing in three shapes, so a filter that applied to only
            // one of them would mean switching view silently changed what
            // you were looking at.
            visible: bridge.totalRoutablePortCount > 0
            spacing: 8

            // "Rows" and "Columns" name where the matrix puts each end. The
            // list and the graph have neither, so there they are just the
            // two ends of a route.
            Label {
                text: views.currentIndex === 1 ? "Rows (from)" : "From"
                color: t.dim
                font.pixelSize: t.fs(11)
            }
            FilterField {
                label: "alias, name or remark"
                Layout.fillWidth: true
                Layout.maximumWidth: page.width * 0.34
                text: bridge.filterFrom
                onTextChanged: bridge.setFilterFrom(text)
            }

            Label {
                text: views.currentIndex === 1 ? "Columns (to)" : "To"
                color: t.dim
                font.pixelSize: t.fs(11)
                leftPadding: t.fs(6)
            }
            FilterField {
                label: "alias, name or remark"
                Layout.fillWidth: true
                Layout.maximumWidth: page.width * 0.34
                text: bridge.filterTo
                onTextChanged: bridge.setFilterTo(text)
            }

            ActionButton {
                text: "Clear"
                visible: bridge.filtersActive
                onClicked: { bridge.setFilterFrom(""); bridge.setFilterTo("") }
            }

            Item { Layout.fillWidth: true }
        }

        Label {
            Layout.fillWidth: true
            visible: bridge.totalRoutablePortCount === 0
                     || (views.currentIndex === 1
                         && (page.sources.length === 0 || page.dests.length === 0))
                     || (views.currentIndex === 2 && page.nodes.length === 0)
            wrapMode: Text.WordWrap
            color: t.dim
            font.pixelSize: t.fs(12)
            text: bridge.totalRoutablePortCount === 0
                ? "No ports to route. Set a port count in Settings and apply it."
                // The graph draws routes, so an empty graph means no route
                // survived -- not that no port matched. Saying "no ports"
                // there would send you looking for the wrong mistake.
                : views.currentIndex === 2
                  ? "No routes match the filter. The graph shows only the "
                    + "ports that the surviving routes connect."
                  : "No ports match the filter. Searching covers the custom "
                    + "name, the kernel name and the remark."
        }

        StackLayout {
            id: views
            objectName: "views"
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: bridge.totalRoutablePortCount > 0
            currentIndex: 0

            // ---- list ---------------------------------------------------
            // One row per route, source on the left. Each end shows the port
            // in full and opens a chooser; the pairing is one to one, so a
            // row is a route rather than a fan-out.
            Rectangle {
                color: t.surface
                border.color: t.line
                radius: 8

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 10
                    spacing: 8

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 8
                        ActionButton {
                            text: "Add"
                            primary: true
                            enabled: bridge.totalRoutablePortCount >= 2
                            onClicked: bridge.addRoute()
                        }
                        Label {
                            visible: bridge.totalRoutablePortCount < 2
                            text: "At least two ports are needed to make a route."
                            color: t.dim
                            font.pixelSize: t.fs(11)
                        }
                        Item { Layout.fillWidth: true }

                        // Right-hand side: these reorder the saved file, so
                        // they sit away from Add rather than beside it.
                        ActionButton {
                            text: "Sort by Source"
                            enabled: bridge.savedLinkCount > 1
                            onClicked: bridge.sortRouting(true)
                        }
                        ActionButton {
                            text: "Sort by Destination"
                            enabled: bridge.savedLinkCount > 1
                            onClicked: bridge.sortRouting(false)
                        }
                    }

                    Label {
                        Layout.fillWidth: true
                        visible: routeList.count === 0
                        text: bridge.filtersActive
                            ? "No routes match the filter."
                            : "No routes yet. Add one, or connect ports in the matrix."
                        color: t.dim
                        font.pixelSize: t.fs(12)
                        topPadding: 8
                    }

                    ListView {
                        id: routeList
                        objectName: "routeList"
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        spacing: 6
                        model: bridge.routeRows
                        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                        delegate: Rectangle {
                            id: routeDelegate
                            required property var modelData
                            width: routeList.width
                            height: routeRow.implicitHeight + 12
                            radius: 6

                            readonly property bool flashing:
                                page.flashRoute === modelData.source.number
                                                   + "->" + modelData.dest.number
                            onFlashingChanged: if (flashing) flashAnim.restart()
                            Component.onCompleted: if (flashing) flashAnim.restart()
                            color: t.isDark ? Qt.lighter(t.surface, 1.10)
                                            : Qt.darker(t.surface, 1.025)
                            border.color: modelData.live && !modelData.saved
                                          ? t.warn
                                          : (!modelData.live && modelData.saved
                                             ? t.dim : "transparent")

                            // A wash that fades out, over the row but under
                            // nothing interactive: it is not a hit target, so
                            // clicking the new row while it fades still works.
                            Rectangle {
                                anchors.fill: parent
                                radius: parent.radius
                                color: t.accent
                                opacity: 0
                                NumberAnimation on opacity {
                                    id: flashAnim
                                    running: false
                                    from: 0.5
                                    to: 0
                                    duration: 1100
                                    easing.type: Easing.OutQuad
                                }
                            }

                            RowLayout {
                                id: routeRow
                                anchors.fill: parent
                                anchors.margins: 6
                                spacing: 8

                                PortPicker {
                                    Layout.fillWidth: true
                                    Layout.preferredWidth: 1      // equal halves
                                    portNumber: modelData.source.number
                                    ports: bridge.routablePorts
                                    onPicked: function (n) {
                                        bridge.retargetRoute(
                                            modelData.source.number,
                                            modelData.dest.number,
                                            n, modelData.dest.number)
                                    }
                                }

                                Label {
                                    text: "\u2b0f"        // right, then up
                                    color: modelData.live ? t.accent : t.dim
                                    font.pixelSize: t.fs(16)
                                    Layout.alignment: Qt.AlignVCenter
                                }

                                PortPicker {
                                    Layout.fillWidth: true
                                    Layout.preferredWidth: 1
                                    portNumber: modelData.dest.number
                                    ports: bridge.routablePorts
                                    onPicked: function (n) {
                                        bridge.retargetRoute(
                                            modelData.source.number,
                                            modelData.dest.number,
                                            modelData.source.number, n)
                                    }
                                }

                                ActionButton {
                                    text: "✕"
                                    danger: true
                                    implicitWidth: Math.max(34, t.fs(36))
                                    Layout.alignment: Qt.AlignVCenter
                                    onClicked: bridge.removeRoute(
                                        modelData.source.number,
                                        modelData.dest.number)
                                }
                            }
                        }
                    }
                }
            }

            // ---- matrix -------------------------------------------------
            Rectangle {
                color: t.surface
                border.color: t.line
                radius: 8

                // Column headers, scrolled horizontally with the body.
                Item {
                    id: topHeader
                    anchors.top: parent.top
                    anchors.topMargin: 1
                    anchors.left: parent.left
                    anchors.leftMargin: page.rowHeaderWidth + 1
                    anchors.right: parent.right
                    height: page.cell + 6
                    clip: true

                    Row {
                        x: -body.contentX
                        Repeater {
                            model: page.dests
                            delegate: Item {
                                required property var modelData
                                required property int index
                                width: page.cell; height: topHeader.height
                                Label {
                                    anchors.centerIn: parent
                                    text: modelData.number
                                    color: page.hoverCol === index
                                           ? t.accent
                                           : (modelData.colourHex.length > 0
                                              ? modelData.colourHex : t.dim)
                                    font.pixelSize: t.fs(10)
                                    font.weight: modelData.colourHex.length > 0
                                                 ? Font.DemiBold : Font.Normal
                                }
                            }
                        }
                    }
                }

                // Row headers, scrolled vertically with the body.
                Item {
                    id: leftHeader
                    anchors.top: parent.top
                    anchors.topMargin: topHeader.height + 1
                    anchors.left: parent.left
                    anchors.leftMargin: 1
                    width: page.rowHeaderWidth
                    anchors.bottom: parent.bottom
                    clip: true

                    Column {
                        y: -body.contentY
                        Repeater {
                            model: page.sources
                            delegate: Item {
                                required property var modelData
                                required property int index
                                width: page.rowHeaderWidth; height: page.cell
                                RowLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: 8
                                    anchors.rightMargin: 6
                                    spacing: 6
                                    Rectangle {
                                        implicitWidth: t.fs(22); implicitHeight: t.fs(16)
                                        radius: 3
                                        color: page.hoverRow === index
                                               ? t.accent
                                               : (modelData.colourHex.length > 0
                                                  ? modelData.colourHex : t.line)
                                        Label {
                                            anchors.centerIn: parent
                                            text: modelData.number
                                            color: page.hoverRow === index
                                                   || modelData.colourHex.length > 0
                                                   ? "#ffffff" : t.dim
                                            font.pixelSize: t.fs(9)
                                        }
                                    }
                                    Label {
                                        Layout.fillWidth: true
                                        text: modelData.displayName
                                        color: t.text
                                        font.pixelSize: t.fs(10)
                                        elide: Text.ElideRight
                                    }
                                }
                            }
                        }
                    }
                }

                Rectangle {
                    // Corner label, so the axes are never ambiguous.
                    anchors.top: parent.top; anchors.left: parent.left
                    anchors.topMargin: 1; anchors.leftMargin: 1
                    width: page.rowHeaderWidth; height: topHeader.height
                    color: t.surface
                    Label {
                        anchors.centerIn: parent
                        text: "from  ↓   to  →"
                        color: t.dim
                        font.pixelSize: t.fs(9)
                    }
                }

                Flickable {
                    id: body
                    anchors.top: parent.top
                    anchors.topMargin: topHeader.height + 1
                    anchors.left: parent.left
                    anchors.leftMargin: page.rowHeaderWidth + 1
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    anchors.rightMargin: 1
                    anchors.bottomMargin: 1
                    clip: true
                    contentWidth: page.dests.length * page.cell
                    contentHeight: page.sources.length * page.cell
                    boundsBehavior: Flickable.StopAtBounds
                    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                    ScrollBar.horizontal: ScrollBar { policy: ScrollBar.AsNeeded }

                    Column {
                        Repeater {
                            model: page.grid
                            delegate: Row {
                                required property var modelData
                                required property int index
                                property int sourceIndex: index

                                Repeater {
                                    model: parent.modelData
                                    delegate: Rectangle {
                                        required property int modelData
                                        required property int index
                                        width: page.cell; height: page.cell
                                        // With the axes filtered separately
                                        // the diagonal is where the two axes
                                        // name the same port, which is no
                                        // longer where row == column.
                                        property int destNumber: page.destNumberAt(index)
                                        property int sourceNumber: page.sourceNumberAt(sourceIndex)
                                        property bool isDiagonal:
                                            destNumber >= 0 && destNumber === sourceNumber
                                        property bool saved: (modelData & 1) !== 0
                                        property bool live: (modelData & 2) !== 0
                                        // The opposite direction is routed.
                                        property bool reverseRouted: (modelData & 4) !== 0
                                        property bool inLoop: reverseRouted && (saved || live)
                                        // Which side of the diagonal. For any
                                        // pair of ports one direction sits
                                        // above it and the reverse below, so
                                        // the two halves of a pair are told
                                        // apart by shade instead of by an
                                        // arrow that would have to point the
                                        // wrong way to do it.
                                        property bool descending: sourceNumber > destNumber

                                        color: {
                                            if (isDiagonal) return t.line
                                            // Status colours are not tinted:
                                            // amber means "not saved" in every
                                            // theme and must not shift meaning
                                            // depending on which half it lands
                                            // in.
                                            if (live && !saved) return t.warn
                                            if (saved && live)
                                                return descending ? Qt.darker(t.accent, 1.5)
                                                                  : t.accent
                                            if (saved) return "transparent"
                                            // Empty cells below the diagonal
                                            // carry a faint accent wash. A
                                            // hue, not a brightness nudge:
                                            // lightening the surface lands on
                                            // almost exactly the diagonal's
                                            // own grey, and the split then
                                            // competes with the diagonal
                                            // instead of reading against it.
                                            return descending
                                                ? Qt.rgba(t.accent.r, t.accent.g,
                                                          t.accent.b,
                                                          t.isDark ? 0.13 : 0.10)
                                                : "transparent"
                                        }
                                        border.width: saved && !live ? 2 : 1
                                        border.color: saved && !live ? t.warn : t.line
                                        opacity: isDiagonal ? 0.5 : 1

                                        // Direction of travel, drawn the way
                                        // the grid actually works: the source
                                        // is the row label to the LEFT and the
                                        // destination is the column header
                                        // ABOVE, so every route goes right,
                                        // then up. U+2B0F, "rightwards arrow
                                        // with tip upwards".
                                        //
                                        // The same glyph in every cell, and
                                        // that is correct. An earlier version
                                        // mirrored it by comparing the port
                                        // numbers -- right-up when routing to
                                        // a higher port, down-left to a lower
                                        // one. That encodes ascending versus
                                        // descending numbering, not flow, and
                                        // a route like 5 -> 0 then drew an
                                        // arrow pointing back at its own
                                        // source. Position already tells the
                                        // two halves of a pair apart; the
                                        // arrow only has to say which axis is
                                        // which.
                                        //
                                        // A glyph, not a drawing: there is one
                                        // per connected cell, and anything
                                        // needing its own render target here
                                        // is a thousand of them.
                                        Text {
                                            anchors.centerIn: parent
                                            visible: parent.saved || parent.live
                                            text: "\u2b0f"
                                            color: parent.live ? "#ffffff" : t.warn
                                            opacity: parent.live ? 0.85 : 0.9
                                            font.pixelSize: Math.max(9, page.cell * 0.66)
                                            font.family: "sans-serif"
                                        }

                                        // Both halves of a two-way pair are
                                        // marked, so a loop is visible from
                                        // either cell rather than only the
                                        // one that completed it.
                                        //
                                        // A plain Rectangle, not a Canvas:
                                        // there is one of these per cell and
                                        // the matrix is N x N, so at 32 ports
                                        // a Canvas here means 1024 render
                                        // targets and a window that crawls.
                                        Rectangle {
                                            visible: parent.inLoop
                                            anchors.right: parent.right
                                            anchors.top: parent.top
                                            anchors.margins: 2
                                            width: Math.max(5, parent.width * 0.26)
                                            height: width
                                            radius: 1
                                            color: t.danger
                                        }

                                        // Crosshair: at this cell size the
                                        // eye cannot track a row across 32
                                        // columns without help.
                                        Rectangle {
                                            anchors.fill: parent
                                            visible: page.hoverRow === sourceIndex
                                                     || page.hoverCol === index
                                            color: t.accent
                                            opacity: 0.12
                                        }

                                        MouseArea {
                                            anchors.fill: parent
                                            // Enabled on the diagonal too.
                                            // Skipping it there left a cell
                                            // with no hover handling at all,
                                            // so the crosshair blinked off
                                            // every time the pointer crossed
                                            // it. Only the *click* is withheld
                                            // there; see onClicked.
                                            enabled: destNumber >= 0 && sourceNumber >= 0
                                            hoverEnabled: true
                                            cursorShape: isDiagonal ? Qt.ArrowCursor
                                                                    : Qt.PointingHandCursor
                                            onClicked: {
                                                // A port cannot route to
                                                // itself: it would echo its
                                                // own output into its input.
                                                if (isDiagonal)
                                                    return
                                                if (bridge.wouldCreateLoop(sourceNumber, destNumber)) {
                                                    loopDialog.src = sourceNumber
                                                    loopDialog.dst = destNumber
                                                    loopDialog.srcName = page.sourceNameAt(sourceIndex)
                                                    loopDialog.dstName = page.destNameAt(index)
                                                    loopDialog.open()
                                                } else {
                                                    bridge.toggleLink(sourceNumber, destNumber)
                                                }
                                            }
                                            onEntered: {
                                                page.hoverRow = sourceIndex
                                                page.hoverCol = index
                                                hint.text = isDiagonal
                                                    ? page.sourceDescAt(sourceIndex)
                                                      + "   —   a port cannot route to itself"
                                                    : page.sourceDescAt(sourceIndex)
                                                      + "   →   " + page.destDescAt(index)
                                            }
                                            // Only the cell that currently
                                            // owns the crosshair may clear it.
                                            //
                                            // Qt promises no ordering between
                                            // one MouseArea's exited and the
                                            // next one's entered, and moving
                                            // between adjacent cells often
                                            // delivers entered first. An
                                            // unconditional clear then wiped
                                            // the hover the new cell had just
                                            // set, which is why the crosshair
                                            // appeared and vanished at random
                                            // as the pointer moved.
                                            onExited: {
                                                if (page.hoverRow === sourceIndex
                                                        && page.hoverCol === index) {
                                                    page.hoverRow = -1
                                                    page.hoverCol = -1
                                                    hint.text = ""
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }

            // ---- graph --------------------------------------------------
            Rectangle {
                id: graphView
                color: t.surface
                border.color: t.line
                radius: 8

                Canvas {
                    id: canvas
                    anchors.fill: parent
                    anchors.margins: 12
                    renderStrategy: Canvas.Cooperative

                    property var ports: page.nodes
                    property var links: bridge.links
                    property int highlight: page.selected

                    onPortsChanged: requestPaint()
                    onLinksChanged: requestPaint()
                    onHighlightChanged: requestPaint()
                    Connections {
                        target: bridge
                        function onRoutingChanged() { canvas.requestPaint() }
                        function onPortsChanged() { canvas.requestPaint() }
                    }

                    function nodeAt(i) {
                        var n = ports.length
                        var cx = width / 2, cy = height / 2
                        var r = Math.min(width, height) / 2 - Math.max(34, t.fs(38))
                        // Start at the top and go clockwise, so port 0 is at
                        // twelve o'clock and the order reads like a dial.
                        var a = -Math.PI / 2 + (i / n) * 2 * Math.PI
                        return { x: cx + r * Math.cos(a), y: cy + r * Math.sin(a), a: a }
                    }

                    function indexOfPort(number) {
                        for (var i = 0; i < ports.length; i++)
                            if (ports[i].number === number) return i
                        return -1
                    }

                    onPaint: {
                        var ctx = getContext("2d")
                        ctx.reset()
                        ctx.clearRect(0, 0, width, height)
                        var n = ports.length
                        if (n === 0) return

                        var cx = width / 2, cy = height / 2
                        var dot = Math.max(7, t.fs(8))

                        // Edges first, so nodes sit on top of them.
                        for (var k = 0; k < links.length; k++) {
                            var link = links[k]
                            var a = indexOfPort(link.from), b = indexOfPort(link.to)
                            if (a < 0 || b < 0) continue
                            var pa = nodeAt(a), pb = nodeAt(b)
                            var lit = highlight === a || highlight === b
                            var dim = highlight >= 0 && !lit

                            ctx.beginPath()
                            ctx.moveTo(pa.x, pa.y)
                            // Bow every edge through the middle: straight
                            // chords across a circle overlap into a mess, and
                            // the curve also shows direction at a glance.
                            ctx.quadraticCurveTo(cx, cy, pb.x, pb.y)
                            ctx.lineWidth = lit ? 2.5 : 1.5
                            ctx.globalAlpha = dim ? 0.12 : (lit ? 1.0 : 0.55)
                            ctx.strokeStyle = !link.saved ? t.warn
                                            : !link.live ? t.dim : t.accent
                            ctx.stroke()

                            // Arrowhead at the destination.
                            var mx = 0.5 * (0.5 * pa.x + cx) + 0.5 * (0.5 * cx + pb.x)
                            var ang = Math.atan2(pb.y - cy, pb.x - cx)
                            var hx = pb.x - Math.cos(ang) * dot * 1.6
                            var hy = pb.y - Math.sin(ang) * dot * 1.6
                            ctx.beginPath()
                            ctx.moveTo(hx, hy)
                            ctx.lineTo(hx - Math.cos(ang - 0.5) * dot,
                                       hy - Math.sin(ang - 0.5) * dot)
                            ctx.lineTo(hx - Math.cos(ang + 0.5) * dot,
                                       hy - Math.sin(ang + 0.5) * dot)
                            ctx.closePath()
                            ctx.fillStyle = ctx.strokeStyle
                            ctx.fill()
                        }

                        ctx.globalAlpha = 1
                        for (var i = 0; i < n; i++) {
                            var p = nodeAt(i)
                            var on = highlight === i
                            ctx.beginPath()
                            ctx.arc(p.x, p.y, on ? dot * 1.4 : dot, 0, 2 * Math.PI)
                            ctx.fillStyle = on ? t.accent
                                          : (ports[i].colourHex.length > 0
                                             ? ports[i].colourHex : t.line)
                            ctx.fill()

                            ctx.save()
                            ctx.translate(p.x, p.y)
                            // Labels sit outside the ring, pushed along the
                            // node's own radius so they never cross an edge.
                            var lx = Math.cos(p.a) * (dot + t.fs(12))
                            var ly = Math.sin(p.a) * (dot + t.fs(12))
                            ctx.fillStyle = on ? t.accent : t.dim
                            ctx.font = t.fs(10) + "px sans-serif"
                            ctx.textAlign = Math.abs(Math.cos(p.a)) < 0.2 ? "center"
                                          : (Math.cos(p.a) > 0 ? "left" : "right")
                            ctx.textBaseline = "middle"
                            ctx.fillText(ports[i].number, lx, ly)
                            ctx.restore()
                        }
                    }

                    MouseArea {
                        anchors.fill: parent
                        hoverEnabled: true
                        onPositionChanged: function (mouse) {
                            var best = -1, bestDist = 1e9
                            for (var i = 0; i < canvas.ports.length; i++) {
                                var p = canvas.nodeAt(i)
                                var d = Math.hypot(mouse.x - p.x, mouse.y - p.y)
                                if (d < bestDist) { bestDist = d; best = i }
                            }
                            page.selected = bestDist < Math.max(18, t.fs(20)) ? best : -1
                            hint.text = page.selected >= 0
                                ? page.describePort(canvas.ports[page.selected])
                                : ""
                        }
                        onExited: { page.selected = -1; hint.text = "" }
                    }
                }
            }
        }

        // ---- hover readout ---------------------------------------------
        //
        // The whole row, to itself. It used to share the line with a colour
        // legend, which cost more than it explained: the legend said the
        // same four things forever, while the readout changes with every
        // cell and had to elide to fit beside it.
        RowLayout {
            Layout.fillWidth: true
            spacing: 14

            Label {
                id: hint
                objectName: "routingHint"
                Layout.fillWidth: true
                color: t.text
                font.pixelSize: t.fs(11)
                elide: Text.ElideRight
            }
        }
    }

    // Pull: the kernel is the truth, and the saved routing learns from it.
    // Creating the second half of a two-way pair. Reported, not refused:
    // a loop is occasionally deliberate.
    ThemedDialog {
        id: loopDialog
        objectName: "loopDialog"
        property int src: 0
        property int dst: 0
        property string srcName: ""
        property string dstName: ""
        title: "This will send MIDI in a loop"
        standardButtons: Dialog.Ok | Dialog.Cancel
        onAccepted: bridge.toggleLink(src, dst)

        contentItem: ColumnLayout {
            spacing: 10
            Label {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                color: t.text
                font.pixelSize: t.fs(12)
                text: "\"" + loopDialog.dstName + "\" already routes to \""
                    + loopDialog.srcName + "\". Connecting this direction as "
                    + "well makes a loop: each port echoes what it receives "
                    + "to the other, so every message arrives several times "
                    + "(three, in testing) before ALSA stops it."
            }
            Label {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                color: t.dim
                font.pixelSize: t.fs(11)
                text: "For two-way MIDI between an application and a device, "
                    + "use two separate ports — one carrying each direction — "
                    + "rather than one pair wired both ways."
            }
        }
    }

    ThemedDialog {
        id: pullDialog
        objectName: "pullDialog"
        title: "Save what the kernel has?"
        standardButtons: Dialog.Ok | Dialog.Cancel
        onAccepted: bridge.syncFromKernel(pullForget.checked)

        contentItem: ColumnLayout {
            spacing: 10

            Label {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                color: t.text
                font.pixelSize: t.fs(12)
                text: bridge.unmanagedLinkCount > 0
                    ? bridge.unmanagedLinkCount + " active connection"
                      + (bridge.unmanagedLinkCount === 1 ? " is" : "s are")
                      + " not in your saved routing. "
                      + (bridge.unmanagedLinkCount === 1 ? "It" : "They")
                      + " will be saved, so the app restores "
                      + (bridge.unmanagedLinkCount === 1 ? "it" : "them")
                      + " after a reboot or a port-count change."
                    : "Every active connection is already saved."
            }

            Label {
                Layout.fillWidth: true
                visible: bridge.inactiveSavedCount > 0
                wrapMode: Text.WordWrap
                color: t.dim
                font.pixelSize: t.fs(11)
                text: bridge.inactiveSavedCount + " saved route"
                    + (bridge.inactiveSavedCount === 1 ? " is" : "s are")
                    + " not connected right now. "
                    + (bridge.inactiveSavedCount === 1 ? "It is" : "They are")
                    + " kept unless you tick the box below."
            }

            ThemedSwitch {
                id: pullForget
                visible: bridge.inactiveSavedCount > 0
                text: "Also forget saved routes that are not connected"
            }

            Label {
                Layout.fillWidth: true
                visible: pullForget.checked
                wrapMode: Text.WordWrap
                color: t.warn
                font.pixelSize: t.fs(11)
                text: "Routes for ports that do not currently exist are still "
                    + "kept — lowering the port count should not delete your "
                    + "setup."
            }
        }
    }

    // Push: the saved routing is the truth, so the kernel is made to match
    // it exactly rather than merged into.
    ThemedDialog {
        id: applyDialog
        title: "Remove " + bridge.unmanagedLinkCount + " connection"
               + (bridge.unmanagedLinkCount === 1 ? "?" : "s?")
        standardButtons: Dialog.Ok | Dialog.Cancel
        contentItem: Label {
            text: bridge.unmanagedLinkCount + " connection"
                + (bridge.unmanagedLinkCount === 1 ? " is" : "s are")
                + " active between MIDI Through ports but not in your saved "
                + "routing. Applying will remove "
                + (bridge.unmanagedLinkCount === 1 ? "it" : "them")
                + ".\n\nTo keep "
                + (bridge.unmanagedLinkCount === 1 ? "it" : "them")
                + " instead, cancel and use Sync from Kernel.\n\n"
                + "Connections belonging to other applications — a browser "
                + "or a DAW subscribed to a port — are never touched."
            color: t.text
            font.pixelSize: t.fs(12)
            wrapMode: Text.WordWrap
        }
        onAccepted: bridge.applySavedRouting()
    }
}
