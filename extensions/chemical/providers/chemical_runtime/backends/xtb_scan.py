"""Validated xTB relaxed-scan controls and deterministic scan-point parsing.

The control grammar mirrors xTB's ``$scan`` block: a directive may reference
an earlier ``$constrain`` entry by number, or define a distance/angle/dihedral
inline using ``kind: atoms, value; start, end, steps``.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .xyz import read_xyz_frames


_FLOAT = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][-+]?\d+)?"
_CONSTRAINT_ATOMS = {"distance": 2, "angle": 3, "dihedral": 4}
_CONTROL_MAX_BYTES = 256 * 1024
_MAX_POINTS = 10_000


@dataclass(frozen=True)
class XtbScanConstraint:
    kind: str
    atoms: tuple[int, ...]
    initial_value: float | None


@dataclass(frozen=True)
class XtbScanDirective:
    constraint_index: int
    start: float
    end: float
    steps: int


@dataclass(frozen=True)
class XtbScanPlan:
    mode: str
    constraints: tuple[XtbScanConstraint, ...]
    directives: tuple[XtbScanDirective, ...]

    @property
    def point_count(self) -> int:
        if self.mode == "concerted":
            return self.directives[0].steps
        return sum(directive.steps for directive in self.directives)


def parse_xtb_scan_control(path: Path, *, atom_count: int | None = None) -> XtbScanPlan:
    if path.stat().st_size > _CONTROL_MAX_BYTES:
        raise ValueError("xTB scan control input exceeds 256 KiB")
    text = path.read_text(encoding="utf-8")
    section: str | None = None
    seen_sections: set[str] = set()
    saw_end = False
    section_closed = False
    constraints: list[XtbScanConstraint] = []
    directives: list[XtbScanDirective] = []
    mode = "sequential"

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("$"):
            header = line.lower()
            if header == "$end":
                saw_end = True
                section_closed = True
                section = None
                continue
            if header not in {"$constrain", "$scan"}:
                raise ValueError(f"unsupported xTB scan control section at line {line_number}: {line}")
            section = header[1:]
            if section in seen_sections:
                raise ValueError(f"duplicate xTB scan control section: {line}")
            seen_sections.add(section)
            section_closed = False
            continue
        if section == "constrain":
            constraint = _parse_constraint(line, line_number)
            if constraint is not None:
                constraints.append(constraint)
            continue
        if section == "scan":
            mode_match = re.fullmatch(r"mode\s*=\s*([A-Za-z]+)", line, flags=re.IGNORECASE)
            if mode_match:
                mode = mode_match.group(1).lower()
                if mode not in {"sequential", "concerted"}:
                    raise ValueError(f"unsupported xTB scan mode at line {line_number}: {mode}")
                continue
            directives.append(_parse_directive(line, line_number, constraints))
            continue
        if saw_end:
            raise ValueError(f"xTB scan control has content after $end at line {line_number}")
        raise ValueError(f"xTB scan control content is outside a section at line {line_number}")

    if not saw_end or not section_closed:
        raise ValueError("xTB scan control must end with $end")
    if "scan" not in seen_sections:
        if seen_sections == {"constrain"}:
            raise ValueError("xTB scan control requires both $constrain and $scan sections")
        raise ValueError("xTB scan control requires a $scan section")
    if not constraints:
        raise ValueError("xTB scan control defines no supported constraints")
    if not directives:
        raise ValueError("xTB scan control defines no scan directives")
    if len(constraints) > 64 or len(directives) > 64:
        raise ValueError("xTB scan control supports at most 64 constraints and 64 directives")
    for directive in directives:
        if directive.constraint_index > len(constraints):
            raise ValueError(
                f"xTB scan directive references undefined constraint {directive.constraint_index}"
            )
        constraint = constraints[directive.constraint_index - 1]
        if constraint.kind == "distance" and (directive.start <= 0 or directive.end <= 0):
            raise ValueError("xTB distance scan endpoints must be positive")
    if atom_count is not None:
        for constraint in constraints:
            if max(constraint.atoms) > atom_count:
                raise ValueError(
                    f"xTB scan constraint atom index exceeds XYZ atom count {atom_count}"
                )
    if mode == "concerted" and len({directive.steps for directive in directives}) != 1:
        raise ValueError("concerted xTB scans require equal step counts")
    plan = XtbScanPlan(mode, tuple(constraints), tuple(directives))
    if plan.point_count > _MAX_POINTS:
        raise ValueError(f"xTB scan control exceeds {_MAX_POINTS} total points")
    return plan


def parse_xtb_scan_artifact(control: Path, trajectory: Path | None) -> dict[str, Any]:
    if trajectory is None:
        plan = parse_xtb_scan_control(control)
        points: list[dict[str, Any]] = []
    else:
        parsed_trajectory = read_xyz_frames(trajectory)
        plan = parse_xtb_scan_control(control, atom_count=parsed_trajectory["atom_count"])
        points = _scan_points(plan, parsed_trajectory["frames"])
    energies = [
        point["energy_hartree"]
        for point in points
        if isinstance(point.get("energy_hartree"), float)
        and math.isfinite(point["energy_hartree"])
    ]
    energies_complete = bool(points) and len(energies) == len(points)
    coordinates_complete = bool(points) and all(
        bool(point["coordinates"])
        and all(math.isfinite(target["actual_value"]) for target in point["coordinates"])
        for point in points
    )
    return {
        "summary": {
            "scan_mode": plan.mode,
            "scan_constraint_count": len(plan.constraints),
            "scan_directive_count": len(plan.directives),
            "scan_expected_point_count": plan.point_count,
            "scan_point_count": len(points),
            "scan_all_energies_finite": energies_complete,
            "scan_coordinates_complete": coordinates_complete,
            "scan_min_energy_hartree": min(energies) if energies else None,
            "scan_max_energy_hartree": max(energies) if energies else None,
            "scan_data_complete": bool(
                len(points) == plan.point_count
                and energies_complete
                and coordinates_complete
            ),
        },
        "points": {
            "schema_version": "xtb-scan-points/1",
            "mode": plan.mode,
            "constraints": [_constraint_value(item) for item in plan.constraints],
            "points": points,
        },
    }


def _parse_constraint(line: str, line_number: int) -> XtbScanConstraint | None:
    force_match = re.fullmatch(
        rf"force\s+constant\s*=\s*({_FLOAT})",
        line,
        flags=re.IGNORECASE,
    )
    if force_match:
        if _finite_number(force_match.group(1), "scan force constant") <= 0:
            raise ValueError(f"xTB scan force constant must be positive at line {line_number}")
        return None
    match = re.fullmatch(r"(distance|angle|dihedral)\s*:\s*(.+)", line, flags=re.IGNORECASE)
    if not match:
        raise ValueError(f"unsupported xTB scan constraint at line {line_number}: {line}")
    kind = match.group(1).lower()
    fields = [field.strip() for field in match.group(2).split(",")]
    expected = _CONSTRAINT_ATOMS[kind] + 1
    if len(fields) != expected:
        raise ValueError(
            f"xTB {kind} constraint requires {expected} comma-separated values at line {line_number}"
        )
    try:
        atoms = tuple(int(field) for field in fields[:-1])
    except ValueError as exc:
        raise ValueError(f"xTB scan atom indices must be integers at line {line_number}") from exc
    if any(atom <= 0 for atom in atoms) or len(set(atoms)) != len(atoms):
        raise ValueError(f"xTB scan atom indices must be positive and distinct at line {line_number}")
    initial = None
    if fields[-1].lower() != "auto":
        initial = _finite_number(fields[-1], f"{kind} constraint value")
        if kind == "distance" and initial <= 0:
            raise ValueError(f"xTB distance constraint must be positive at line {line_number}")
    return XtbScanConstraint(kind, atoms, initial)


def _parse_directive(
    line: str,
    line_number: int,
    constraints: list[XtbScanConstraint],
) -> XtbScanDirective:
    numbered = re.fullmatch(r"(\d+)\s*:\s*(.+)", line)
    if numbered:
        constraint_index = int(numbered.group(1))
        if constraint_index <= 0:
            raise ValueError(f"xTB scan constraint index must be positive at line {line_number}")
        if constraint_index > len(constraints):
            if not constraints:
                raise ValueError(
                    "$constrain must appear before $scan for numbered directives; "
                    f"undefined constraint {constraint_index}"
                )
            raise ValueError(
                f"xTB scan directive references undefined constraint {constraint_index}"
            )
        return _parse_scan_values(numbered.group(2), constraint_index, line_number)

    inline = re.fullmatch(
        r"(distance|angle|dihedral)\s*:\s*(.+)",
        line,
        flags=re.IGNORECASE,
    )
    if inline:
        parts = inline.group(2).split(";")
        if len(parts) != 2 or not all(part.strip() for part in parts):
            raise ValueError(
                "xTB inline scan directives require a constraint and "
                f"start, end, and steps separated by ';' at line {line_number}"
            )
        constraint = _parse_constraint(
            f"{inline.group(1)}: {parts[0].strip()}",
            line_number,
        )
        if constraint is None:
            raise ValueError(f"invalid xTB inline scan constraint at line {line_number}")
        constraints.append(constraint)
        return _parse_scan_values(parts[1], len(constraints), line_number)

    raise ValueError(
        "xTB scan directives must reference a numbered constraint or use "
        f"the named inline form at line {line_number}"
    )


def _parse_scan_values(
    value_text: str,
    constraint_index: int,
    line_number: int,
) -> XtbScanDirective:
    fields = [field.strip() for field in value_text.split(",")]
    if len(fields) != 3:
        raise ValueError(f"xTB scan directive requires start, end, and steps at line {line_number}")
    start = _finite_number(fields[0], "scan start")
    end = _finite_number(fields[1], "scan end")
    try:
        steps = int(fields[2])
    except ValueError as exc:
        raise ValueError(f"xTB scan steps must be an integer at line {line_number}") from exc
    if not 2 <= steps <= _MAX_POINTS:
        raise ValueError(
            f"xTB scan steps must be between 2 and {_MAX_POINTS} at line {line_number}"
        )
    return XtbScanDirective(constraint_index, start, end, steps)


def _scan_points(plan: XtbScanPlan, frames: list[dict[str, Any]]) -> list[dict[str, Any]]:
    target_groups = _target_groups(plan)
    points: list[dict[str, Any]] = []
    for index, frame in enumerate(frames):
        coordinates = frame["coordinates"]
        targets = target_groups[index] if index < len(target_groups) else []
        values = []
        for constraint_index, target_value in targets:
            constraint = plan.constraints[constraint_index - 1]
            values.append(
                {
                    "constraint_index": constraint_index,
                    "kind": constraint.kind,
                    "atoms": list(constraint.atoms),
                    "unit": "angstrom" if constraint.kind == "distance" else "degree",
                    "target_value": target_value,
                    "actual_value": _constraint_coordinate(constraint, coordinates),
                }
            )
        points.append(
            {
                "index": index,
                "energy_hartree": frame.get("energy_hartree"),
                "coordinates": values,
            }
        )
    return points


def _target_groups(plan: XtbScanPlan) -> list[list[tuple[int, float]]]:
    if plan.mode == "sequential":
        return [
            [(directive.constraint_index, value)]
            for directive in plan.directives
            for value in _scan_values(directive)
        ]
    value_lists = [_scan_values(directive) for directive in plan.directives]
    return [
        [
            (directive.constraint_index, values[point_index])
            for directive, values in zip(plan.directives, value_lists, strict=True)
        ]
        for point_index in range(plan.point_count)
    ]


def _scan_values(directive: XtbScanDirective) -> list[float]:
    return [
        directive.start
        + (directive.end - directive.start) * point_index / (directive.steps - 1)
        for point_index in range(directive.steps)
    ]


def _constraint_value(constraint: XtbScanConstraint) -> dict[str, Any]:
    return {
        "kind": constraint.kind,
        "atoms": list(constraint.atoms),
        "unit": "angstrom" if constraint.kind == "distance" else "degree",
        "initial_value": constraint.initial_value,
    }


def _constraint_coordinate(
    constraint: XtbScanConstraint,
    coordinates: list[tuple[float, float, float]],
) -> float:
    points = [coordinates[index - 1] for index in constraint.atoms]
    if constraint.kind == "distance":
        return _norm(_subtract(points[0], points[1]))
    if constraint.kind == "angle":
        left = _subtract(points[0], points[1])
        right = _subtract(points[2], points[1])
        denominator = _norm(left) * _norm(right)
        if denominator == 0:
            raise ValueError("xTB scan trajectory contains an undefined angle")
        cosine = max(-1.0, min(1.0, _dot(left, right) / denominator))
        return math.degrees(math.acos(cosine))
    first = _subtract(points[0], points[1])
    axis = _subtract(points[2], points[1])
    last = _subtract(points[3], points[2])
    axis_norm = _norm(axis)
    if axis_norm == 0:
        raise ValueError("xTB scan trajectory contains an undefined dihedral")
    unit_axis = tuple(value / axis_norm for value in axis)
    first_plane = _subtract(first, _scale(unit_axis, _dot(first, unit_axis)))
    last_plane = _subtract(last, _scale(unit_axis, _dot(last, unit_axis)))
    if _norm(first_plane) == 0 or _norm(last_plane) == 0:
        raise ValueError("xTB scan trajectory contains an undefined dihedral")
    return math.degrees(
        math.atan2(
            _dot(_cross(unit_axis, first_plane), last_plane),
            _dot(first_plane, last_plane),
        )
    )


def _subtract(
    left: tuple[float, float, float],
    right: tuple[float, float, float],
) -> tuple[float, float, float]:
    return tuple(a - b for a, b in zip(left, right, strict=True))


def _scale(
    vector: tuple[float, float, float],
    factor: float,
) -> tuple[float, float, float]:
    return tuple(value * factor for value in vector)


def _dot(
    left: tuple[float, float, float],
    right: tuple[float, float, float],
) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True))


def _cross(
    left: tuple[float, float, float],
    right: tuple[float, float, float],
) -> tuple[float, float, float]:
    return (
        left[1] * right[2] - left[2] * right[1],
        left[2] * right[0] - left[0] * right[2],
        left[0] * right[1] - left[1] * right[0],
    )


def _norm(vector: tuple[float, float, float]) -> float:
    return math.sqrt(_dot(vector, vector))


def _finite_number(value: str, label: str) -> float:
    try:
        parsed = float(value.replace("D", "E").replace("d", "e"))
    except ValueError as exc:
        raise ValueError(f"xTB {label} must be numeric") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"xTB {label} must be finite")
    return parsed
