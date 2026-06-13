"""Gaussian log/input parsing helpers used by transition-state tools."""

from __future__ import annotations

from dataclasses import dataclass
import re
from pathlib import Path
from typing import Any

from transition_state_workflow.chem.geometry import Atom, vector_norm


PERIODIC_TABLE = [
    "",
    "H",
    "He",
    "Li",
    "Be",
    "B",
    "C",
    "N",
    "O",
    "F",
    "Ne",
    "Na",
    "Mg",
    "Al",
    "Si",
    "P",
    "S",
    "Cl",
    "Ar",
    "K",
    "Ca",
    "Sc",
    "Ti",
    "V",
    "Cr",
    "Mn",
    "Fe",
    "Co",
    "Ni",
    "Cu",
    "Zn",
    "Ga",
    "Ge",
    "As",
    "Se",
    "Br",
    "Kr",
    "Rb",
    "Sr",
    "Y",
    "Zr",
    "Nb",
    "Mo",
    "Tc",
    "Ru",
    "Rh",
    "Pd",
    "Ag",
    "Cd",
    "In",
    "Sn",
    "Sb",
    "Te",
    "I",
    "Xe",
    "Cs",
    "Ba",
    "La",
    "Ce",
    "Pr",
    "Nd",
    "Pm",
    "Sm",
    "Eu",
    "Gd",
    "Tb",
    "Dy",
    "Ho",
    "Er",
    "Tm",
    "Yb",
    "Lu",
    "Hf",
    "Ta",
    "W",
    "Re",
    "Os",
    "Ir",
    "Pt",
    "Au",
    "Hg",
    "Tl",
    "Pb",
    "Bi",
    "Po",
    "At",
    "Rn",
]


@dataclass(frozen=True)
class Mode:
    """Gaussian normal-mode displacement vectors."""

    index: int
    frequency: float
    vectors: list[tuple[float, float, float]]


def atomic_symbol(atomic_number: int) -> str:
    """Return a chemical symbol for a Gaussian atomic number."""

    if 0 < atomic_number < len(PERIODIC_TABLE):
        return PERIODIC_TABLE[atomic_number]
    return f"X{atomic_number}"


# Standard ``Frequencies --`` lines carry exactly two dashes. With ``freq=hpmodes``
# Gaussian additionally prints high-precision ``Frequencies ---`` lines (three
# dashes); those must be skipped so frequencies are not counted twice and the
# trailing ``-`` is not parsed as a float. The trailing ``\s`` after ``--`` makes
# the three-dash form fail to match.
STANDARD_FREQUENCY_LINE = re.compile(r"\s*Frequencies\s+--\s+(.*)")


def standard_frequency_values(line: str) -> list[float] | None:
    """Return the frequencies on a standard ``Frequencies --`` line, else None.

    High-precision ``Frequencies ---`` (hpmodes) lines return None so callers can
    skip them without double-counting modes.
    """

    match = STANDARD_FREQUENCY_LINE.match(line)
    if not match:
        return None
    return [float(value) for value in match.group(1).split()]


def read_lines(path: Path) -> list[str]:
    """Read a Gaussian text file while tolerating replacement characters."""

    return path.read_text(encoding="utf-8", errors="replace").splitlines()


def split_job_sections(lines: list[str]) -> list[list[str]]:
    """Split a concatenated Gaussian log into per-job line blocks.

    Jobs are separated by a ``--Link1--`` line or a fresh ``Entering Link 1``
    banner that follows a prior job's termination. A single-job log returns one
    block. This mirrors the section logic in
    ``tool/parse_gaussian_ts_result.split_job_sections`` but returns plain line
    blocks for the common "look at the final job" question.
    """

    sections: list[list[str]] = []
    start = 0
    for i, line in enumerate(lines):
        is_link1 = re.match(r"^\s*--Link1--\s*$", line) is not None
        is_concat_start = (
            i > start
            and re.match(r"^\s*Entering Link 1\b", line) is not None
            and any("termination of Gaussian" in prior for prior in lines[start:i])
        )
        if not is_link1 and not is_concat_start:
            continue
        if any(part.strip() for part in lines[start:i]):
            sections.append(lines[start:i])
        start = i + 1 if is_link1 else i
    if any(part.strip() for part in lines[start:]):
        sections.append(lines[start:])
    return sections or [lines]


def final_job_lines(lines: list[str]) -> list[str]:
    """Return the line block for the last job in a (possibly concatenated) log."""

    return split_job_sections(lines)[-1]


def terminated_normally(lines: list[str]) -> bool:
    """True only if the *final* job reached normal termination without error.

    Whole-file ``any("Normal termination" ...)`` checks misjudge concatenated
    logs: a prior successful job makes a later failed job look terminated. This
    scopes the judgment to the last job, matching the TS/Freq validator.
    """

    final = "\n".join(final_job_lines(lines))
    return "Normal termination of Gaussian" in final and "Error termination" not in final


def parse_charge_multiplicity(lines: list[str]) -> tuple[int, int]:
    """Parse the first Gaussian charge/multiplicity line, defaulting to neutral singlet."""

    match = re.search(r"Charge\s*=\s*(-?\d+)\s+Multiplicity\s*=\s*(\d+)", "\n".join(lines))
    if match:
        return int(match.group(1)), int(match.group(2))
    return 0, 1


def orientation_blocks(lines: list[str], marker: str) -> list[list[Atom]]:
    """Return all Gaussian orientation tables matching a marker."""

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


def final_geometry(lines: list[str]) -> list[Atom]:
    """Return the last standard or input orientation block from a Gaussian log."""

    standard = orientation_blocks(lines, "Standard orientation:")
    if standard:
        return standard[-1]
    input_orientation = orientation_blocks(lines, "Input orientation:")
    if input_orientation:
        return input_orientation[-1]
    raise ValueError("No final orientation block found in Gaussian output")


def parse_modes(lines: list[str], natoms: int) -> list[Mode]:
    """Parse Gaussian frequency displacement tables."""

    modes: list[Mode] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        freqs = standard_frequency_values(line)
        if freqs is None:
            i += 1
            continue
        i += 1
        while i < len(lines) and not re.match(r"\s*Atom\s+AN\s+", lines[i]):
            i += 1
        if i >= len(lines):
            raise ValueError("Frequency block has no displacement table")
        i += 1
        vectors = [[(0.0, 0.0, 0.0) for _ in range(natoms)] for _ in freqs]
        row_count = 0
        while i < len(lines) and row_count < natoms:
            parts = lines[i].split()
            if len(parts) < 2 + 3 * len(freqs):
                break
            for mode_offset in range(len(freqs)):
                base = 2 + 3 * mode_offset
                vectors[mode_offset][row_count] = (
                    float(parts[base]),
                    float(parts[base + 1]),
                    float(parts[base + 2]),
                )
            row_count += 1
            i += 1
        if row_count != natoms:
            raise ValueError(f"Mode table atom count mismatch: expected {natoms}, got {row_count}")
        start = len(modes) + 1
        for offset, freq in enumerate(freqs):
            modes.append(Mode(index=start + offset, frequency=freq, vectors=vectors[offset]))
    if not modes:
        raise ValueError("No Gaussian frequency blocks found")
    return modes


def displaced_atoms(atoms: list[Atom], mode: Mode, amplitude: float) -> list[Atom]:
    """Displace atoms along a mode by a max-atom displacement amplitude."""

    max_norm = max(vector_norm(vector) for vector in mode.vectors)
    if max_norm == 0.0:
        raise ValueError("Imaginary mode displacement vectors are all zero")
    factor = amplitude / max_norm
    return [
        Atom(
            atom.element,
            atom.x + factor * vector[0],
            atom.y + factor * vector[1],
            atom.z + factor * vector[2],
        )
        for atom, vector in zip(atoms, mode.vectors)
    ]


def parse_irc_status(lines: list[str]) -> dict[str, Any]:
    """Parse a compact status summary from a Gaussian IRC log."""

    energies: list[float] = []
    accepted_points: list[int] = []
    reaction_coordinates: list[float] = []
    directions: list[str] = []
    for line in lines:
        point_match = re.search(r"Point Number\s+(\d+)\s+in\s+([A-Z]+)\s+path direction", line, flags=re.IGNORECASE)
        if point_match:
            directions.append(point_match.group(2).upper())
        accepted_match = re.search(r"Point Number:\s*(\d+)\s+Path Number:\s*(\d+)", line)
        if accepted_match:
            accepted_points.append(int(accepted_match.group(1)))
        coord_match = re.search(r"NET REACTION COORDINATE UP TO THIS POINT\s*=\s*([-+]?\d+(?:\.\d*)?)", line)
        if coord_match:
            reaction_coordinates.append(float(coord_match.group(1)))
        energy_match = re.search(r"SCF Done:\s+E\([^)]+\)\s*=\s*([-+]?\d+\.\d+)", line)
        if energy_match:
            energies.append(float(energy_match.group(1)))
    final = final_job_lines(lines)
    return {
        "direction": directions[-1] if directions else None,
        "normal_termination": any("Normal termination of Gaussian" in line for line in final),
        "error_termination": any("Error termination" in line for line in final),
        "pes_minimum_detected": any("PES minimum detected" in line for line in lines),
        "maximum_points_reached": any("Maximum number of points" in line for line in lines),
        "accepted_point_count": len(accepted_points),
        "last_accepted_point": accepted_points[-1] if accepted_points else None,
        "last_reaction_coordinate": reaction_coordinates[-1] if reaction_coordinates else None,
        "scf_done_count": len(energies),
        "last_scf_energy_hartree": energies[-1] if energies else None,
    }


def frequency_summary(lines: list[str]) -> dict[str, Any]:
    """Return a compact frequency-analysis summary."""

    frequencies: list[float] = []
    for line in lines:
        values = standard_frequency_values(line)
        if values is not None:
            frequencies.extend(values)
    imaginary = [freq for freq in frequencies if freq < 0.0]
    return {
        "frequency_count": len(frequencies),
        "imaginary_frequency_count": len(imaginary),
        "imaginary_frequencies_cm-1": imaginary,
        "has_frequency_analysis": bool(frequencies),
    }


def parse_gjf_template(path: Path) -> dict[str, Any]:
    """Parse Link0, route, charge/multiplicity, and tail blocks from a Gaussian input."""

    lines = read_lines(path)
    i = 0
    link0: list[str] = []
    while i < len(lines) and lines[i].lstrip().startswith("%"):
        link0.append(lines[i])
        i += 1
    route: list[str] = []
    if i < len(lines) and lines[i].lstrip().startswith("#"):
        while i < len(lines) and lines[i].strip():
            route.append(lines[i].strip())
            i += 1
    while i < len(lines) and not lines[i].strip():
        i += 1
    title: list[str] = []
    while i < len(lines) and lines[i].strip():
        title.append(lines[i])
        i += 1
    while i < len(lines) and not lines[i].strip():
        i += 1
    charge, multiplicity = 0, 1
    if i < len(lines):
        parts = lines[i].split()
        if len(parts) >= 2:
            charge, multiplicity = int(parts[0]), int(parts[1])
        i += 1
    while i < len(lines) and lines[i].strip():
        i += 1
    while i < len(lines) and not lines[i].strip():
        i += 1
    return {
        "link0": link0,
        "route": " ".join(route),
        "title": " ".join(title).strip(),
        "charge": charge,
        "multiplicity": multiplicity,
        "tail": lines[i:],
    }


def endpoint_route(route: str) -> str:
    """Convert a TS/Freq route into a plain endpoint-optimization route."""

    route = re.sub(r"\bfreq(?:\s*=\s*\([^)]*\)|\s*\([^)]*\))?", "", route, flags=re.IGNORECASE)
    opt_pattern = r"\bopt(?:\s*=\s*\([^)]*\)|\s*\([^)]*\)|\s*=\s*\w+)?"
    if re.search(opt_pattern, route, flags=re.IGNORECASE):
        route = re.sub(opt_pattern, "opt=(maxcycle=100)", route, count=1, flags=re.IGNORECASE)
    else:
        route = f"{route} opt=(maxcycle=100)"
    return re.sub(r"\s+", " ", route).strip()


def fixed_link0(link0: list[str], chk: str, nproc: int | None, mem: str | None) -> list[str]:
    """Return Link0 lines with checkpoint/resources normalized."""

    out: list[str] = []
    saw_chk = False
    saw_nproc = False
    saw_mem = False
    for line in link0:
        key = line.split("=", 1)[0].strip().lower()
        if key == "%chk":
            out.append(f"%chk={chk}")
            saw_chk = True
        elif key == "%nprocshared":
            out.append(f"%nprocshared={nproc}" if nproc else line)
            saw_nproc = True
        elif key == "%mem":
            out.append(f"%mem={mem}" if mem else line)
            saw_mem = True
        else:
            out.append(line)
    if not saw_chk:
        out.insert(0, f"%chk={chk}")
    if nproc and not saw_nproc:
        out.insert(1, f"%nprocshared={nproc}")
    if mem and not saw_mem:
        out.insert(1, f"%mem={mem}")
    return out


def write_gjf(
    path: Path,
    atoms: list[Atom],
    template: dict[str, Any],
    route: str,
    chk: str,
    nproc: int | None,
    mem: str | None,
    title: str,
) -> None:
    """Write a Gaussian input using a parsed template and a new geometry."""

    link0 = fixed_link0(list(template["link0"]), chk, nproc, mem)
    charge = int(template["charge"])
    multiplicity = int(template["multiplicity"])
    tail = list(template["tail"])
    lines = [*link0, route, "", title, "", f"{charge} {multiplicity}"]
    for atom in atoms:
        lines.append(f"{atom.element:<3s} {atom.x:16.8f} {atom.y:16.8f} {atom.z:16.8f}")
    lines.append("")
    lines.extend(tail)
    while lines and not lines[-1].strip():
        lines.pop()
    lines.extend(["", ""])
    path.write_text("\n".join(lines), encoding="utf-8")
