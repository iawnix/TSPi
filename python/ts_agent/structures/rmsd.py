"""RMSD helpers."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


Point = tuple[float, float, float]


@dataclass(frozen=True)
class RigidTransform:
    """Proper rotation and translation that map target coordinates to a reference."""

    rotation: tuple[Point, Point, Point]
    translation: Point

    def apply(self, points: list[Point]) -> list[Point]:
        if not points:
            return []
        coordinates = _point_array(points)
        rotation = np.asarray(self.rotation, dtype=float)
        translation = np.asarray(self.translation, dtype=float)
        transformed = coordinates @ rotation + translation
        return [tuple(float(value) for value in row) for row in transformed]


def rmsd(points_a: list[Point], points_b: list[Point]) -> float:
    if len(points_a) != len(points_b):
        raise ValueError("RMSD point lists must have the same length")
    if not points_a:
        raise ValueError("RMSD needs at least one point")
    return math.sqrt(
        sum((ax - bx) ** 2 + (ay - by) ** 2 + (az - bz) ** 2 for (ax, ay, az), (bx, by, bz) in zip(points_a, points_b))
        / len(points_a)
    )


def centered(points: list[Point]) -> list[Point]:
    count = len(points)
    if count == 0:
        return []
    center = (
        sum(point[0] for point in points) / count,
        sum(point[1] for point in points) / count,
        sum(point[2] for point in points) / count,
    )
    return [(point[0] - center[0], point[1] - center[1], point[2] - center[2]) for point in points]


def centered_rmsd(points_a: list[Point], points_b: list[Point]) -> float:
    return rmsd(centered(points_a), centered(points_b))


def kabsch_transform(reference_points: list[Point], target_points: list[Point]) -> RigidTransform:
    """Fit a target-to-reference least-squares transform without allowing reflection."""

    if len(reference_points) != len(target_points):
        raise ValueError("Kabsch point lists must have the same length")
    if not reference_points:
        raise ValueError("Kabsch alignment needs at least one point")

    reference = _point_array(reference_points)
    target = _point_array(target_points)
    reference_center = reference.mean(axis=0)
    target_center = target.mean(axis=0)
    reference_centered = reference - reference_center
    target_centered = target - target_center

    covariance = target_centered.T @ reference_centered
    left, _singular_values, right_transpose = np.linalg.svd(covariance)
    correction = np.eye(3)
    correction[-1, -1] = 1.0 if np.linalg.det(left @ right_transpose) >= 0.0 else -1.0
    rotation = left @ correction @ right_transpose
    translation = reference_center - target_center @ rotation

    return RigidTransform(
        rotation=tuple(tuple(float(value) for value in row) for row in rotation),
        translation=tuple(float(value) for value in translation),
    )


def _point_array(points: list[Point]) -> np.ndarray:
    try:
        coordinates = np.asarray(points, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError("coordinates must contain numeric three-dimensional points") from exc
    if coordinates.shape != (len(points), 3):
        raise ValueError("coordinates must have shape (n, 3)")
    if not np.isfinite(coordinates).all():
        raise ValueError("coordinates must contain only finite values")
    return coordinates
