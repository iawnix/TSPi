"""Extract compact descriptors from a Gaussian TS/frequency result."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from transition_state_workflow.backends.gaussian import (
    parse_charge_multiplicity,
    parse_charge_table,
    parse_freq_metadata,
    parse_frontier_orbitals,
    parse_imaginary_vectors,
    parse_last_dipole,
    parse_last_mulliken,
    parse_last_scf_energy,
)
from transition_state_workflow.chem.gaussian_log import terminated_normally
from transition_state_workflow.chem.geometry import (
    Atom,
    COVALENT_RADII,
    angle_degrees as angle,
    dihedral_degrees as dihedral,
    distance,
    dot,
    read_xyz,
    vector,
    vector_norm as norm,
)
from transition_state_workflow.tools.contracts import ToolCapability, ToolRequest, ToolResult
from transition_state_workflow.util.cli import CliError, emit_json, run_cli


@dataclass(frozen=True)
class DescriptorExtractionRequest:
    """Resolved request for Gaussian TS descriptor extraction."""

    ts_out: Path
    ts_xyz: Path
    minus_xyz: Path
    plus_xyz: Path
    output_dir: Path
    pairs: tuple[str, ...] = ()
    focus_atoms: tuple[str, ...] = ()
    center_index: int | None = None
    angles: tuple[str, ...] = ()
    dihedrals: tuple[str, ...] = ()
    bond_scale: float = 1.25


@dataclass(frozen=True)
class DescriptorExtractionResult:
    """Descriptor extraction result and evidence-bearing artifacts."""

    payload: dict[str, object]
    artifacts: tuple[Path, ...]
    descriptor: dict[str, object]


class TSDescriptorExtractionTool:
    """ChemTool adapter for Gaussian TS/frequency descriptor extraction."""

    name = "ts-descriptor-extract"
    capabilities = frozenset({ToolCapability.DESCRIPTOR_ANALYSIS})

    def run(self, request: ToolRequest) -> ToolResult:
        if request.capability != ToolCapability.DESCRIPTOR_ANALYSIS:
            raise ValueError("ts-descriptor-extract only supports descriptor_analysis requests")
        descriptor_request = descriptor_request_from_mapping(request.parameters)
        result = extract_ts_descriptors(descriptor_request)
        return ToolResult(
            tool_name=self.name,
            capability=ToolCapability.DESCRIPTOR_ANALYSIS,
            ok=True,
            artifacts=result.artifacts,
            properties=result.payload,
        )


def _path_parameter(parameters: Mapping[str, Any], name: str) -> Path:
    value = parameters.get(name)
    if value is None:
        raise ValueError(f"descriptor extraction requires parameter {name!r}")
    return Path(str(value))


def _string_tuple_parameter(parameters: Mapping[str, Any], name: str) -> tuple[str, ...]:
    value = parameters.get(name, ())
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(item) for item in value)


def descriptor_request_from_mapping(parameters: object) -> DescriptorExtractionRequest:
    if not isinstance(parameters, Mapping):
        raise ValueError("descriptor extraction parameters must be a mapping")
    center_index_value = parameters.get("center_index")
    return DescriptorExtractionRequest(
        ts_out=_path_parameter(parameters, "ts_out"),
        ts_xyz=_path_parameter(parameters, "ts_xyz"),
        minus_xyz=_path_parameter(parameters, "minus_xyz"),
        plus_xyz=_path_parameter(parameters, "plus_xyz"),
        output_dir=_path_parameter(parameters, "output_dir"),
        pairs=_string_tuple_parameter(parameters, "pairs"),
        focus_atoms=_string_tuple_parameter(parameters, "focus_atoms"),
        center_index=int(center_index_value) if center_index_value not in (None, "") else None,
        angles=_string_tuple_parameter(parameters, "angles"),
        dihedrals=_string_tuple_parameter(parameters, "dihedrals"),
        bond_scale=float(parameters.get("bond_scale", 1.25)),
    )


def formula(atoms: list[Atom]) -> str:
    counts = Counter(atom.element for atom in atoms)
    order = ["C", "H", "N", "O"]
    parts = []
    for element in order:
        if element in counts:
            value = counts.pop(element)
            parts.append(element if value == 1 else f"{element}{value}")
    for element in sorted(counts):
        value = counts[element]
        parts.append(element if value == 1 else f"{element}{value}")
    return "".join(parts)


def pair_key(pair: tuple[int, int], atoms: list[Atom]) -> str:
    i, j = pair
    return f"{i}:{atoms[i - 1].element}-{j}:{atoms[j - 1].element}"


def atom_key(index: int, atoms: list[Atom]) -> str:
    return f"{index}:{atoms[index - 1].element}"


def parse_index_group(text: str, expected: int) -> tuple[int, ...]:
    parts = tuple(int(part) for part in text.split("-"))
    if len(parts) != expected:
        raise ValueError(f"Expected {expected} atom indices in {text!r}")
    return parts


def scaled_mode_distances(atoms: list[Atom], minus_atoms: list[Atom], plus_atoms: list[Atom], pairs: list[tuple[int, int]]) -> list[dict[str, object]]:
    rows = []
    for pair in pairs:
        i, j = pair
        ts_d = distance(atoms[i - 1], atoms[j - 1])
        minus_d = distance(minus_atoms[i - 1], minus_atoms[j - 1])
        plus_d = distance(plus_atoms[i - 1], plus_atoms[j - 1])
        rows.append(
            {
                "pair": pair_key(pair, atoms),
                "ts_distance_angstrom": ts_d,
                "minus_scaled_distance_angstrom": minus_d,
                "plus_scaled_distance_angstrom": plus_d,
                "plus_minus_delta_angstrom": plus_d - minus_d,
                "plus_minus_delta_percent_of_ts": 100.0 * (plus_d - minus_d) / ts_d if ts_d else None,
            }
        )
    return rows


def mode_pair_derivatives(atoms: list[Atom], vectors: list[tuple[float, float, float]], pairs: list[tuple[int, int]]) -> list[dict[str, object]]:
    rows = []
    for pair in pairs:
        i, j = pair
        a = atoms[i - 1]
        b = atoms[j - 1]
        rij = vector(a, b)
        rij_norm = norm(rij)
        if rij_norm == 0:
            projection = float("nan")
        else:
            unit = (rij[0] / rij_norm, rij[1] / rij_norm, rij[2] / rij_norm)
            dv = tuple(vectors[j - 1][k] - vectors[i - 1][k] for k in range(3))
            projection = dot(dv, unit)
        rows.append(
            {
                "pair": pair_key(pair, atoms),
                "mode_distance_derivative_arbitrary_units": projection,
                "interpretation": "positive mode sign lengthens this distance" if projection > 0 else "positive mode sign shortens this distance",
            }
        )
    return rows


def coordination_shell(atoms: list[Atom], center_index: int, scale: float) -> list[dict[str, object]]:
    center = atoms[center_index - 1]
    rows = []
    for idx, atom in enumerate(atoms, start=1):
        if idx == center_index or atom.element == "H":
            continue
        cutoff = scale * (COVALENT_RADII.get(center.element, 0.77) + COVALENT_RADII.get(atom.element, 0.77))
        d = distance(center, atom)
        rows.append(
            {
                "atom": f"{idx}:{atom.element}",
                "distance_angstrom": d,
                "covalent_cutoff_angstrom": cutoff,
                "within_cutoff": d <= cutoff,
            }
        )
    rows.sort(key=lambda row: row["distance_angstrom"])
    return rows


def focus_charge_dict(atoms: list[Atom], charges: dict[int, float], focus_atoms: set[int]) -> dict[str, float | None]:
    return {atom_key(index, atoms): charges.get(index) for index in sorted(focus_atoms)}


def angle_descriptors(atoms: list[Atom], angle_specs: list[tuple[int, int, int]]) -> dict[str, float]:
    out: dict[str, float] = {}
    for i, j, k in angle_specs:
        key = f"{atom_key(i, atoms)}-{atom_key(j, atoms)}-{atom_key(k, atoms)}"
        out[key] = angle(atoms[i - 1], atoms[j - 1], atoms[k - 1])
    return out


def dihedral_descriptors(atoms: list[Atom], dihedral_specs: list[tuple[int, int, int, int]]) -> dict[str, float]:
    out: dict[str, float] = {}
    for i, j, k, l in dihedral_specs:
        key = f"{atom_key(i, atoms)}-{atom_key(j, atoms)}-{atom_key(k, atoms)}-{atom_key(l, atoms)}"
        out[key] = dihedral(atoms[i - 1], atoms[j - 1], atoms[k - 1], atoms[l - 1])
    return out


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ts-out", type=Path, required=True)
    parser.add_argument("--ts-xyz", type=Path, required=True)
    parser.add_argument("--minus-xyz", type=Path, required=True)
    parser.add_argument("--plus-xyz", type=Path, required=True)
    parser.add_argument("-o", "--output-dir", type=Path, required=True)
    parser.add_argument("--pairs", nargs="*", default=[], help="Reaction-center atom pairs, e.g. 1-23 1-54 23-54.")
    parser.add_argument("--focus-atoms", nargs="*", default=[], help="Atom indices to include in the compact charge summary.")
    parser.add_argument("--center-index", type=int, help="Optional coordination center atom index.")
    parser.add_argument("--angles", nargs="*", default=[], help="Optional angle descriptors as i-j-k atom indices.")
    parser.add_argument("--dihedrals", nargs="*", default=[], help="Optional dihedral descriptors as i-j-k-l atom indices.")
    parser.add_argument("--bond-scale", type=float, default=1.25)
    return parser


def descriptor_request_from_args(args: argparse.Namespace) -> DescriptorExtractionRequest:
    return DescriptorExtractionRequest(
        ts_out=args.ts_out,
        ts_xyz=args.ts_xyz,
        minus_xyz=args.minus_xyz,
        plus_xyz=args.plus_xyz,
        output_dir=args.output_dir,
        pairs=tuple(args.pairs),
        focus_atoms=tuple(args.focus_atoms),
        center_index=args.center_index,
        angles=tuple(args.angles),
        dihedrals=tuple(args.dihedrals),
        bond_scale=args.bond_scale,
    )


def extract_ts_descriptors(request: DescriptorExtractionRequest) -> DescriptorExtractionResult:
    """Extract descriptor artifacts without mutating scientific workspace state."""

    lines = request.ts_out.read_text(encoding="utf-8", errors="replace").splitlines()
    atoms = read_xyz(request.ts_xyz)
    minus_atoms = read_xyz(request.minus_xyz)
    plus_atoms = read_xyz(request.plus_xyz)
    pairs = [parse_index_group(item, 2) for item in request.pairs]
    angle_specs = [parse_index_group(item, 3) for item in request.angles]
    dihedral_specs = [parse_index_group(item, 4) for item in request.dihedrals]
    focus_atoms = {int(item) for item in request.focus_atoms}
    for pair in pairs:
        focus_atoms.update(pair)
    if request.center_index:
        focus_atoms.add(request.center_index)
    vectors = parse_imaginary_vectors(lines, len(atoms))
    vector_norms = [norm(vector) for vector in vectors]
    norm2_sum = sum(value * value for value in vector_norms)
    charges = parse_last_mulliken(lines)
    mulliken_h_summed = parse_charge_table(
        lines,
        "Mulliken charges with hydrogens summed into heavy atoms:",
    )
    apt_charges = parse_charge_table(lines, "APT charges:", "Sum of APT charges")
    apt_h_summed = parse_charge_table(
        lines,
        "APT charges with hydrogens summed into heavy atoms:",
    )

    mode_rows = []
    for idx, (atom, vec_norm) in enumerate(zip(atoms, vector_norms), start=1):
        mode_rows.append(
            {
                "atom_index": idx,
                "element": atom.element,
                "mode_vector_norm": vec_norm,
                "mode_participation_percent": 100.0 * vec_norm * vec_norm / norm2_sum if norm2_sum else 0.0,
                "mulliken_charge": charges.get(idx),
            }
        )
    mode_rows.sort(key=lambda row: row["mode_participation_percent"], reverse=True)

    charge, multiplicity = parse_charge_multiplicity(lines)
    freq_metadata = parse_freq_metadata(lines)
    key_distances = scaled_mode_distances(atoms, minus_atoms, plus_atoms, pairs)
    pair_derivatives = mode_pair_derivatives(atoms, vectors, pairs)
    shell = (
        coordination_shell(atoms, request.center_index, request.bond_scale)
        if request.center_index
        else []
    )

    descriptor = {
        "source": {
            "ts_out": str(request.ts_out),
            "ts_xyz": str(request.ts_xyz),
            "minus_xyz": str(request.minus_xyz),
            "plus_xyz": str(request.plus_xyz),
        },
        "validation": {
            "normal_termination": terminated_normally(lines),
            "stationary_point_found": any("Stationary point found" in line for line in lines),
            **freq_metadata,
        },
        "system": {
            "natoms": len(atoms),
            "formula": formula(atoms),
            "charge": charge,
            "multiplicity": multiplicity,
            "final_scf_energy_hartree": parse_last_scf_energy(lines),
            "dipole": parse_last_dipole(lines),
            "frontier_orbitals": parse_frontier_orbitals(lines),
        },
        "reaction_center": {
            "tracked_pairs": key_distances,
            "imaginary_mode_pair_derivatives": pair_derivatives,
            "angles_degrees": angle_descriptors(atoms, angle_specs),
            "dihedral_degrees": dihedral_descriptors(atoms, dihedral_specs),
            "mulliken_charges": focus_charge_dict(atoms, charges, focus_atoms),
            "mulliken_h_summed_charges": focus_charge_dict(atoms, mulliken_h_summed, focus_atoms),
            "apt_charges": focus_charge_dict(atoms, apt_charges, focus_atoms),
            "apt_h_summed_charges": focus_charge_dict(atoms, apt_h_summed, focus_atoms),
        },
        "coordination": {
            "center": atom_key(request.center_index, atoms) if request.center_index else None,
            "bond_scale": request.bond_scale,
            "within_cutoff": [row for row in shell if row["within_cutoff"]],
            "nearest_heavy_atoms": shell[:12],
        },
        "imaginary_mode": {
            "top_atom_participation": mode_rows[:15],
            "focus_atom_participation_percent": sum(
                mode_rows_item["mode_participation_percent"]
                for mode_rows_item in mode_rows
                if mode_rows_item["atom_index"] in focus_atoms
            ),
        },
    }

    request.output_dir.mkdir(parents=True, exist_ok=True)
    descriptor_path = request.output_dir / "ts_descriptors.json"
    distances_path = request.output_dir / "reaction_center_distances.csv"
    mode_path = request.output_dir / "mode_participation.csv"
    charges_path = request.output_dir / "atomic_charges.csv"
    descriptor_path.write_text(json.dumps(descriptor, indent=2), encoding="utf-8")

    with distances_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "pair",
                "ts_distance_angstrom",
                "minus_scaled_distance_angstrom",
                "plus_scaled_distance_angstrom",
                "plus_minus_delta_angstrom",
                "plus_minus_delta_percent_of_ts",
            ],
        )
        writer.writeheader()
        writer.writerows(key_distances)

    with mode_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(mode_rows[0].keys()))
        writer.writeheader()
        writer.writerows(mode_rows)

    charge_rows = []
    all_indices = sorted(set(charges) | set(mulliken_h_summed) | set(apt_charges) | set(apt_h_summed))
    for idx in all_indices:
        atom = atoms[idx - 1]
        charge_rows.append(
            {
                "atom_index": idx,
                "element": atom.element,
                "mulliken": charges.get(idx),
                "mulliken_h_summed": mulliken_h_summed.get(idx),
                "apt": apt_charges.get(idx),
                "apt_h_summed": apt_h_summed.get(idx),
            }
        )
    with charges_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(charge_rows[0].keys()))
        writer.writeheader()
        writer.writerows(charge_rows)

    payload = {
        "validation": descriptor["validation"],
        "system": descriptor["system"],
        "tracked_pairs": key_distances,
        "reaction_center_charges": {
            "mulliken": descriptor["reaction_center"]["mulliken_charges"],
            "mulliken_h_summed": descriptor["reaction_center"]["mulliken_h_summed_charges"],
            "apt": descriptor["reaction_center"]["apt_charges"],
            "apt_h_summed": descriptor["reaction_center"]["apt_h_summed_charges"],
        },
        "top_mode_atoms": mode_rows[:8],
        "outputs": {
            "json": str(descriptor_path),
            "distances_csv": str(distances_path),
            "mode_csv": str(mode_path),
            "charges_csv": str(charges_path),
        },
    }
    return DescriptorExtractionResult(
        payload=payload,
        artifacts=(descriptor_path, distances_path, mode_path, charges_path),
        descriptor=descriptor,
    )


def _run(argv: list[str] | None) -> int:
    args = build_parser().parse_args(argv)
    result = extract_ts_descriptors(descriptor_request_from_args(args))
    emit_json(result.payload)
    return 0


def _run_translated(argv: list[str] | None) -> int:
    try:
        return _run(argv)
    except ValueError as exc:
        # Malformed --pairs/--angles specs and bad XYZ files raise ValueError;
        # surface them as a tidy CLI error envelope instead of a traceback.
        raise CliError(str(exc)) from exc


def main(argv: list[str] | None = None) -> int:
    return run_cli(_run_translated, argv)


if __name__ == "__main__":
    raise SystemExit(main())
