"""Render configuration constants and parsing helpers."""

from __future__ import annotations

DEFAULT_RESOLUTION = (1024, 768)
STYLES = ("ball_and_stick", "space_fill", "wireframe", "stick", "cartoon", "licorice", "van_der_waals")
ENGINES = ("blender", "mayavi", "pyvista")
COLOR_SCHEMES = ("cpk", "jmol", "rasmol", "element", "temperature", "charge", "electronegativity")
LAYOUTS = ("horizontal", "vertical", "grid")
CAMERA_PATHS = ("orbit", "zoom", "pan", "static")


def parse_resolution(value: str) -> tuple[int, int]:
    try:
        width, height = value.lower().split("x", 1)
        parsed = (int(width), int(height))
    except Exception as exc:
        raise ValueError(f"invalid resolution {value!r}; expected WIDTHxHEIGHT") from exc
    if parsed[0] <= 0 or parsed[1] <= 0:
        raise ValueError(f"invalid resolution {value!r}; dimensions must be positive")
    return parsed
