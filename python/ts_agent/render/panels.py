"""Deterministic composition for multi-structure render outputs."""

from __future__ import annotations

import math
import os
from io import BytesIO
from pathlib import Path
from typing import Iterable


def compose_panels(
    panel_files: Iterable[str | Path],
    output_file: str | Path,
    *,
    resolution: tuple[int, int],
    layout: str,
    labels: list[str] | None = None,
    background: str = "white",
    show_arrows: bool = False,
) -> None:
    """Compose pre-rendered molecular PNGs into one fixed-size canvas."""

    try:
        from PIL import Image, ImageColor, ImageDraw, ImageFont
    except ImportError as exc:  # pragma: no cover - exercised by runtime diagnostics
        raise RuntimeError("Pillow is required for multi-panel rendering") from exc

    paths = [Path(value) for value in panel_files]
    if not paths:
        raise ValueError("panel composition requires at least one image")
    if layout not in {"horizontal", "vertical", "grid"}:
        raise ValueError(f"unsupported panel layout: {layout}")
    if show_arrows and layout == "grid":
        raise ValueError("reaction arrows require horizontal or vertical layout")
    captions = list(labels or [])
    if captions and len(captions) != len(paths):
        raise ValueError("panel labels must match the number of input structures")

    width, height = resolution
    if width < 128 or height < 128:
        raise ValueError("multi-panel resolution must be at least 128x128")

    columns, rows = _grid_shape(len(paths), layout)
    short_side = min(width, height)
    margin = max(8, min(32, short_side // 24))
    base_gap = max(12, min(32, short_side // 20))
    gap_x = max(base_gap, min(96, width // 16)) if show_arrows and layout == "horizontal" else base_gap
    gap_y = max(base_gap, min(96, height // 16)) if show_arrows and layout == "vertical" else base_gap
    available_width = width - (2 * margin) - ((columns - 1) * gap_x)
    available_height = height - (2 * margin) - ((rows - 1) * gap_y)
    if available_width < columns or available_height < rows:
        raise ValueError("panel layout does not fit the requested resolution")

    cell_width = available_width // columns
    cell_height = available_height // rows
    label_height = min(56, max(24, cell_height // 8)) if captions else 0
    content_height = cell_height - label_height
    if content_height < 1:
        raise ValueError("panel labels leave no room for molecular images")

    background_rgba = _background_color(ImageColor, background)
    foreground = _contrast_color(background_rgba)
    canvas = Image.new("RGBA", (width, height), background_rgba)
    draw = ImageDraw.Draw(canvas)
    cells: list[tuple[int, int, int, int]] = []

    for index, path in enumerate(paths):
        row, column = divmod(index, columns)
        x = margin + column * (cell_width + gap_x)
        y = margin + row * (cell_height + gap_y)
        cells.append((x, y, cell_width, cell_height))
        with Image.open(path) as source:
            panel = source.convert("RGBA")
        bounds = panel.getchannel("A").getbbox()
        if bounds:
            panel = panel.crop(bounds)
        panel.thumbnail((cell_width, content_height), Image.Resampling.LANCZOS)
        panel_x = x + (cell_width - panel.width) // 2
        panel_y = y + (content_height - panel.height) // 2
        canvas.alpha_composite(panel, (panel_x, panel_y))

        if captions:
            caption = captions[index]
            font, caption = _fit_caption(ImageFont, draw, caption, cell_width - 8, label_height - 4)
            text_box = draw.textbbox((0, 0), caption, font=font)
            text_width = text_box[2] - text_box[0]
            text_height = text_box[3] - text_box[1]
            text_x = x + (cell_width - text_width) // 2
            text_y = y + content_height + max(0, (label_height - text_height) // 2) - text_box[1]
            draw.text((text_x, text_y), caption, font=font, fill=foreground)

    if show_arrows:
        _draw_sequence_arrows(draw, cells, layout, foreground, short_side)

    output = Path(output_file)
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    payload = BytesIO()
    canvas.save(payload, format="PNG")
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(payload.getvalue())
    finally:
        os.close(descriptor)


def _grid_shape(count: int, layout: str) -> tuple[int, int]:
    if layout == "horizontal":
        return count, 1
    if layout == "vertical":
        return 1, count
    columns = math.ceil(math.sqrt(count))
    return columns, math.ceil(count / columns)


def _background_color(image_color, value: str) -> tuple[int, int, int, int]:
    if value == "transparent":
        return (0, 0, 0, 0)
    try:
        return image_color.getcolor(value, "RGBA")
    except ValueError as exc:
        raise ValueError(f"unsupported panel background: {value}") from exc


def _contrast_color(background: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    red, green, blue, alpha = background
    if alpha == 0:
        return (24, 24, 27, 255)
    luminance = (0.2126 * red) + (0.7152 * green) + (0.0722 * blue)
    return (24, 24, 27, 255) if luminance >= 145 else (245, 245, 245, 255)


def _fit_caption(image_font, draw, value: str, max_width: int, max_height: int):
    caption = str(value).strip()
    if not caption:
        caption = " "
    maximum = max(10, min(34, max_height))
    for size in range(maximum, 9, -1):
        try:
            font = image_font.truetype("DejaVuSans.ttf", size)
        except OSError:
            font = image_font.load_default()
        box = draw.textbbox((0, 0), caption, font=font)
        if box[2] - box[0] <= max_width and box[3] - box[1] <= max_height:
            return font, caption
    font = image_font.load_default()
    while len(caption) > 4:
        candidate = f"{caption[:-4]}..."
        box = draw.textbbox((0, 0), candidate, font=font)
        if box[2] - box[0] <= max_width:
            return font, candidate
        caption = caption[:-1]
    return font, caption


def _draw_sequence_arrows(draw, cells, layout: str, color, short_side: int) -> None:
    line_width = max(2, min(6, short_side // 160))
    for current, following in zip(cells, cells[1:]):
        x, y, width, height = current
        next_x, next_y, next_width, next_height = following
        if layout == "horizontal":
            start = (x + width + 4, y + height // 2)
            end = (next_x - 4, next_y + next_height // 2)
        else:
            start = (x + width // 2, y + height + 4)
            end = (next_x + next_width // 2, next_y - 4)
        _draw_arrow(draw, start, end, color, line_width)


def _draw_arrow(draw, start: tuple[int, int], end: tuple[int, int], color, width: int) -> None:
    delta_x = end[0] - start[0]
    delta_y = end[1] - start[1]
    length = math.hypot(delta_x, delta_y)
    if length < 8:
        return
    unit_x = delta_x / length
    unit_y = delta_y / length
    head_length = max(10, width * 4)
    head_width = max(6, width * 3)
    base_x = end[0] - (unit_x * head_length)
    base_y = end[1] - (unit_y * head_length)
    perpendicular_x = -unit_y
    perpendicular_y = unit_x
    draw.line((start, (base_x, base_y)), fill=color, width=width)
    draw.polygon(
        [
            end,
            (base_x + perpendicular_x * head_width, base_y + perpendicular_y * head_width),
            (base_x - perpendicular_x * head_width, base_y - perpendicular_y * head_width),
        ],
        fill=color,
    )
