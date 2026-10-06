"""Chemistry-owned calculation input format validators."""

from __future__ import annotations

import math
import re
from typing import Any

from research_compute.errors import ComputeContractError

IMPORT_FORMAT_SUFFIXES = {
    "gaussian_input": frozenset({".com", ".gjf"}),
    "xyz_structure": frozenset({".xyz"}),
    "xtb_control": frozenset({".inp"}),
}
ROLE_SUFFIXES = {
    "gjf": frozenset({".gjf", ".com"}),
    "xyz": frozenset({".xyz"}),
    "control": frozenset({".inp"}),
    "reactant": frozenset({".xyz"}),
    "product": frozenset({".xyz"}),
    "config": frozenset({".json"}),
}

def validate_import_content(
    artifact_format: str,
    content: str,
    charge: int | None,
    multiplicity: int | None,
) -> dict[str, Any]:
    if artifact_format == "xyz_structure":
        return _xyz_import_metadata(content, int(charge), int(multiplicity))
    if artifact_format == "gaussian_input":
        return _gaussian_import_metadata(content, int(charge), int(multiplicity))
    if not re.search(r"(?m)^\s*\$[A-Za-z]", content) or not re.search(
        r"(?mi)^\s*\$end\s*$", content
    ):
        raise ComputeContractError("xTB control input requires at least one $ block and a $end line")
    return {"format": "xtb_control"}

def _xyz_import_metadata(content: str, charge: int, multiplicity: int) -> dict[str, Any]:
    lines = content.splitlines()
    if len(lines) < 3:
        raise ComputeContractError("XYZ seed is too short")
    try:
        atom_count = int(lines[0].strip())
    except ValueError as exc:
        raise ComputeContractError("XYZ seed first line must be an atom count") from exc
    if not 1 <= atom_count <= 512:
        raise ComputeContractError("XYZ seed atom count must be from 1 to 512")
    if len(lines) < atom_count + 2 or any(line.strip() for line in lines[atom_count + 2 :]):
        raise ComputeContractError("XYZ seed must contain exactly one complete frame")
    atom_order: list[str] = []
    for index, line in enumerate(lines[2 : atom_count + 2], start=3):
        parts = line.split()
        if len(parts) < 4 or re.fullmatch(r"(?:[A-Za-z]{1,3}|[1-9][0-9]{0,2})", parts[0]) is None:
            raise ComputeContractError(f"XYZ seed has an invalid atom line {index}")
        try:
            coordinates = [float(value) for value in parts[1:4]]
        except ValueError as exc:
            raise ComputeContractError(f"XYZ seed has a non-numeric coordinate on line {index}") from exc
        if not all(math.isfinite(value) for value in coordinates):
            raise ComputeContractError(f"XYZ seed has a non-finite coordinate on line {index}")
        atom_order.append(parts[0])
    return {
        "format": "xyz",
        "charge": charge,
        "multiplicity": multiplicity,
        "atom_count": atom_count,
        "atom_order": atom_order,
    }

def _gaussian_import_metadata(content: str, charge: int, multiplicity: int) -> dict[str, Any]:
    lines = content.splitlines()
    route_index = next((index for index, line in enumerate(lines) if line.lstrip().startswith("#")), None)
    if route_index is None:
        raise ComputeContractError("Gaussian seed requires a route section")
    route_end = next(
        (index for index in range(route_index + 1, len(lines)) if not lines[index].strip()),
        len(lines),
    )
    route = " ".join(line.strip() for line in lines[route_index:route_end]).strip()
    if route in {"#", "#p", "#P"}:
        raise ComputeContractError("Gaussian seed route section cannot be empty")
    if any(re.fullmatch(r"\s*--Link1--\s*", line, flags=re.IGNORECASE) for line in lines):
        raise ComputeContractError("Gaussian seed must contain exactly one job; --Link1-- is not allowed")
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("%") and any(marker in stripped for marker in ("/", "\\", "..")):
            raise ComputeContractError("Gaussian Link 0 directives cannot select filesystem paths")

    qst_matches = {int(match.group(1)) for match in re.finditer(r"(?i)\bqst([23])\b", route)}
    if len(qst_matches) > 1:
        raise ComputeContractError("Gaussian seed route cannot request both QST2 and QST3")
    structure_count = next(iter(qst_matches), 1)
    structures: list[list[str]] = []
    cursor = route_end
    for structure_index in range(1, structure_count + 1):
        cursor = _skip_blank_lines(lines, cursor)
        title_start = cursor
        while cursor < len(lines) and lines[cursor].strip():
            cursor += 1
        if cursor == title_start:
            raise ComputeContractError(
                f"Gaussian seed requires title section {structure_index} of {structure_count}"
            )
        cursor = _skip_blank_lines(lines, cursor)
        atom_order, cursor = _gaussian_cartesian_structure(
            lines,
            cursor,
            charge,
            multiplicity,
            structure_index,
            structure_count,
        )
        structures.append(atom_order)

    atom_order = structures[0]
    for structure_index, candidate in enumerate(structures[1:], start=2):
        if len(candidate) != len(atom_order):
            raise ComputeContractError(
                f"Gaussian QST structure {structure_index} atom count does not match structure 1"
            )
        if candidate != atom_order:
            raise ComputeContractError(
                f"Gaussian QST structure {structure_index} atom order does not match structure 1"
            )
    return {
        "format": "gaussian_input",
        "charge": charge,
        "multiplicity": multiplicity,
        "structure_count": structure_count,
        "atom_count": len(atom_order),
        "atom_order": atom_order,
        "route": route,
    }

def _skip_blank_lines(lines: list[str], cursor: int) -> int:
    while cursor < len(lines) and not lines[cursor].strip():
        cursor += 1
    return cursor

def _gaussian_cartesian_structure(
    lines: list[str],
    cursor: int,
    charge: int,
    multiplicity: int,
    structure_index: int,
    structure_count: int,
) -> tuple[list[str], int]:
    if cursor >= len(lines):
        raise ComputeContractError(
            f"Gaussian seed requires charge and multiplicity for structure "
            f"{structure_index} of {structure_count}"
        )
    charge_line = re.fullmatch(
        r"\s*([+-]?\d+)\s+(\d+)(?:\s+[+-]?\d+\s+\d+)*\s*",
        lines[cursor],
    )
    if charge_line is None:
        raise ComputeContractError(
            f"Gaussian seed has an invalid charge/multiplicity line for structure "
            f"{structure_index} of {structure_count}"
        )
    embedded = (int(charge_line.group(1)), int(charge_line.group(2)))
    if embedded != (charge, multiplicity):
        raise ComputeContractError(
            f"Gaussian seed structure {structure_index} charge/multiplicity does not match "
            "declared chemical metadata"
        )

    cursor += 1
    atom_order: list[str] = []
    while cursor < len(lines) and lines[cursor].strip():
        parts = lines[cursor].split()
        symbol = re.match(r"^(?:[A-Za-z]{1,3}|[1-9][0-9]{0,2})", parts[0]) if parts else None
        if len(parts) < 4 or symbol is None:
            raise ComputeContractError(f"Gaussian seed has an invalid Cartesian atom line {cursor + 1}")
        try:
            coordinates = [float(value) for value in parts[-3:]]
        except ValueError as exc:
            raise ComputeContractError(
                f"Gaussian seed requires Cartesian coordinates on line {cursor + 1}"
            ) from exc
        if not all(math.isfinite(value) for value in coordinates):
            raise ComputeContractError(f"Gaussian seed has a non-finite coordinate on line {cursor + 1}")
        atom_order.append(symbol.group(0))
        cursor += 1
    if not atom_order:
        raise ComputeContractError(
            f"Gaussian seed requires at least one Cartesian atom in structure "
            f"{structure_index} of {structure_count}"
        )
    if len(atom_order) > 512:
        raise ComputeContractError("Gaussian seed atom count cannot exceed 512")
    return atom_order, cursor
