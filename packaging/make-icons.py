#!/usr/bin/env python3
"""Generate the tray/application icons.

A 5-pin DIN connector: instantly readable as MIDI at 22 px, which is the size
that actually matters in a system tray. Drawn rather than shipped as binary
blobs so a colour can be changed in one line and regenerated.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPen

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "lmssdr" / "resources"
#: Sizes installed into the icon theme. A tray needs the small ones and gets
#: them wrong if it has to downscale 256px artwork itself.
THEME_DIR = ROOT / "packaging" / "icons"
THEME_SIZES = (16, 22, 24, 32, 48, 64, 128, 256)
SIZE = 256

# Default plus one per tray state. Keep in step with lmssdr/resources.
COLOURS = {
    "": "#21a5b8",          # default: the Ocean accent
    "blue": "#5a8dea",      # listening, nothing heard yet
    "green": "#4caf6d",     # unmuted
    "red": "#e05a5a",       # muted
    "purple": "#9b7ede",    # talkback
}


def draw(colour: str, path: Path, size: int = SIZE) -> None:
    image = QImage(size, size, QImage.Format_ARGB32)
    image.fill(Qt.transparent)

    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    ink = QColor(colour)

    # Body ring.
    stroke = size * 0.085
    painter.setPen(QPen(ink, stroke, Qt.SolidLine, Qt.RoundCap))
    painter.setBrush(Qt.NoBrush)
    inset = stroke / 2 + size * 0.04
    painter.drawEllipse(QRectF(inset, inset, size - 2 * inset, size - 2 * inset))

    # Five pins on a 180-degree arc, the DIN-5 layout: 180, 135, 90, 45, 0
    # degrees measured from the left, which puts one pin at top centre.
    centre = QPointF(size / 2, size / 2)
    radius = size * 0.27
    pin = size * 0.058
    painter.setPen(Qt.NoPen)
    painter.setBrush(ink)
    for degrees in (180, 135, 90, 45, 0):
        angle = math.radians(degrees)
        point = QPointF(centre.x() - radius * math.cos(angle),
                        centre.y() - radius * math.sin(angle))
        painter.drawEllipse(point, pin, pin)

    # Keyway notch at the bottom, as on a real connector.
    notch_w, notch_h = size * 0.20, size * 0.085
    painter.drawRoundedRect(
        QRectF(centre.x() - notch_w / 2, centre.y() + radius * 0.72,
               notch_w, notch_h),
        notch_h / 2, notch_h / 2)
    painter.end()

    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(str(path))


def main() -> int:
    QGuiApplication(sys.argv)
    for suffix, colour in COLOURS.items():
        name = "lmssdr.png" if not suffix else f"lmssdr-{suffix}.png"
        draw(colour, OUT_DIR / name)
        print(f"  {(OUT_DIR / name).relative_to(ROOT)}  {colour}")
        # Theme sizes, for installation. Drawn at each size rather than
        # scaled from one: the ring and the pins are thin, and a downscaled
        # 256px icon turns to mush at 22px, which is the size a tray uses.
        for size in THEME_SIZES:
            out = THEME_DIR / f"{size}x{size}" / name
            draw(colour, out, size)
    print(f"  theme sizes {THEME_SIZES} under {THEME_DIR.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
