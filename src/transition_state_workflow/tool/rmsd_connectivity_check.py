#!/usr/bin/env python3
"""Judge TS endpoint connectivity with RMSD and key internal coordinates."""

from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path

from transition_state_workflow.chem.geometry import (
    Atom,
    COVALENT_RADII,
    parse_angle_spec,
    parse_bond_spec,
)
from transition_state_workflow.chem.gaussian_log import atomic_symbol, read_lines
from transition_state_workflow.util.cli import emit_json, run_cli, warn


@dataclass(frozen=True)
class Structure:
    path: str
    atoms: list[Atom]
    metadata: dict[str, object]


def read_xyz(path: Path) -> Structure:
    lines = read_lines(path)
    frames: list[list[Atom]] = []
    comments: list[str] = []
    i = 0
    while i < len(lines):
        if not lines[i].strip():
            i += 1
            continue
        try:
            natoms = int(lines[i].strip())
        except ValueError as exc:
            raise ValueError(f"{path}: invalid XYZ atom count at line {i + 1}") from exc
        if i + natoms + 1 >= len(lines):
            raise ValueError(f"{path}: truncated XYZ frame at line {i + 1}")
        comment = lines[i + 1].strip()
        atoms: list[Atom] = []
        for row in lines[i + 2:i + 2 + natoms]:
            parts = row.split()
            if len(parts) < 4:
                raise ValueError(f"{path}: invalid XYZ atom row: {row}")
            atoms.append(Atom(parts[0], float(parts[1]), float(parts[2]), float(parts[3])))
        frames.append(atoms)
        comments.append(comment)
        i += natoms + 2
    if not frames:
        raise ValueError(f"{path}: no XYZ frames found")
    return Structure(
        path=str(path),
        atoms=frames[-1],
        metadata={"format": "xyz", "frame_count": len(frames), "selected_frame": len(frames), "comment": comments[-1]},
    )


def orientation_blocks(lines: list[str], marker: str) -> list[list[Atom]]:
    blocks: list[list[Atom]] = []
    for i, line in enumerate(lines):
        if marker not in line:
            continue
        j = i + 1
        dash_count = 0
        while j < len(lines):
            if lines[j].strip().startswith("----"):
                dash_count += 1
                if dash_count == 2:
                    j += 1
                    break
            j += 1
        atoms: list[Atom] = []
        while j < len(lines) and not lines[j].strip().startswith("----"):
            parts = lines[j].split()
            if len(parts) >= 6:
                try:
                    atoms.append(
                        Atom(
                            atomic_symbol(int(parts[1])),
                            float(parts[3]),
                            float(parts[4]),
                            float(parts[5]),
                        )
                    )
                except ValueError:
                    pass
            j += 1
        if atoms:
            blocks.append(atoms)
    return blocks


def read_gaussian(path: Path) -> Structure:
    lines = read_lines(path)
    standard = orientation_blocks(lines, "Standard orientation:")
    input_orientation = orientation_blocks(lines, "Input orientation:")
    if standard:
        atoms = standard[-1]
        marker = "Standard orientation"
        count = len(standard)
    elif input_orientation:
        atoms = input_orientation[-1]
        marker = "Input orientation"
        count = len(input_orientation)
    else:
        raise ValueError(f"{path}: no Gaussian orientation block found")
    return Structure(
        path=str(path),
        atoms=atoms,
        metadata={
            "format": "gaussian",
            "selected_orientation": marker,
            "orientation_block_count": count,
            "normal_termination": any("Normal termination of Gaussian" in line for line in lines),
            "error_termination": any("Error termination" in line for line in lines),
        },
    )


def read_structure(path_string: str) -> Structure:
    path = Path(path_string)
    if not path.exists():
        raise FileNotFoundError(path)
    suffix = path.suffix.lower()
    if suffix == ".xyz":
        return read_xyz(path)
    if suffix in {".out", ".log"}:
        return read_gaussian(path)
    try:
        return read_xyz(path)
    except Exception:
        return read_gaussian(path)


def parse_bond(spec: str) -> tuple[int, int]:
    try:
        return parse_bond_spec(spec)
    except ValueError as exc:
        message = str(exc)
        if message.startswith("invalid "):
            message = "Invalid " + message[len("invalid ") :]
        raise ValueError(message) from exc


def parse_angle(spec: str) -> tuple[int, int, int]:
    try:
        return parse_angle_spec(spec)
    except ValueError as exc:
        message = str(exc)
        if message.startswith("invalid "):
            message = "Invalid " + message[len("invalid ") :]
        raise ValueError(message) from exc


def validate_indices(natoms: int, bonds: list[tuple[int, int]], angles: list[tuple[int, int, int]]) -> None:
    for item in bonds:
        if max(item) > natoms:
            raise ValueError(f"Bond index out of range for {natoms} atoms: {item}")
    for item in angles:
        if max(item) > natoms:
            raise ValueError(f"Angle index out of range for {natoms} atoms: {item}")


def atom_order(atoms: list[Atom]) -> list[str]:
    return [atom.element for atom in atoms]


def ensure_compatible(reference: Structure, other: Structure, label: str) -> None:
    if len(reference.atoms) != len(other.atoms):
        raise ValueError(f"{label}: atom count mismatch: {len(reference.atoms)} vs {len(other.atoms)}")
    if atom_order(reference.atoms) != atom_order(other.atoms):
        raise ValueError(f"{label}: atom order or elements differ; RMSD would be invalid")


def coords(atoms: list[Atom], indices: list[int]) -> list[tuple[float, float, float]]:
    return [(atoms[i].x, atoms[i].y, atoms[i].z) for i in indices]


def centroid(points: list[tuple[float, float, float]]) -> tuple[float, float, float]:
    scale = 1.0 / len(points)
    return (
        sum(point[0] for point in points) * scale,
        sum(point[1] for point in points) * scale,
        sum(point[2] for point in points) * scale,
    )


def subtract_centroid(
    points: list[tuple[float, float, float]], center: tuple[float, float, float]
) -> list[tuple[float, float, float]]:
    return [(point[0] - center[0], point[1] - center[1], point[2] - center[2]) for point in points]


def matvec(matrix: list[list[float]], vector: list[float]) -> list[float]:
    return [sum(row[i] * vector[i] for i in range(len(vector))) for row in matrix]


def normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0.0:
        return vector
    return [value / norm for value in vector]


def largest_eigenvector_symmetric_4x4(matrix: list[list[float]]) -> list[float]:
    a = [row[:] for row in matrix]
    vectors = [[1.0 if i == j else 0.0 for j in range(4)] for i in range(4)]
    for _ in range(80):
        p, q = 0, 1
        max_value = 0.0
        for i in range(4):
            for j in range(i + 1, 4):
                value = abs(a[i][j])
                if value > max_value:
                    max_value = value
                    p, q = i, j
        if max_value < 1.0e-14:
            break
        app, aqq, apq = a[p][p], a[q][q], a[p][q]
        tau = (aqq - app) / (2.0 * apq)
        sign = 1.0 if tau >= 0.0 else -1.0
        t = sign / (abs(tau) + math.sqrt(1.0 + tau * tau))
        c = 1.0 / math.sqrt(1.0 + t * t)
        s = t * c
        for k in range(4):
            if k in (p, q):
                continue
            akp, akq = a[k][p], a[k][q]
            a[k][p] = a[p][k] = c * akp - s * akq
            a[k][q] = a[q][k] = s * akp + c * akq
        a[p][p] = c * c * app - 2.0 * s * c * apq + s * s * aqq
        a[q][q] = s * s * app + 2.0 * s * c * apq + c * c * aqq
        a[p][q] = a[q][p] = 0.0
        for k in range(4):
            vkp, vkq = vectors[k][p], vectors[k][q]
            vectors[k][p] = c * vkp - s * vkq
            vectors[k][q] = s * vkp + c * vkq
    idx = max(range(4), key=lambda i: a[i][i])
    return normalize([vectors[row][idx] for row in range(4)])


def quaternion_rotation_matrix(quaternion: list[float]) -> list[list[float]]:
    w, x, y, z = normalize(quaternion)
    return [
        [w * w + x * x - y * y - z * z, 2.0 * (x * y - w * z), 2.0 * (x * z + w * y)],
        [2.0 * (x * y + w * z), w * w - x * x + y * y - z * z, 2.0 * (y * z - w * x)],
        [2.0 * (x * z - w * y), 2.0 * (y * z + w * x), w * w - x * x - y * y + z * z],
    ]


def rotate_point(point: tuple[float, float, float], matrix: list[list[float]]) -> tuple[float, float, float]:
    return (
        matrix[0][0] * point[0] + matrix[0][1] * point[1] + matrix[0][2] * point[2],
        matrix[1][0] * point[0] + matrix[1][1] * point[1] + matrix[1][2] * point[2],
        matrix[2][0] * point[0] + matrix[2][1] * point[1] + matrix[2][2] * point[2],
    )


def best_rotation(
    source: list[tuple[float, float, float]], target: list[tuple[float, float, float]]
) -> list[list[float]]:
    sxx = sxy = sxz = syx = syy = syz = szx = szy = szz = 0.0
    for p, q in zip(source, target):
        sxx += p[0] * q[0]
        sxy += p[0] * q[1]
        sxz += p[0] * q[2]
        syx += p[1] * q[0]
        syy += p[1] * q[1]
        syz += p[1] * q[2]
        szx += p[2] * q[0]
        szy += p[2] * q[1]
        szz += p[2] * q[2]
    matrix = [
        [sxx + syy + szz, syz - szy, szx - sxz, sxy - syx],
        [syz - szy, sxx - syy - szz, sxy + syx, szx + sxz],
        [szx - sxz, sxy + syx, -sxx + syy - szz, syz + szy],
        [sxy - syx, szx + sxz, syz + szy, -sxx - syy + szz],
    ]
    return quaternion_rotation_matrix(largest_eigenvector_symmetric_4x4(matrix))


def rmsd(candidate: list[Atom], reference: list[Atom], *, heavy_only: bool, align: bool) -> float:
    indices = [i for i, atom in enumerate(reference) if not heavy_only or atom.element != "H"]
    if not indices:
        raise ValueError("No atoms selected for RMSD")
    p = coords(candidate, indices)
    q = coords(reference, indices)
    if align:
        p = subtract_centroid(p, centroid(p))
        q = subtract_centroid(q, centroid(q))
        rotation = best_rotation(p, q)
        p = [rotate_point(point, rotation) for point in p]
    total = 0.0
    for point_p, point_q in zip(p, q):
        total += (
            (point_p[0] - point_q[0]) ** 2
            + (point_p[1] - point_q[1]) ** 2
            + (point_p[2] - point_q[2]) ** 2
        )
    return math.sqrt(total / len(p))


def distance(atoms: list[Atom], pair: tuple[int, int]) -> float:
    a = atoms[pair[0] - 1]
    b = atoms[pair[1] - 1]
    return math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2 + (a.z - b.z) ** 2)


def angle(atoms: list[Atom], triple: tuple[int, int, int]) -> float:
    a = atoms[triple[0] - 1]
    b = atoms[triple[1] - 1]
    c = atoms[triple[2] - 1]
    v1 = (a.x - b.x, a.y - b.y, a.z - b.z)
    v2 = (c.x - b.x, c.y - b.y, c.z - b.z)
    norm1 = math.sqrt(v1[0] ** 2 + v1[1] ** 2 + v1[2] ** 2)
    norm2 = math.sqrt(v2[0] ** 2 + v2[1] ** 2 + v2[2] ** 2)
    denom = norm1 * norm2
    if denom == 0.0:
        raise ValueError(f"Zero-length vector in angle {triple}")
    dot = v1[0] * v2[0] + v1[1] * v2[1] + v1[2] * v2[2]
    cosang = max(-1.0, min(1.0, dot / denom))
    return math.degrees(math.acos(cosang))


def metric_label(kind: str, indices: tuple[int, ...]) -> str:
    return f"{kind}:{'-'.join(str(i) for i in indices)}"


def covalent_bond_set(atoms: list[Atom], scale: float) -> set[tuple[int, int]]:
    """Infer a conservative covalent bond graph from covalent radii."""

    bonds: set[tuple[int, int]] = set()
    for i, atom_i in enumerate(atoms):
        radius_i = COVALENT_RADII.get(atom_i.element, 0.77)
        for j in range(i + 1, len(atoms)):
            atom_j = atoms[j]
            radius_j = COVALENT_RADII.get(atom_j.element, 0.77)
            if distance(atoms, (i + 1, j + 1)) <= scale * (radius_i + radius_j):
                bonds.add((i + 1, j + 1))
    return bonds


def covalent_identity_evaluation(
    endpoint: Structure,
    reference: Structure,
    *,
    bond_scale: float,
) -> dict[str, object]:
    endpoint_bonds = covalent_bond_set(endpoint.atoms, bond_scale)
    reference_bonds = covalent_bond_set(reference.atoms, bond_scale)
    missing = reference_bonds - endpoint_bonds
    extra = endpoint_bonds - reference_bonds
    return {
        "passed": not missing and not extra,
        "endpoint_bond_count": len(endpoint_bonds),
        "reference_bond_count": len(reference_bonds),
        "missing_reference_bonds": [metric_label("bond", pair) for pair in sorted(missing)],
        "extra_endpoint_bonds": [metric_label("bond", pair) for pair in sorted(extra)],
    }


def pair_evaluation(
    endpoint_name: str,
    endpoint: Structure,
    reference_name: str,
    reference: Structure,
    *,
    bonds: list[tuple[int, int]],
    angles: list[tuple[int, int, int]],
    rmsd_threshold: float,
    bond_threshold: float,
    angle_threshold: float,
    heavy_only: bool,
    align: bool,
) -> dict[str, object]:
    value = rmsd(endpoint.atoms, reference.atoms, heavy_only=heavy_only, align=align)
    metric_rows: list[dict[str, object]] = [
        {
            "endpoint": endpoint_name,
            "reference": reference_name,
            "metric_type": "rmsd",
            "metric": "heavy_rmsd" if heavy_only else "all_atom_rmsd",
            "endpoint_value": value,
            "reference_value": "",
            "difference": value,
            "threshold": rmsd_threshold,
            "passed": value <= rmsd_threshold,
        }
    ]
    bond_pass = True
    angle_pass = True
    max_bond_delta = 0.0
    max_angle_delta = 0.0
    for pair in bonds:
        endpoint_value = distance(endpoint.atoms, pair)
        reference_value = distance(reference.atoms, pair)
        delta = abs(endpoint_value - reference_value)
        max_bond_delta = max(max_bond_delta, delta)
        passed = delta <= bond_threshold
        bond_pass = bond_pass and passed
        metric_rows.append(
            {
                "endpoint": endpoint_name,
                "reference": reference_name,
                "metric_type": "bond",
                "metric": metric_label("bond", pair),
                "endpoint_value": endpoint_value,
                "reference_value": reference_value,
                "difference": delta,
                "threshold": bond_threshold,
                "passed": passed,
            }
        )
    for triple in angles:
        endpoint_value = angle(endpoint.atoms, triple)
        reference_value = angle(reference.atoms, triple)
        delta = abs(endpoint_value - reference_value)
        max_angle_delta = max(max_angle_delta, delta)
        passed = delta <= angle_threshold
        angle_pass = angle_pass and passed
        metric_rows.append(
            {
                "endpoint": endpoint_name,
                "reference": reference_name,
                "metric_type": "angle",
                "metric": metric_label("angle", triple),
                "endpoint_value": endpoint_value,
                "reference_value": reference_value,
                "difference": delta,
                "threshold": angle_threshold,
                "passed": passed,
            }
        )
    all_pass = value <= rmsd_threshold and bond_pass and angle_pass
    return {
        "endpoint": endpoint_name,
        "reference": reference_name,
        "rmsd": value,
        "rmsd_pass": value <= rmsd_threshold,
        "bond_pass": bond_pass,
        "angle_pass": angle_pass,
        "max_bond_delta_angstrom": max_bond_delta if bonds else None,
        "max_angle_delta_degree": max_angle_delta if angles else None,
        "passed": all_pass,
        "metric_rows": metric_rows,
    }


def assignment_score(pairs: list[dict[str, object]], args: argparse.Namespace) -> float:
    score = 0.0
    for pair in pairs:
        score += float(pair["rmsd"]) / max(args.rmsd_threshold, 1.0e-12)
        if pair["max_bond_delta_angstrom"] is not None:
            score += float(pair["max_bond_delta_angstrom"]) / max(args.bond_threshold, 1.0e-12)
        if pair["max_angle_delta_degree"] is not None:
            score += float(pair["max_angle_delta_degree"]) / max(args.angle_threshold, 1.0e-12)
    return score


def write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--forward", required=True, help="Forward endpoint structure, XYZ or Gaussian out/log")
    parser.add_argument("--reverse", required=True, help="Reverse endpoint structure, XYZ or Gaussian out/log")
    parser.add_argument("--reactant", required=True, help="Reference reactant structure, same atom order")
    parser.add_argument("--product", required=True, help="Reference product structure, same atom order")
    parser.add_argument("--bonds", nargs="*", default=[], help="Key bond specs, 1-based, e.g. 1-23 23-54")
    parser.add_argument("--angles", nargs="*", default=[], help="Key angle specs, 1-based, e.g. 23-1-54")
    parser.add_argument("--rmsd-threshold", type=float, default=0.75, help="Aligned RMSD pass threshold")
    parser.add_argument("--bond-threshold", type=float, default=0.15, help="Bond-length delta threshold in angstrom")
    parser.add_argument("--angle-threshold", type=float, default=8.0, help="Angle delta threshold in degrees")
    parser.add_argument("--heavy-only", action="store_true", help="Use heavy atoms only for RMSD")
    parser.add_argument("--no-align", action="store_true", help="Disable Kabsch alignment before RMSD")
    parser.add_argument("--directional", action="store_true", help="Require forward=product and reverse=reactant")
    parser.add_argument(
        "--conformer-aware",
        action="store_true",
        help=(
            "For unimolecular conformer cases, report covalent graph identity as conservative "
            "ambiguous evidence when RMSD or conformation gates fail; never promotes to connected by itself."
        ),
    )
    parser.add_argument("--bond-scale", type=float, default=1.25, help="Covalent-radius scale for conformer-aware graph checks")
    parser.add_argument("-o", "--output-dir", required=True, help="Output directory")
    return parser


def _run(argv: list[str] | None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    bonds = [parse_bond(spec) for spec in args.bonds]
    angles = [parse_angle(spec) for spec in args.angles]
    outdir = Path(args.output_dir)
    outdir.mkdir(parents=True, exist_ok=True)

    structures = {
        "forward": read_structure(args.forward),
        "reverse": read_structure(args.reverse),
        "reactant": read_structure(args.reactant),
        "product": read_structure(args.product),
    }
    baseline = structures["reactant"]
    for name, structure in structures.items():
        ensure_compatible(baseline, structure, f"{name} vs reactant")
    natoms = len(baseline.atoms)
    validate_indices(natoms, bonds, angles)

    pair_results: dict[str, dict[str, dict[str, object]]] = {}
    covalent_pair_results: dict[str, dict[str, dict[str, object]]] = {}
    metric_rows: list[dict[str, object]] = []
    for endpoint_name in ("forward", "reverse"):
        pair_results[endpoint_name] = {}
        covalent_pair_results[endpoint_name] = {}
        for reference_name in ("reactant", "product"):
            result = pair_evaluation(
                endpoint_name,
                structures[endpoint_name],
                reference_name,
                structures[reference_name],
                bonds=bonds,
                angles=angles,
                rmsd_threshold=args.rmsd_threshold,
                bond_threshold=args.bond_threshold,
                angle_threshold=args.angle_threshold,
                heavy_only=args.heavy_only,
                align=not args.no_align,
            )
            pair_results[endpoint_name][reference_name] = result
            covalent_pair_results[endpoint_name][reference_name] = covalent_identity_evaluation(
                structures[endpoint_name],
                structures[reference_name],
                bond_scale=args.bond_scale,
            )
            metric_rows.extend(result["metric_rows"])  # type: ignore[arg-type]

    raw_assignments = [
        {"forward": "product", "reverse": "reactant", "label": "forward=product,reverse=reactant"},
    ]
    if not args.directional:
        raw_assignments.append(
            {"forward": "reactant", "reverse": "product", "label": "forward=reactant,reverse=product"}
        )

    assignment_rows: list[dict[str, object]] = []
    assignments: list[dict[str, object]] = []
    for assignment in raw_assignments:
        forward_ref = str(assignment["forward"])
        reverse_ref = str(assignment["reverse"])
        selected_pairs = [pair_results["forward"][forward_ref], pair_results["reverse"][reverse_ref]]
        selected_covalent_pairs = [
            covalent_pair_results["forward"][forward_ref],
            covalent_pair_results["reverse"][reverse_ref],
        ]
        passed = all(bool(pair["passed"]) for pair in selected_pairs)
        covalent_identity_passed = all(bool(pair["passed"]) for pair in selected_covalent_pairs)
        score = assignment_score(selected_pairs, args)
        row = {
            "assignment": assignment["label"],
            "forward_reference": forward_ref,
            "reverse_reference": reverse_ref,
            "score": score,
            "passed": passed,
            "covalent_identity_passed": covalent_identity_passed,
            "forward_rmsd": pair_results["forward"][forward_ref]["rmsd"],
            "reverse_rmsd": pair_results["reverse"][reverse_ref]["rmsd"],
        }
        assignment_rows.append(row)
        assignments.append({**row, "pairs": selected_pairs})

    selected = min(assignments, key=lambda item: float(item["score"]))
    connected = bool(selected["passed"])
    covalent_identity_assignments = [item for item in assignments if bool(item.get("covalent_identity_passed"))]
    selected_covalent_identity = min(covalent_identity_assignments, key=lambda item: float(item["score"])) if covalent_identity_assignments else None
    conformer_identity_supported = bool(args.conformer_aware and not connected and selected_covalent_identity)
    warnings: list[str] = []
    if not bonds and not angles:
        warnings.append("No key bonds or angles supplied; RMSD-only connectivity is weak evidence.")
    for name, structure in structures.items():
        if structure.metadata.get("format") == "gaussian" and structure.metadata.get("error_termination"):
            warnings.append(f"{name} comes from an error-terminated Gaussian log; prefer an extracted accepted endpoint XYZ.")
    if conformer_identity_supported:
        warnings.append(
            "Covalent identity matches one assignment but RMSD/internal-coordinate gates did not pass; "
            "treat as conformer_identity_supported, not endpoint_connected or accepted_ts."
        )

    summary = {
        "decision": "connected" if connected else ("conformer_identity_supported" if conformer_identity_supported else "not_connected"),
        "connectivity_supported": connected,
        "conformer_identity_supported": conformer_identity_supported,
        "selected_assignment": {
            key: selected[key]
            for key in ("assignment", "forward_reference", "reverse_reference", "score", "passed", "covalent_identity_passed", "forward_rmsd", "reverse_rmsd")
        },
        "selected_covalent_identity_assignment": (
            {
                key: selected_covalent_identity[key]
                for key in ("assignment", "forward_reference", "reverse_reference", "score", "passed", "covalent_identity_passed", "forward_rmsd", "reverse_rmsd")
            }
            if selected_covalent_identity
            else None
        ),
        "thresholds": {
            "rmsd": args.rmsd_threshold,
            "bond_angstrom": args.bond_threshold,
            "angle_degree": args.angle_threshold,
            "covalent_bond_scale": args.bond_scale,
        },
        "options": {
            "heavy_only_rmsd": args.heavy_only,
            "aligned_rmsd": not args.no_align,
            "directional": args.directional,
            "conformer_aware": args.conformer_aware,
        },
        "claim_suggestion": (
            {
                "claim_status": "endpoint_connected",
                "outcome": "connectivity_validated",
                "outcome_code": "endpoint_assignment_passed",
            }
            if connected
            else (
                {
                    "claim_status": "ambiguous",
                    "outcome": "wrong_endpoint",
                    "outcome_code": "conformer_identity_only",
                }
                if conformer_identity_supported
                else {
                    "claim_status": "rejected",
                    "outcome": "wrong_endpoint",
                    "outcome_code": "endpoint_assignment_failed",
                }
            )
        ),
        "atom_count": natoms,
        "structures": {
            name: dict(structure.metadata, path=structure.path)
            for name, structure in structures.items()
        },
        "key_bonds": [metric_label("bond", pair) for pair in bonds],
        "key_angles": [metric_label("angle", triple) for triple in angles],
        "rmsd_matrix": {
            endpoint: {reference: pair_results[endpoint][reference]["rmsd"] for reference in ("reactant", "product")}
            for endpoint in ("forward", "reverse")
        },
        "pair_pass": {
            endpoint: {
                reference: {
                    key: pair_results[endpoint][reference][key]
                    for key in ("rmsd_pass", "bond_pass", "angle_pass", "passed", "max_bond_delta_angstrom", "max_angle_delta_degree")
                }
                for reference in ("reactant", "product")
            }
            for endpoint in ("forward", "reverse")
        },
        "covalent_identity": {
            endpoint: {
                reference: covalent_pair_results[endpoint][reference]
                for reference in ("reactant", "product")
            }
            for endpoint in ("forward", "reverse")
        },
        "assignments": assignment_rows,
        "warnings": warnings,
    }

    write_csv(
        outdir / "pair_metrics.csv",
        metric_rows,
        ["endpoint", "reference", "metric_type", "metric", "endpoint_value", "reference_value", "difference", "threshold", "passed"],
    )
    write_csv(
        outdir / "assignment_scores.csv",
        assignment_rows,
        ["assignment", "forward_reference", "reverse_reference", "score", "passed", "covalent_identity_passed", "forward_rmsd", "reverse_rmsd"],
    )
    (outdir / "connectivity_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    emit_json(
        {
            "decision": summary["decision"],
            "assignment": selected["assignment"],
            "forward_rmsd": float(selected["forward_rmsd"]),
            "reverse_rmsd": float(selected["reverse_rmsd"]),
            "summary": str(outdir / "connectivity_summary.json"),
            "warnings": list(warnings),
        }
    )
    for warning in warnings:
        warn(warning)
    return 0 if connected else (3 if conformer_identity_supported else 2)


def main(argv: list[str] | None = None) -> int:
    return run_cli(_run, argv)


if __name__ == "__main__":
    raise SystemExit(main())
