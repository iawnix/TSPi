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


def read_xyz_with_comment(path: Path) -> tuple[list[Atom], str]:
    """Read a single-frame XYZ file and return atoms plus the comment line."""

    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        raise ValueError(f"empty XYZ file: {path}")
    try:
        natoms = int(lines[0].strip())
    except ValueError as exc:
        raise ValueError(f"invalid XYZ atom count in {path}") from exc
    if len(lines) < natoms + 2:
        raise ValueError(f"XYZ file has too few coordinate lines: {path}")
    comment = lines[1] if len(lines) > 1 else ""
    atoms: list[Atom] = []
    for line in lines[2: 2 + natoms]:
        parts = line.split()
        if len(parts) < 4:
            raise ValueError(f"invalid XYZ coordinate line: {line}")
        element, x, y, z = parts[:4]
        atoms.append(Atom(element, float(x), float(y), float(z)))
    return atoms, comment


def read_xyz(path: Path) -> list[Atom]:
    """Read a single-frame XYZ file into a list of :class:`Atom`."""

    atoms, _ = read_xyz_with_comment(path)
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


def bond_label(bond: tuple[int, int]) -> str:
    """Return a compact 1-based bond label."""

    return f"{bond[0]}-{bond[1]}"


def angle_label(angle: tuple[int, int, int]) -> str:
    """Return a compact 1-based angle label."""

    return f"{angle[0]}-{angle[1]}-{angle[2]}"


def covalent_cutoff(a: Atom, b: Atom, scale: float = 1.25) -> float:
    """Return a covalent-radius distance cutoff for two atoms."""

    ra = COVALENT_RADII.get(a.element, 0.77)
    rb = COVALENT_RADII.get(b.element, 0.77)
    return scale * (ra + rb)


def bonded_pairs(atoms: list[Atom], *, scale: float = 1.25) -> set[tuple[int, int]]:
    """Infer covalent-radius bonded pairs using 1-based atom indices."""

    pairs: set[tuple[int, int]] = set()
    for i, atom_i in enumerate(atoms, start=1):
        for j, atom_j in enumerate(atoms[i:], start=i + 1):
            if distance(atom_i, atom_j) <= covalent_cutoff(atom_i, atom_j, scale=scale):
                pairs.add((i, j))
    return pairs


def bond_set(atoms: list[Atom], scale: float = 1.25) -> set[tuple[int, int]]:
    """Infer a simple covalent-radius bond set using 1-based atom indices."""

    return bonded_pairs(atoms, scale=scale)


def changed_bonds(
    reactant: list[Atom],
    product: list[Atom],
    *,
    user_bonds: list[tuple[int, int]] | None = None,
) -> dict[str, list[tuple[int, int]]]:
    """Return user-specified, formed, and broken bonds between two structures."""

    if user_bonds:
        return {"user": sorted(set(user_bonds)), "formed": [], "broken": []}
    r_pairs = bonded_pairs(reactant)
    p_pairs = bonded_pairs(product)
    formed = sorted(p_pairs - r_pairs)
    broken = sorted(r_pairs - p_pairs)
    changed = sorted(set(formed) | set(broken))
    if changed:
        return {"user": [], "formed": formed, "broken": broken}

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
    """Return a covalent-radius neighbor map keyed by 1-based atom index."""

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
    """Infer local reaction-center angles from endpoint connectivity."""

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
            k = next((idx for idx in range(1, len(reactant) + 1) if idx not in {i, j}), None)
            if k:
                angles.add((i, j, k))
    return sorted(angles)[:12]


def atom_indices_from_bonds_angles(
    bonds: list[tuple[int, int]],
    angles: list[tuple[int, int, int]],
) -> list[int]:
    """Return sorted unique atom indices present in bond and angle specs."""

    indices: set[int] = set()
    for bond in bonds:
        indices.update(bond)
    for angle in angles:
        indices.update(angle)
    return sorted(indices)


def fragment_labels(atoms: list[Atom]) -> list[str]:
    """Return formula-plus-indices labels for covalent connected components."""

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
