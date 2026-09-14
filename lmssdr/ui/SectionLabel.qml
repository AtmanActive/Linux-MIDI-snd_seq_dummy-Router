import QtQuick
import QtQuick.Controls

Label {
    Theme { id: t }
    color: t.dim
    font.pixelSize: t.fs(11)
    font.capitalization: Font.AllUppercase
    font.letterSpacing: 1.1
    topPadding: t.fs(8)
}
