"""Deterministic metadata extraction for XYZ artifacts."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


_FLOAT = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][-+]?\d+)?"


def xyz_frame_metadata(path: Path) -> dict[str, Any]:
    parsed = read_xyz_frames(path)
    return {
        "atom_count": parsed["atom_count"],
        "frame_count": len(parsed["frames"]),
        "frames": [
            {key: value for key, value in frame.items() if key != "coordinates"}
            for frame in parsed["frames"]
        ],
    }


def read_xyz_frames(path: Path) -> dict[str, Any]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    frames: list[dict[str, Any]] = []
    atom_count: int | None = None
    index = 0
    while index < len(lines):
        if not lines[index].strip():
            index += 1
            continue
        try:
            count = int(lines[index].strip())
        except ValueError as exc:
            raise ValueError(f"invalid XYZ atom count at line {index + 1}: {path}") from exc
        if count <= 0 or index + count + 1 >= len(lines):
            raise ValueError(f"incomplete XYZ frame at line {index + 1}: {path}")
        if atom_count is None:
            atom_count = count
        elif count != atom_count:
            raise ValueError(f"inconsistent XYZ atom counts in {path}")
        coordinates = _coordinate_values(
            path,
            lines[index + 2 : index + count + 2],
            index + 3,
        )
        title = lines[index + 1].strip()
        energy = _first_float(title, rf"(?:^|\s)energy:\s*({_FLOAT})")
        if energy is None and re.fullmatch(rf"\s*{_FLOAT}\s*", title):
            energy = _number(title)
        frames.append(
            {
                "index": len(frames),
                "title": title,
                "energy_hartree": energy,
                "coordinates": coordinates,
            }
        )
        index += count + 2
    if not frames or atom_count is None:
        raise ValueError(f"XYZ artifact contains no frames: {path}")
    return {"atom_count": atom_count, "frames": frames}


def _coordinate_values(
    path: Path,
    lines: list[str],
    first_line: int,
) -> list[tuple[float, float, float]]:
    coordinates: list[tuple[float, float, float]] = []
    for offset, line in enumerate(lines):
        fields = line.split()
        if len(fields) < 4:
            raise ValueError(f"invalid XYZ coordinate at line {first_line + offset}: {path}")
        try:
            coordinates.append(tuple(_number(value) for value in fields[1:4]))
        except ValueError as exc:
            raise ValueError(
                f"invalid XYZ coordinate at line {first_line + offset}: {path}"
            ) from exc
    return coordinates


def _first_float(text: str, pattern: str) -> float | None:
    match = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
    return _number(match.group(1)) if match else None


def _number(value: str) -> float:
    return float(value.replace("D", "E").replace("d", "e"))
