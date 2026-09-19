#!/usr/bin/env python3
"""Build the small, dependency-light TSPi model icon font.

The font intentionally uses Supplementary Private Use Area codepoints. Nerd
Fonts heavily occupy the Basic Private Use Area, so putting these glyphs there
would let a terminal's primary font shadow TSPi's fallback font.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen


UPM = 1000
ASCENT = 800
DESCENT = -200
ADVANCE = 1000

GLYPH_CODES = {
    "tspi-deepseek": 0xF0000,
    "tspi-gpt": 0xF0001,
    "tspi-glm": 0xF0002,
    "tspi-seeddance": 0xF0003,
    "tspi-model": 0xF0004,
}


def polygon(pen: TTGlyphPen, points: list[tuple[int, int]]) -> None:
    pen.moveTo(points[0])
    for point in points[1:]:
        pen.lineTo(point)
    pen.closePath()


def rectangle(pen: TTGlyphPen, x0: int, y0: int, x1: int, y1: int) -> None:
    polygon(pen, [(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


def circle(pen: TTGlyphPen, cx: int, cy: int, radius: int) -> None:
    # Four quadratic arcs keep the outline in the native TrueType format.
    pen.moveTo((cx + radius, cy))
    pen.qCurveTo((cx + radius, cy + radius), (cx, cy + radius))
    pen.qCurveTo((cx - radius, cy + radius), (cx - radius, cy))
    pen.qCurveTo((cx - radius, cy - radius), (cx, cy - radius))
    pen.qCurveTo((cx + radius, cy - radius), (cx + radius, cy))
    pen.closePath()


def deepseek() -> object:
    pen = TTGlyphPen(None)
    # A compact fish/whale silhouette with a pointed tail and eye.
    polygon(pen, [(170, 390), (310, 535), (530, 575), (745, 515), (875, 620), (850, 470), (875, 320), (745, 425), (530, 365), (310, 405)])
    circle(pen, 655, 480, 32)
    return pen.glyph()


def gpt() -> object:
    pen = TTGlyphPen(None)
    # Six interlocking petals read as a knot/rosette at terminal sizes.
    for cx, cy in ((500, 680), (690, 575), (690, 355), (500, 250), (310, 355), (310, 575)):
        polygon(pen, [(cx, cy + 120), (cx + 72, cy + 38), (cx + 52, cy - 72), (cx, cy - 110), (cx - 52, cy - 72), (cx - 72, cy + 38)])
    circle(pen, 500, 465, 82)
    return pen.glyph()


def glm() -> object:
    pen = TTGlyphPen(None)
    # Angular G with a central crossbar and three small connection nodes.
    polygon(pen, [(760, 650), (650, 735), (405, 735), (240, 610), (190, 405), (260, 210), (430, 120), (660, 140), (790, 270), (790, 420), (500, 420), (500, 330), (700, 330), (700, 280), (610, 220), (440, 215), (335, 290), (295, 420), (335, 560), (440, 640), (610, 640), (700, 575)])
    circle(pen, 500, 465, 28)
    circle(pen, 760, 465, 28)
    circle(pen, 500, 120, 28)
    return pen.glyph()


def seeddance() -> object:
    pen = TTGlyphPen(None)
    # Seed/leaf pair with a short motion spark.
    polygon(pen, [(460, 180), (330, 300), (300, 470), (350, 650), (470, 755), (565, 620), (575, 445), (540, 290)])
    polygon(pen, [(515, 560), (650, 685), (790, 690), (735, 555), (610, 485)])
    polygon(pen, [(150, 700), (285, 720), (210, 640)])
    polygon(pen, [(720, 250), (865, 295), (760, 335)])
    rectangle(pen, 170, 330, 255, 365)
    return pen.glyph()


def generic_model() -> object:
    pen = TTGlyphPen(None)
    # Chip body plus four pins on each side.
    rectangle(pen, 275, 235, 725, 695)
    rectangle(pen, 390, 350, 610, 580)
    for offset in (315, 435, 555, 675):
        rectangle(pen, offset, 720, offset + 45, 820)
        rectangle(pen, offset, 110, offset + 45, 210)
        rectangle(pen, 175, offset, 275, offset + 45)
        rectangle(pen, 725, offset, 825, offset + 45)
    return pen.glyph()


def build(output: Path) -> None:
    glyphs = {
        ".notdef": TTGlyphPen(None).glyph(),
        "tspi-deepseek": deepseek(),
        "tspi-gpt": gpt(),
        "tspi-glm": glm(),
        "tspi-seeddance": seeddance(),
        "tspi-model": generic_model(),
    }
    builder = FontBuilder(UPM, isTTF=True)
    builder.setupGlyphOrder(list(glyphs))
    builder.setupCharacterMap({code: name for name, code in GLYPH_CODES.items()})
    builder.setupGlyf(glyphs)
    builder.setupHorizontalMetrics({name: (ADVANCE, 0) for name in glyphs})
    builder.setupHorizontalHeader(ascent=ASCENT, descent=DESCENT)
    builder.setupOS2(
        sTypoAscender=ASCENT,
        sTypoDescender=DESCENT,
        sTypoLineGap=0,
        usWinAscent=ASCENT,
        usWinDescent=-DESCENT,
        sxHeight=450,
        sCapHeight=700,
    )
    builder.setupNameTable(
        {
            "familyName": "TSPi Model Icons",
            "styleName": "Regular",
            "fullName": "TSPi Model Icons Regular",
            "uniqueFontIdentifier": "TSPi Model Icons Regular",
            "psName": "TSPi-Model-Icons-Regular",
            "version": "Version 2.0",
        }
    )
    builder.setupPost(keepGlyphNames=True)
    builder.setupMaxp()
    # Avoid embedding the build clock in the checked-in binary.
    builder.font["head"].fontRevision = 2.0
    builder.font["head"].created = 2082840000
    builder.font["head"].modified = 2082840000
    output.parent.mkdir(parents=True, exist_ok=True)
    builder.save(output)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", nargs="?", type=Path, default=Path("assets/fonts/tspi-model-icons.ttf"))
    args = parser.parse_args()
    build(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
