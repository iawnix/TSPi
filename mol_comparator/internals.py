"""Geometry primitives for molecular comparisons."""

from __future__ import annotations

import math
from pathlib import Path


def read_xyz(path: str | Path) -> tuple[list[str], list[tuple[float, float, float]]]:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    if len(lines) < 2:
        raise ValueError("XYZ file is too short")
    count = int(lines[0].strip())
    symbols: list[str] = []
    coords: list[tuple[float, float, float]] = []
    for line in lines[2 : 2 + count]:
        parts = line.split()
        if len(parts) < 4:
            raise ValueError(f"invalid XYZ atom line: {line!r}")
        symbols.append(parts[0])
        coords.append((float(parts[1]), float(parts[2]), float(parts[3])))
    if len(symbols) != count:
        raise ValueError("XYZ atom count mismatch")
    return symbols, coords


def distance(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def angle(a: tuple[float, float, float], b: tuple[float, float, float], c: tuple[float, float, float]) -> float:
    ba = _vec(b, a)
    bc = _vec(b, c)
    denom = _norm(ba) * _norm(bc)
    if denom == 0:
        raise ValueError("zero-length angle vector")
    cos_value = max(-1.0, min(1.0, _dot(ba, bc) / denom))
    return math.degrees(math.acos(cos_value))


def dihedral(
    a: tuple[float, float, float],
    b: tuple[float, float, float],
    c: tuple[float, float, float],
    d: tuple[float, float, float],
) -> float:
    b0 = _vec(b, a)
    b1 = _vec(b, c)
    b2 = _vec(c, d)
    n0 = _cross(b0, b1)
    n1 = _cross(b1, b2)
    if _norm(n0) == 0 or _norm(n1) == 0:
        raise ValueError("zero-length dihedral normal")
    m1 = _cross(n0, _unit(b1))
    x = _dot(n0, n1)
    y = _dot(m1, n1)
    return math.degrees(math.atan2(y, x))


def heavy_atom_indices(symbols: list[str]) -> list[int]:
    return [index for index, symbol in enumerate(symbols) if symbol.upper() != "H"]


def mapped_indices(count: int, atom_mapping: list[int] | None) -> list[tuple[int, int]]:
    if atom_mapping is None:
        return [(index, index) for index in range(count)]
    if len(atom_mapping) != count:
        raise ValueError("atom mapping length must match reference atom count")
    return [(index, target_index) for index, target_index in enumerate(atom_mapping)]


def _vec(origin: tuple[float, float, float], point: tuple[float, float, float]) -> tuple[float, float, float]:
    return (point[0] - origin[0], point[1] - origin[1], point[2] - origin[2])


def _dot(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: tuple[float, float, float], b: tuple[float, float, float]) -> tuple[float, float, float]:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _norm(a: tuple[float, float, float]) -> float:
    return math.sqrt(_dot(a, a))


def _unit(a: tuple[float, float, float]) -> tuple[float, float, float]:
    norm = _norm(a)
    if norm == 0:
        raise ValueError("zero-length vector")
    return (a[0] / norm, a[1] / norm, a[2] / norm)
