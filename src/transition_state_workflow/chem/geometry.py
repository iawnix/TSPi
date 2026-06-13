"""Small geometry utilities used by TS-search tooling."""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path


COVALENT_RADII = {
    "H": 0.31,
    "B": 0.84,
    "C": 0.76,
    "N": 0.71,
    "O": 0.66,
    "F": 0.57,
    "Si": 1.11,
    "P": 1.07,
    "S": 1.05,
    "Cl": 1.02,
    "Br": 1.20,
    "I": 1.39,
    "Li": 1.28,
    "Na": 1.66,
    "K": 2.03,
    "Mg": 1.41,
    "Ca": 1.76,
    "Fe": 1.32,
    "Co": 1.26,
    "Ni": 1.24,
    "Cu": 1.32,
    "Zn": 1.22,
    "Pd": 1.39,
    "Ag": 1.45,
    "Pt": 1.36,
    "Au": 1.36,
}


@dataclass(frozen=True)
class Atom:
    """Cartesian atom record in Angstrom."""

    element: str
    x: float
    y: float
    z: float


def read_xyz(path: Path) -> list[Atom]:
    """Read a single-frame XYZ file into a list of :class:`Atom`."""

    lines = path.read_text(encoding="utf-8").splitlines()
    natoms = int(lines[0].strip())
    atoms: list[Atom] = []
    for line in lines[2 : 2 + natoms]:
        element, x, y, z = line.split()[:4]
        atoms.append(Atom(element, float(x), float(y), float(z)))
    if len(atoms) != natoms:
        raise ValueError(f"XYZ atom count mismatch in {path}")
    return atoms


def vector_norm(vector: tuple[float, float, float]) -> float:
    """Return the Euclidean norm of a 3D vector."""

    return math.sqrt(vector[0] ** 2 + vector[1] ** 2 + vector[2] ** 2)


def distance(a: Atom, b: Atom) -> float:
    """Return interatomic distance in Angstrom."""

    return math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2 + (a.z - b.z) ** 2)


def bond_set(atoms: list[Atom], scale: float = 1.25) -> set[tuple[int, int]]:
    """Infer a simple covalent-radius bond set using 1-based atom indices."""

    bonds: set[tuple[int, int]] = set()
    for i, atom_i in enumerate(atoms):
        radius_i = COVALENT_RADII.get(atom_i.element, 0.77)
        for j in range(i + 1, len(atoms)):
            atom_j = atoms[j]
            radius_j = COVALENT_RADII.get(atom_j.element, 0.77)
            if distance(atom_i, atom_j) <= scale * (radius_i + radius_j):
                bonds.add((i + 1, j + 1))
    return bonds


def bond_labels(bonds: set[tuple[int, int]], atoms: list[Atom]) -> list[str]:
    """Return stable human-readable labels for a bond set."""

    return [
        f"{i}:{atoms[i - 1].element}-{j}:{atoms[j - 1].element}"
        for i, j in sorted(bonds)
    ]


def write_xyz(path: Path, atoms: list[Atom], comment: str) -> None:
    """Write a single-frame XYZ file."""

    lines = [str(len(atoms)), comment]
    for atom in atoms:
        lines.append(f"{atom.element:<3s} {atom.x:16.8f} {atom.y:16.8f} {atom.z:16.8f}")
    lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def append_xyz_frame(lines: list[str], atoms: list[Atom], comment: str) -> None:
    """Append one XYZ frame to an in-memory multi-frame XYZ buffer."""

    lines.extend([str(len(atoms)), comment])
    for atom in atoms:
        lines.append(f"{atom.element:<3s} {atom.x:16.8f} {atom.y:16.8f} {atom.z:16.8f}")
