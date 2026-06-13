"""Geometry and connectivity heuristics for NEB candidate generation.

Pure functions over the canonical :class:`chem.geometry.Atom` value object: XYZ
parsing, covalent-radius bond inference, reaction-center bond/angle changes, and
fragment labelling. No workspace or ASE state lives here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from transition_state_workflow.chem.geometry import (
    Atom,
    distance,
    parse_angle_spec as parse_geometry_angle_spec,
    parse_bond_spec as parse_geometry_bond_spec,
)
from transition_state_workflow.tool.ase_neb.constants import COVALENT_RADII
from transition_state_workflow.tool.ase_neb.errors import ConfigError


def read_xyz(path: Path) -> tuple[list[Atom], str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        raise ConfigError(f"empty XYZ file: {path}")
    try:
        natoms = int(lines[0].strip())
    except ValueError as exc:
        raise ConfigError(f"invalid XYZ atom count in {path}") from exc
    if len(lines) < natoms + 2:
        raise ConfigError(f"XYZ file has too few coordinate lines: {path}")
    comment = lines[1] if len(lines) > 1 else ""
    atoms: list[Atom] = []
    for line in lines[2 : 2 + natoms]:
        parts = line.split()
        if len(parts) < 4:
            raise ConfigError(f"invalid XYZ coordinate line: {line}")
        atoms.append(Atom(parts[0], float(parts[1]), float(parts[2]), float(parts[3])))
    return atoms, comment


def parse_bond_spec(spec: str) -> tuple[int, int]:
    try:
        return parse_geometry_bond_spec(spec)
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc


def parse_angle_spec(spec: str) -> tuple[int, int, int]:
    try:
        return parse_geometry_angle_spec(spec)
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc


def bond_label(bond: tuple[int, int]) -> str:
    return f"{bond[0]}-{bond[1]}"


def angle_label(angle: tuple[int, int, int]) -> str:
    return f"{angle[0]}-{angle[1]}-{angle[2]}"


def covalent_cutoff(a: Atom, b: Atom, scale: float = 1.25) -> float:
    ra = COVALENT_RADII.get(a.element, 0.77)
    rb = COVALENT_RADII.get(b.element, 0.77)
    return scale * (ra + rb)


def bonded_pairs(atoms: list[Atom], *, scale: float = 1.25) -> set[tuple[int, int]]:
    pairs: set[tuple[int, int]] = set()
    for i, atom_i in enumerate(atoms, start=1):
        for j, atom_j in enumerate(atoms[i:], start=i + 1):
            if distance(atom_i, atom_j) <= covalent_cutoff(atom_i, atom_j, scale=scale):
                pairs.add((i, j))
    return pairs


def changed_bonds(
    reactant: list[Atom],
    product: list[Atom],
    *,
    user_bonds: list[tuple[int, int]] | None = None,
) -> dict[str, list[tuple[int, int]]]:
    if user_bonds:
        return {"user": sorted(set(user_bonds)), "formed": [], "broken": []}
    r_pairs = bonded_pairs(reactant)
    p_pairs = bonded_pairs(product)
    formed = sorted(p_pairs - r_pairs)
    broken = sorted(r_pairs - p_pairs)
    changed = sorted(set(formed) | set(broken))
    if changed:
        return {"user": [], "formed": formed, "broken": broken}

    # Fallback for loose contacts or partial bond-order changes: keep the
    # largest covalent-radius-normalized distance changes.
    scored: list[tuple[float, tuple[int, int]]] = []
    for i, atom_i in enumerate(reactant, start=1):
        for j, atom_j in enumerate(reactant[i:], start=i + 1):
            r_dist = distance(atom_i, atom_j)
            p_dist = distance(product[i - 1], product[j - 1])
            scale = max(covalent_cutoff(atom_i, atom_j), 0.1)
            score = abs(p_dist - r_dist) / scale
            if score >= 0.20:
                scored.append((score, (i, j)))
    return {"user": [bond for _, bond in sorted(scored, reverse=True)[:6]], "formed": [], "broken": []}


def neighbor_map(atoms: list[Atom]) -> dict[int, set[int]]:
    pairs = bonded_pairs(atoms)
    neighbors: dict[int, set[int]] = {i: set() for i in range(1, len(atoms) + 1)}
    for i, j in pairs:
        neighbors[i].add(j)
        neighbors[j].add(i)
    return neighbors


def infer_angles(
    reactant: list[Atom],
    product: list[Atom],
    bonds: list[tuple[int, int]],
    *,
    user_angles: list[tuple[int, int, int]] | None = None,
) -> list[tuple[int, int, int]]:
    if user_angles:
        return sorted(set(user_angles))
    r_neighbors = neighbor_map(reactant)
    p_neighbors = neighbor_map(product)
    angles: set[tuple[int, int, int]] = set()
    for i, j in bonds:
        for center, edge in ((i, j), (j, i)):
            neighbors = (r_neighbors.get(center, set()) | p_neighbors.get(center, set())) - {edge}
            for other in sorted(neighbors):
                angles.add((other, center, edge))
        if not angles and len(reactant) >= 3:
            # Keep at least one local angle when connectivity inference is weak.
            k = next((idx for idx in range(1, len(reactant) + 1) if idx not in {i, j}), None)
            if k:
                angles.add((i, j, k))
    return sorted(angles)[:12]


def atom_indices_from_bonds_angles(
    bonds: list[tuple[int, int]],
    angles: list[tuple[int, int, int]],
) -> list[int]:
    indices: set[int] = set()
    for bond in bonds:
        indices.update(bond)
    for angle in angles:
        indices.update(angle)
    return sorted(indices)


def xyz_atoms_from_ase(atoms: Any) -> list[Atom]:
    symbols = atoms.get_chemical_symbols()
    positions = atoms.get_positions()
    return [
        Atom(symbol, float(position[0]), float(position[1]), float(position[2]))
        for symbol, position in zip(symbols, positions)
    ]


def fragment_labels(atoms: list[Atom]) -> list[str]:
    neighbors = neighbor_map(atoms)
    seen: set[int] = set()
    fragments: list[list[int]] = []
    for start in range(1, len(atoms) + 1):
        if start in seen:
            continue
        stack = [start]
        seen.add(start)
        component: list[int] = []
        while stack:
            current = stack.pop()
            component.append(current)
            for neighbor in sorted(neighbors[current]):
                if neighbor not in seen:
                    seen.add(neighbor)
                    stack.append(neighbor)
        fragments.append(sorted(component))
    labels: list[str] = []
    for component in fragments:
        counts: dict[str, int] = {}
        for index in component:
            symbol = atoms[index - 1].element
            counts[symbol] = counts.get(symbol, 0) + 1
        formula = "".join(
            f"{symbol}{counts[symbol] if counts[symbol] > 1 else ''}"
            for symbol in sorted(counts)
        )
        labels.append(f"{formula}:{','.join(str(index) for index in component)}")
    return labels


__all__ = [
    "Atom",
    "read_xyz",
    "parse_bond_spec",
    "parse_angle_spec",
    "bond_label",
    "angle_label",
    "distance",
    "covalent_cutoff",
    "bonded_pairs",
    "changed_bonds",
    "neighbor_map",
    "infer_angles",
    "atom_indices_from_bonds_angles",
    "xyz_atoms_from_ase",
    "fragment_labels",
]
