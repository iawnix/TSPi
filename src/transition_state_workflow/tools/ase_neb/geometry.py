"""ASE NEB adapters over shared chemistry geometry helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from transition_state_workflow.chem import geometry as chem_geometry
from transition_state_workflow.tools.ase_neb.errors import ConfigError

Atom = chem_geometry.Atom
distance = chem_geometry.distance
bond_label = chem_geometry.bond_label
angle_label = chem_geometry.angle_label
covalent_cutoff = chem_geometry.covalent_cutoff
bonded_pairs = chem_geometry.bonded_pairs
changed_bonds = chem_geometry.changed_bonds
neighbor_map = chem_geometry.neighbor_map
infer_angles = chem_geometry.infer_angles
atom_indices_from_bonds_angles = chem_geometry.atom_indices_from_bonds_angles
fragment_labels = chem_geometry.fragment_labels


def read_xyz(path: Path) -> tuple[list[Atom], str]:
    """Read an XYZ file and adapt parser errors to ASE NEB config errors."""

    try:
        return chem_geometry.read_xyz_with_comment(path)
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc


def parse_bond_spec(spec: str) -> tuple[int, int]:
    try:
        return chem_geometry.parse_bond_spec(spec)
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc


def parse_angle_spec(spec: str) -> tuple[int, int, int]:
    try:
        return chem_geometry.parse_angle_spec(spec)
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc


def xyz_atoms_from_ase(atoms: Any) -> list[Atom]:
    symbols = atoms.get_chemical_symbols()
    positions = atoms.get_positions()
    return [
        Atom(symbol, float(position[0]), float(position[1]), float(position[2]))
        for symbol, position in zip(symbols, positions)
    ]


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
