"""Simple stereochemical descriptors and explicit stereo comparisons."""

from __future__ import annotations

from typing import Any

from .internals import _cross, _dot, _vec, dihedral


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


def compare_stereochemistry(
    ref_coords: list[tuple[float, float, float]],
    tgt_coords: list[tuple[float, float, float]],
    mapping: list[tuple[int, int]],
    checks: list[dict[str, Any]] | None,
    *,
    dihedral_tolerance_degrees: float = 30.0,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Compare explicitly declared stereochemical features.

    Checks use zero-based atom indices, matching the rest of ``mol_comparator``.
    Supported check shapes:

    - ``{"type": "tetrahedral", "center": 0, "neighbors": [1, 2, 3, 4],
       "policy": "retain"}``
    - ``{"type": "alkene", "atoms": [1, 2], "substituents": [0, 3],
       "policy": "retain"}``
    - ``{"type": "dihedral", "atoms": [0, 1, 2, 3], "policy": "retain",
       "max_delta_degrees": 20}``
    """

    rows: list[dict[str, Any]] = []
    diagnostics: list[str] = []
    if not checks:
        return rows, diagnostics
    target_by_ref = {ref: target for ref, target in mapping}
    for index, check in enumerate(checks):
        if not isinstance(check, dict):
            diagnostics.append(f"stereo check {index} is not an object")
            continue
        kind = str(check.get("type") or check.get("kind") or "").lower()
        try:
            if kind == "tetrahedral":
                row = _tetrahedral_row(check, ref_coords, tgt_coords, target_by_ref)
            elif kind == "alkene":
                row = _alkene_row(check, ref_coords, tgt_coords, target_by_ref)
            elif kind == "dihedral":
                row = _dihedral_row(check, ref_coords, tgt_coords, target_by_ref, dihedral_tolerance_degrees)
            else:
                diagnostics.append(f"unsupported stereo check type at index {index}: {kind or '<missing>'}")
                continue
        except (IndexError, KeyError, TypeError, ValueError) as exc:
            diagnostics.append(f"invalid stereo check {index}: {exc}")
            continue
        rows.append(row)
        if row["verdict"] != "matched":
            diagnostics.append(row["diagnostic"])
    return rows, diagnostics


def _tetrahedral_row(check, ref_coords, tgt_coords, target_by_ref):
    center = int(check["center"])
    neighbors = [int(item) for item in check["neighbors"]]
    if len(neighbors) != 4:
        raise ValueError("tetrahedral check requires four neighbors")
    tgt_center = target_by_ref[center]
    tgt_neighbors = [target_by_ref[item] for item in neighbors]
    ref_parity = tetrahedral_parity(ref_coords[center], [ref_coords[item] for item in neighbors])
    tgt_parity = tetrahedral_parity(tgt_coords[tgt_center], [tgt_coords[item] for item in tgt_neighbors])
    policy = _policy(check, default="retain")
    matched = _parity_matches(ref_parity, tgt_parity, policy)
    return {
        "type": "tetrahedral",
        "center": center,
        "neighbors": neighbors,
        "policy": policy,
        "reference_parity": ref_parity,
        "target_parity": tgt_parity,
        "verdict": "matched" if matched else "mismatched",
        "diagnostic": "" if matched else f"tetrahedral parity policy {policy} failed at center {center}",
    }


def _alkene_row(check, ref_coords, tgt_coords, target_by_ref):
    atoms = [int(item) for item in check["atoms"]]
    substituents = [int(item) for item in check["substituents"]]
    if len(atoms) != 2 or len(substituents) != 2:
        raise ValueError("alkene check requires atoms=[i,j] and substituents=[a,b]")
    ref_label = _ez_label(dihedral(ref_coords[substituents[0]], ref_coords[atoms[0]], ref_coords[atoms[1]], ref_coords[substituents[1]]))
    mapped_atoms = [target_by_ref[item] for item in atoms]
    mapped_substituents = [target_by_ref[item] for item in substituents]
    tgt_label = _ez_label(
        dihedral(
            tgt_coords[mapped_substituents[0]],
            tgt_coords[mapped_atoms[0]],
            tgt_coords[mapped_atoms[1]],
            tgt_coords[mapped_substituents[1]],
        )
    )
    policy = _policy(check, default="retain")
    if policy in {"retain", "same", "match"}:
        matched = ref_label == tgt_label
    elif policy in {"invert", "opposite"}:
        matched = ref_label != tgt_label
    elif policy in {"E", "Z"}:
        matched = tgt_label == policy
    else:
        raise ValueError(f"unsupported alkene policy: {policy}")
    return {
        "type": "alkene",
        "atoms": atoms,
        "substituents": substituents,
        "policy": policy,
        "reference_assignment": ref_label,
        "target_assignment": tgt_label,
        "verdict": "matched" if matched else "mismatched",
        "diagnostic": "" if matched else f"alkene stereochemical policy {policy} failed for atoms {atoms}",
    }


def _dihedral_row(check, ref_coords, tgt_coords, target_by_ref, default_tolerance):
    atoms = [int(item) for item in check["atoms"]]
    if len(atoms) != 4:
        raise ValueError("dihedral check requires four atoms")
    ref_value = dihedral(ref_coords[atoms[0]], ref_coords[atoms[1]], ref_coords[atoms[2]], ref_coords[atoms[3]])
    mapped = [target_by_ref[item] for item in atoms]
    tgt_value = dihedral(tgt_coords[mapped[0]], tgt_coords[mapped[1]], tgt_coords[mapped[2]], tgt_coords[mapped[3]])
    delta = _signed_angle_delta(tgt_value, ref_value)
    tolerance = float(check.get("max_delta_degrees", default_tolerance))
    policy = _policy(check, default="retain")
    if policy in {"retain", "same", "match"}:
        matched = abs(delta) <= tolerance
    elif policy in {"invert", "opposite"}:
        matched = abs(abs(delta) - 180.0) <= tolerance
    else:
        raise ValueError(f"unsupported dihedral policy: {policy}")
    return {
        "type": "dihedral",
        "atoms": atoms,
        "policy": policy,
        "reference_degrees": ref_value,
        "target_degrees": tgt_value,
        "delta_degrees": delta,
        "max_delta_degrees": tolerance,
        "verdict": "matched" if matched else "mismatched",
        "diagnostic": "" if matched else f"dihedral stereochemical policy {policy} failed for atoms {atoms}",
    }


def _policy(check: dict[str, Any], *, default: str) -> str:
    value = check.get("policy", check.get("expected", default))
    policy = str(value).strip()
    if policy.upper() in {"E", "Z"}:
        return policy.upper()
    return policy.lower()


def _parity_matches(ref_parity: int, tgt_parity: int, policy: str) -> bool:
    if ref_parity == 0 or tgt_parity == 0:
        return False
    if policy in {"retain", "same", "match"}:
        return ref_parity == tgt_parity
    if policy in {"invert", "opposite"}:
        return ref_parity == -tgt_parity
    if policy in {"positive", "+", "1"}:
        return tgt_parity == 1
    if policy in {"negative", "-", "-1"}:
        return tgt_parity == -1
    raise ValueError(f"unsupported tetrahedral policy: {policy}")


def _ez_label(value: float) -> str:
    return "Z" if abs(value) < 90.0 else "E"


def _signed_angle_delta(target: float, reference: float) -> float:
    delta = target - reference
    while delta > 180.0:
        delta -= 360.0
    while delta < -180.0:
        delta += 360.0
    return delta
