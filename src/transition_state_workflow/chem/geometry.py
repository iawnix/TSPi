"""Small geometry utilities used by TS-search tooling."""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import re


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


def vector(a: Atom, b: Atom) -> tuple[float, float, float]:
    """Return the vector from atom ``a`` to atom ``b``."""

    return (b.x - a.x, b.y - a.y, b.z - a.z)


def dot(u: tuple[float, float, float], v: tuple[float, float, float]) -> float:
    """Return the dot product of two 3D vectors."""

    return u[0] * v[0] + u[1] * v[1] + u[2] * v[2]


def cross(u: tuple[float, float, float], v: tuple[float, float, float]) -> tuple[float, float, float]:
    """Return the cross product of two 3D vectors."""

    return (
        u[1] * v[2] - u[2] * v[1],
        u[2] * v[0] - u[0] * v[2],
        u[0] * v[1] - u[1] * v[0],
    )


def distance(a: Atom, b: Atom) -> float:
    """Return interatomic distance in Angstrom."""

    return math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2 + (a.z - b.z) ** 2)


def angle_degrees(a: Atom, b: Atom, c: Atom) -> float:
    """Return the angle a-b-c in degrees."""

    ba = vector(b, a)
    bc = vector(b, c)
    denom = vector_norm(ba) * vector_norm(bc)
    if denom == 0:
        return float("nan")
    value = max(-1.0, min(1.0, dot(ba, bc) / denom))
    return math.degrees(math.acos(value))


def dihedral_degrees(a: Atom, b: Atom, c: Atom, d: Atom) -> float:
    """Return the dihedral angle a-b-c-d in degrees."""

    b0 = vector(b, a)
    b1 = vector(b, c)
    b2 = vector(c, d)
    b1_norm = vector_norm(b1)
    if b1_norm == 0:
        return float("nan")
    b1u = (b1[0] / b1_norm, b1[1] / b1_norm, b1[2] / b1_norm)
    v = tuple(b0[i] - dot(b0, b1u) * b1u[i] for i in range(3))
    w = tuple(b2[i] - dot(b2, b1u) * b1u[i] for i in range(3))
    x = dot(v, w)
    y = dot(cross(b1u, v), w)
    return math.degrees(math.atan2(y, x))


def parse_bond_spec(spec: str) -> tuple[int, int]:
    """Parse a 1-based bond spec like ``1-2``, ``1:2``, or ``1,2``."""

    parts = re.split(r"[-:,]", spec.strip())
    if len(parts) != 2:
        raise ValueError(f"invalid bond spec '{spec}', expected i-j")
    i, j = int(parts[0]), int(parts[1])
    if i < 1 or j < 1 or i == j:
        raise ValueError(f"invalid bond spec '{spec}'")
    return tuple(sorted((i, j)))


def parse_angle_spec(spec: str) -> tuple[int, int, int]:
    """Parse a 1-based angle spec like ``1-2-3``, ``1:2:3``, or ``1,2,3``."""

    parts = re.split(r"[-:,]", spec.strip())
    if len(parts) != 3:
        raise ValueError(f"invalid angle spec '{spec}', expected i-j-k")
    i, j, k = (int(part) for part in parts)
    if min(i, j, k) < 1 or len({i, j, k}) != 3:
        raise ValueError(f"invalid angle spec '{spec}'")
    return i, j, k


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
