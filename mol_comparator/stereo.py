"""Simple stereochemical descriptors."""

from __future__ import annotations

from .internals import _cross, _dot, _vec


def tetrahedral_parity(
    center: tuple[float, float, float],
    neighbors: list[tuple[float, float, float]],
) -> int:
    if len(neighbors) != 4:
        raise ValueError("tetrahedral parity requires four neighbors")
    first = _vec(center, neighbors[0])
    second = _vec(center, neighbors[1])
    third = _vec(center, neighbors[2])
    volume = _dot(_cross(first, second), third)
    if abs(volume) < 1e-9:
        return 0
    return 1 if volume > 0 else -1
