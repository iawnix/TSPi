"""RMSD helpers."""

from __future__ import annotations

import math


def rmsd(points_a: list[tuple[float, float, float]], points_b: list[tuple[float, float, float]]) -> float:
    if len(points_a) != len(points_b):
        raise ValueError("RMSD point lists must have the same length")
    if not points_a:
        raise ValueError("RMSD needs at least one point")
    return math.sqrt(
        sum((ax - bx) ** 2 + (ay - by) ** 2 + (az - bz) ** 2 for (ax, ay, az), (bx, by, bz) in zip(points_a, points_b))
        / len(points_a)
    )


def centered(points: list[tuple[float, float, float]]) -> list[tuple[float, float, float]]:
    count = len(points)
    if count == 0:
        return []
    center = (
        sum(point[0] for point in points) / count,
        sum(point[1] for point in points) / count,
        sum(point[2] for point in points) / count,
    )
    return [(point[0] - center[0], point[1] - center[1], point[2] - center[2]) for point in points]


def centered_rmsd(points_a: list[tuple[float, float, float]], points_b: list[tuple[float, float, float]]) -> float:
    return rmsd(centered(points_a), centered(points_b))
