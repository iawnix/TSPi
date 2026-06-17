"""Gaussian backend adapter and TS/Freq log parsing."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, List, Mapping, Tuple

from transition_state_workflow.backends.base import FilesystemBackendAdapter
from transition_state_workflow.backends.contracts import BackendInput, BackendOutput
from transition_state_workflow.chem.geometry import Atom
from transition_state_workflow.chem.gaussian_log import (
    Mode as GaussianMode,
    displaced_atoms,
    endpoint_route as gaussian_endpoint_route,
    final_geometry as final_gaussian_atoms,
    parse_charge_multiplicity as parse_gaussian_charge_multiplicity,
    parse_gjf_template,
    parse_modes as parse_gaussian_modes,
    read_lines as read_gaussian_lines,
    orientation_blocks as gaussian_orientation_blocks,
    standard_frequency_values,
    terminated_normally as gaussian_terminated_normally,
    write_gjf,
)

GaussianCoord = Tuple[str, float, float, float]
GaussianFrame = Tuple[str, List[GaussianCoord]]
HARTREE_TO_EV = 27.211386245988
QST_ROUTE_TOKENS = ("qst2", "qst3")


@dataclass(frozen=True)
class GaussianInputRequest:
    """Backend-owned Gaussian input-generation request."""

    title: str
    coords: list[GaussianCoord]
    route: str
    charge: int
    multiplicity: int
    nproc: int | None = None
    mem: str | None = None
    chk: str | None = None
    extra_sections: tuple[str, ...] = ()


@dataclass(frozen=True)
class GaussianImaginaryModeFollowData:
    """Backend-owned data needed to prepare imaginary-mode follow-up artifacts."""

    freq_output: Path
    atoms: list[Atom]
    modes: list[GaussianMode]
    imaginary_modes: list[GaussianMode]
    mode: GaussianMode | None
    minus_atoms: list[Atom] | None
    plus_atoms: list[Atom] | None
    scan_frames: tuple[tuple[float, list[Atom], str], ...]
    summary: dict[str, object]


def read_xyz_frames(path: Path) -> list[GaussianFrame]:
    """Read one or more XYZ/extXYZ frames for Gaussian input preparation."""

    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        raise ValueError(f"{path} is empty")

    frames: list[GaussianFrame] = []
    i = 0
    while i < len(lines):
        while i < len(lines) and not lines[i].strip():
            i += 1
        if i >= len(lines):
            break
        try:
            natoms = int(lines[i].strip())
        except ValueError as exc:
            raise ValueError(
                f"{path} is not a standard XYZ/extXYZ file: line {i + 1} is not an atom count"
            ) from exc
        if natoms <= 0:
            raise ValueError(f"Bad atom count on line {i + 1}: {natoms}")

        title_line = i + 1
        title = lines[title_line].strip() if title_line < len(lines) and lines[title_line].strip() else path.stem
        coord_start = i + 2
        coord_end = coord_start + natoms
        if coord_end > len(lines):
            raise ValueError(f"Frame {len(frames)} expected {natoms} atoms, but file ended early")

        coords: list[GaussianCoord] = []
        for lineno, line in enumerate(lines[coord_start:coord_end], start=coord_start + 1):
            parts = line.split()
            if len(parts) < 4:
                raise ValueError(f"Bad coordinate line {lineno}: {line!r}")
            try:
                coords.append((parts[0], float(parts[1]), float(parts[2]), float(parts[3])))
            except ValueError as exc:
                raise ValueError(f"Bad coordinate value on line {lineno}: {line!r}") from exc
        frames.append((title, coords))
        i = coord_end

    if not frames:
        raise ValueError(f"{path} does not contain any XYZ frames")
    return frames


def select_frame(frames: list[GaussianFrame], selector: str) -> tuple[int, str, list[GaussianCoord]]:
    """Select a Gaussian input frame using the CLI-compatible selector syntax."""

    selector = selector.strip().lower()
    if selector == "only":
        if len(frames) != 1:
            raise ValueError(
                f"Input contains {len(frames)} XYZ frames; use --frame first, --frame last, "
                "or --frame <zero-based-index> to choose the TS candidate explicitly"
            )
        index = 0
    elif selector == "first":
        index = 0
    elif selector == "last":
        index = len(frames) - 1
    else:
        try:
            index = int(selector)
        except ValueError as exc:
            raise ValueError("Frame selector must be 'only', 'first', 'last', or an integer index") from exc
        if index < 0:
            index += len(frames)
        if not 0 <= index < len(frames):
            raise ValueError(f"Frame index {selector!r} is out of range for {len(frames)} frames")
    title, coords = frames[index]
    return index, title, coords


def read_xyz_frame(path: Path, frame: str = "only") -> tuple[int, str, list[GaussianCoord]]:
    """Read and select one XYZ/extXYZ frame."""

    return select_frame(read_xyz_frames(path), frame)


def normalize_route(route: str) -> str:
    """Normalize a Gaussian route section, adding ``#P`` when omitted."""

    route = route.strip()
    if not route:
        raise ValueError("Gaussian route section cannot be empty")
    if route.startswith("#"):
        return route
    return f"#P {route}"


def route_requires_extra_section(route: str) -> bool:
    """Return whether a route uses Gen/GenECP-style extra input sections."""

    normalized = normalize_route(route).lower()
    return bool(re.search(r"(^|[\s/#(),])gen(ecp)?($|[\s/#(),])", normalized))


def route_indices(lines: list[str]) -> tuple[int | None, int | None]:
    """Return the inclusive Gaussian route-line span in an input file."""

    start = next((i for i, line in enumerate(lines) if line.lstrip().startswith("#")), None)
    if start is None:
        return None, None
    end = start
    while end + 1 < len(lines) and lines[end + 1].strip():
        end += 1
    return start, end


def split_tail(lines: list[str]) -> list[str]:
    """Return extra sections after title, charge/multiplicity, and coordinates."""

    route_start, route_end = route_indices(lines)
    if route_start is None or route_end is None:
        return []
    i = route_end + 1
    while i < len(lines) and not lines[i].strip():
        i += 1
    while i < len(lines) and lines[i].strip():
        i += 1
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i < len(lines):
        i += 1
    while i < len(lines) and lines[i].strip():
        i += 1
    while i < len(lines) and not lines[i].strip():
        i += 1
    return lines[i:]


def link0_end(lines: list[str]) -> int:
    """Return the first line after contiguous Gaussian Link 0 directives."""

    i = 0
    while i < len(lines) and lines[i].lstrip().startswith("%"):
        i += 1
    return i


def warnings_for(lines: list[str]) -> list[str]:
    """Return Gen/GenECP preflight warnings for a Gaussian input."""

    warnings: list[str] = []
    route_start, route_end = route_indices(lines)
    link0 = lines[: link0_end(lines)]
    route = " ".join(line.strip() for line in lines[route_start : route_end + 1]) if route_start is not None else ""
    tail = split_tail(lines)

    if not any(line.lower().lstrip().startswith("%chk") for line in link0):
        warnings.append("missing %chk")

    if "/gen" in route.lower():
        first_basis_line = next((line.strip() for line in tail if line.strip()), "")
        if any(part.startswith("-") for part in first_basis_line.split()[:-1]):
            warnings.append("Gen center line contains leading '-' labels")

    if "/genecp" in route.lower():
        stars = [i for i, line in enumerate(tail) if line.strip() == "****"]
        if not stars:
            warnings.append("route uses genecp but no basis terminator was found")
        elif not any(line.strip() for line in tail[stars[-1] + 1 :]):
            warnings.append("route uses genecp but no ECP block follows the basis block")

    if len(lines) < 2 or lines[-1].strip() or lines[-2].strip():
        warnings.append("input does not end with two blank lines")
    return warnings


def fix_lines(lines: list[str], chk: str, nproc: int | None, mem: str | None) -> list[str]:
    """Return a repaired Gaussian Gen/GenECP input line list."""

    out = list(lines)
    end = link0_end(out)
    seen_chk = False
    seen_mem = False
    seen_nproc = False
    fixed_link0: list[str] = []
    for line in out[:end]:
        key = line.split("=", 1)[0].strip().lower()
        if key == "%chk":
            fixed_link0.append(f"%chk={chk}")
            seen_chk = True
        elif key == "%mem" and mem:
            fixed_link0.append(f"%mem={mem}")
            seen_mem = True
        elif key == "%nprocshared" and nproc:
            fixed_link0.append(f"%nprocshared={nproc}")
            seen_nproc = True
        else:
            fixed_link0.append(line)
    inserts: list[str] = []
    if not seen_chk:
        inserts.append(f"%chk={chk}")
    if mem and not seen_mem:
        inserts.append(f"%mem={mem}")
    if nproc and not seen_nproc:
        inserts.append(f"%nprocshared={nproc}")
    out = [*inserts, *fixed_link0, *out[end:]]

    route_start, route_end = route_indices(out)
    if route_start is not None and route_end is not None:
        route = " ".join(line.strip() for line in out[route_start : route_end + 1])
        tail = split_tail(out)
        if "/genecp" in route.lower():
            stars = [i for i, line in enumerate(tail) if line.strip() == "****"]
            if stars and not any(line.strip() for line in tail[stars[-1] + 1 :]):
                route = re.sub(r"/genecp\b", "/gen", route, flags=re.IGNORECASE)
        out[route_start : route_end + 1] = [route]

    for i, line in enumerate(out):
        parts = line.split()
        if len(parts) >= 2 and parts[-1] == "0" and any(part.startswith("-") for part in parts[:-1]):
            out[i] = " ".join([*(part[1:] if part.startswith("-") else part for part in parts[:-1]), "0"])

    while out and not out[-1].strip():
        out.pop()
    out.extend(["", ""])
    return out


def render_gaussian_input(request: GaussianInputRequest) -> str:
    """Render a Gaussian input file from backend-neutral geometry fields."""

    if request.nproc is not None and request.nproc <= 0:
        raise ValueError("--nproc must be positive")
    if request.multiplicity <= 0:
        raise ValueError("--multiplicity must be positive")

    lines: list[str] = []
    if request.chk:
        lines.append(f"%chk={request.chk}")
    if request.nproc is not None:
        lines.append(f"%nprocshared={request.nproc}")
    if request.mem:
        lines.append(f"%mem={request.mem}")
    lines.extend(
        [
            normalize_route(request.route),
            "",
            request.title,
            "",
            f"{request.charge} {request.multiplicity}",
        ]
    )
    for element, x, y, z in request.coords:
        lines.append(f"{element:<3s} {x:16.8f} {y:16.8f} {z:16.8f}")
    lines.append("")
    for section in request.extra_sections:
        section_lines = section.rstrip().splitlines()
        if section_lines:
            lines.extend(section_lines)
            lines.append("")
    lines.append("")
    return "\n".join(lines)


def write_gaussian_input(path: Path, request: GaussianInputRequest) -> None:
    """Write a Gaussian input file from a prepared backend request."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_gaussian_input(request), encoding="utf-8")


def gaussian_refinement_defaults() -> dict[str, Any]:
    """Return ASE-NEB-promoted Gaussian TS/Freq refinement defaults."""

    return {
        "route": "# M062X/def2SVP opt=(ts,calcfc,noeigen,maxcycle=100) freq nosymm scf=xqc",
        "charge": 0,
        "multiplicity": 1,
        "nprocshared": None,
        "mem": None,
        "chk": "ts_candidate.chk",
        "title": "TS candidate from ASE NEB",
        "extra_sections": [],
    }


def render_gaussian_refinement_input(
    xyz_path: Path,
    gaussian_cfg: Mapping[str, Any],
    *,
    frame: str = "only",
) -> str:
    """Render the Gaussian TS/Freq input for an ASE NEB promoted candidate."""

    _, source_title, coords = read_xyz_frame(xyz_path, frame)
    params = gaussian_refinement_defaults()
    params.update(dict(gaussian_cfg))

    lines: list[str] = []
    if params.get("chk"):
        lines.append(f"%chk={params['chk']}")
    if params.get("nprocshared"):
        lines.append(f"%nprocshared={params['nprocshared']}")
    if params.get("mem"):
        lines.append(f"%mem={params['mem']}")
    lines.append(str(params["route"]))
    lines.append("")
    title = str(params.get("title") or source_title or "TS candidate from ASE NEB")
    lines.append(title)
    lines.append("")
    lines.append(f"{int(params['charge'])} {int(params['multiplicity'])}")
    for element, x, y, z in coords:
        lines.append(f"{element:<3s} {x:16.8f} {y:16.8f} {z:16.8f}")
    lines.append("")
    extra_sections = params.get("extra_sections") or []
    if isinstance(extra_sections, str):
        lines.extend(extra_sections.splitlines())
    else:
        for section in extra_sections:
            lines.extend(str(section).splitlines())
            lines.append("")
    while lines and not lines[-1].strip():
        lines.pop()
    lines.extend(["", "", ""])
    return "\n".join(lines)


def write_gaussian_refinement_input(
    xyz_path: Path,
    output_path: Path,
    gaussian_cfg: Mapping[str, Any],
    *,
    frame: str = "only",
) -> Path:
    """Write an ASE-NEB-promoted Gaussian TS/Freq refinement input."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        render_gaussian_refinement_input(xyz_path, gaussian_cfg, frame=frame),
        encoding="utf-8",
    )
    return output_path


def prepare_gaussian_imaginary_mode_follow_data(
    freq_output: Path,
    *,
    scale: float,
) -> GaussianImaginaryModeFollowData:
    """Extract the Gaussian TS/Freq mode data needed for endpoint follow-up."""

    lines = read_gaussian_lines(freq_output)
    atoms = final_gaussian_atoms(lines)
    charge, multiplicity = parse_gaussian_charge_multiplicity(lines)
    modes = parse_gaussian_modes(lines, len(atoms))
    imaginary = [mode for mode in modes if mode.frequency < 0.0]
    summary: dict[str, object] = {
        "freq_output": str(freq_output),
        "natoms": len(atoms),
        "charge": charge,
        "multiplicity": multiplicity,
        "frequency_count": len(modes),
        "imaginary_frequency_count": len(imaginary),
        "imaginary_frequencies_cm-1": [mode.frequency for mode in imaginary],
        "normal_termination": gaussian_terminated_normally(lines),
        "stationary_point_found": any("Stationary point found" in line for line in lines),
        "is_ts_frequency_validated": False,
    }
    if len(imaginary) != 1:
        return GaussianImaginaryModeFollowData(
            freq_output=freq_output,
            atoms=atoms,
            modes=modes,
            imaginary_modes=imaginary,
            mode=None,
            minus_atoms=None,
            plus_atoms=None,
            scan_frames=(),
            summary=summary,
        )

    mode = imaginary[0]
    is_validated = bool(summary["normal_termination"] and summary["stationary_point_found"])
    summary["is_ts_frequency_validated"] = is_validated
    summary["claim_status_suggestion"] = "tsfreq_validated" if is_validated else "ambiguous"
    summary["imaginary_mode_index"] = mode.index
    summary["imaginary_mode_frequency_cm-1"] = mode.frequency
    summary["mode_scale_angstrom_max_atom_displacement"] = scale
    minus_atoms = displaced_atoms(atoms, mode, -scale)
    plus_atoms = displaced_atoms(atoms, mode, scale)
    scan_frames = tuple(
        (
            multiplier,
            displaced_atoms(atoms, mode, multiplier * scale),
            f"mode {mode.index}, frequency {mode.frequency:.4f} cm-1, scale {multiplier * scale:.4f}",
        )
        for multiplier in (-1.0, -0.5, 0.0, 0.5, 1.0)
    )
    return GaussianImaginaryModeFollowData(
        freq_output=freq_output,
        atoms=atoms,
        modes=modes,
        imaginary_modes=imaginary,
        mode=mode,
        minus_atoms=minus_atoms,
        plus_atoms=plus_atoms,
        scan_frames=scan_frames,
        summary=summary,
    )


def endpoint_template_from_gjf(path: Path) -> tuple[dict[str, object], bool]:
    """Return a Gaussian template safe for single-geometry endpoint Opt jobs."""

    template = parse_gjf_template(path)
    route = str(template.get("route", "")).lower()
    if any(token in route for token in QST_ROUTE_TOKENS):
        return {**template, "tail": []}, True
    return template, False


def parse_gaussian_input_template(path: Path) -> dict[str, object]:
    """Parse a Gaussian input template without endpoint-follow-up policy changes."""

    return parse_gjf_template(path)


def write_gaussian_endpoint_opt_input(
    path: Path,
    atoms: list[Atom],
    *,
    template: Mapping[str, object],
    route: str,
    chk: str,
    nproc: int | None,
    mem: str | None,
    title: str,
) -> Path:
    """Write one Gaussian endpoint-optimization input from prepared atoms."""

    path.parent.mkdir(parents=True, exist_ok=True)
    write_gjf(path, atoms, dict(template), route, chk, nproc, mem, title)
    return path


def final_gaussian_atoms_from_log(path: Path) -> list[Atom]:
    """Return the final Gaussian orientation atoms from an output log."""

    return final_gaussian_atoms(read_gaussian_lines(path))


def split_gaussian_job_sections(lines: list[str]) -> list[dict[str, object]]:
    """Split a Gaussian log into Link1/concatenated job sections."""

    sections: list[dict[str, object]] = []
    start = 0
    for i, line in enumerate(lines):
        is_link1_separator = re.match(r"^\s*--Link1--\s*$", line) is not None
        is_concatenated_start = (
            i > start
            and re.match(r"^\s*Entering Link 1\b", line) is not None
            and any("termination of Gaussian" in prior for prior in lines[start:i])
        )
        if not is_link1_separator and not is_concatenated_start:
            continue
        if any(part.strip() for part in lines[start:i]):
            sections.append({"index": len(sections), "start_line": start + 1, "end_line": i, "lines": lines[start:i]})
        start = i + 1 if is_link1_separator else i
    if any(part.strip() for part in lines[start:]):
        sections.append({"index": len(sections), "start_line": start + 1, "end_line": len(lines), "lines": lines[start:]})
    return sections or [{"index": 0, "start_line": 1, "end_line": len(lines), "lines": lines}]


def select_gaussian_job_section(lines: list[str], section_index: int | None = None) -> dict[str, object]:
    """Select the final or explicitly requested Gaussian job section."""

    sections = split_gaussian_job_sections(lines)
    if section_index is None:
        section = sections[-1]
        section["selection_reason"] = "default_final_section"
        section["section_count"] = len(sections)
        return section
    if section_index < 0 or section_index >= len(sections):
        raise ValueError(f"section index {section_index} out of range for {len(sections)} section(s)")
    section = sections[section_index]
    section["selection_reason"] = "explicit_section_index"
    section["section_count"] = len(sections)
    return section


GAUSSIAN_FLOAT_TOKEN_RE = r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[DEde][-+]?\d+)?"
SCF_DONE_ENERGY_RE = re.compile(rf"SCF Done:\s+E\([^)]+\)\s+=\s+({GAUSSIAN_FLOAT_TOKEN_RE})")


def parse_gaussian_float_token(value: str) -> float:
    """Parse one Gaussian/Fortran float token."""

    return float(value.replace("D", "E").replace("d", "E"))


def parse_float(pattern: str, text: str) -> float | None:
    """Return the last float matching ``pattern`` in Gaussian text."""

    matches = re.findall(pattern, text)
    if not matches:
        return None
    value = matches[-1]
    if isinstance(value, tuple):
        value = value[-1]
    return parse_gaussian_float_token(value)


def parse_gaussian_energy_hartree(output_path: Path) -> float:
    """Return the last SCF energy from a Gaussian output in hartree."""

    energy = None
    with output_path.open("r", errors="ignore") as handle:
        for line in handle:
            match = SCF_DONE_ENERGY_RE.search(line)
            if match:
                energy = parse_gaussian_float_token(match.group(1))
    if energy is None:
        raise RuntimeError(f"cannot find SCF Done energy in Gaussian output: {output_path}")
    return energy


def parse_gaussian_forces_hartree_per_bohr(output_path: Path, natoms: int) -> Any:
    """Return the final Gaussian force block as hartree/bohr rows."""

    import numpy as np

    lines = output_path.read_text(errors="ignore").splitlines()
    starts = [
        index
        for index, line in enumerate(lines)
        if "Forces (Hartrees/Bohr)" in line
    ]
    if not starts:
        raise RuntimeError(f"cannot find Gaussian force block: {output_path}")

    force_line_re = re.compile(
        r"^\s*\d+\s+\d+\s+"
        r"([-+]?\d+\.\d+(?:[DEde][-+]?\d+)?)\s+"
        r"([-+]?\d+\.\d+(?:[DEde][-+]?\d+)?)\s+"
        r"([-+]?\d+\.\d+(?:[DEde][-+]?\d+)?)"
    )
    data: list[list[float]] = []
    for line in lines[starts[-1] :]:
        match = force_line_re.match(line)
        if not match:
            continue
        data.append(
            [
                float(match.group(1).replace("D", "E").replace("d", "E")),
                float(match.group(2).replace("D", "E").replace("d", "E")),
                float(match.group(3).replace("D", "E").replace("d", "E")),
            ]
        )
        if len(data) == natoms:
            break
    if len(data) != natoms:
        raise RuntimeError(
            f"Gaussian force block incomplete in {output_path}: "
            f"got {len(data)} rows, expected {natoms}"
        )
    return np.array(data, dtype=float)


def parse_last_scf_energy(lines: list[str]) -> float | None:
    """Return the final SCF energy from Gaussian text lines."""

    energies = []
    for line in lines:
        match = SCF_DONE_ENERGY_RE.search(line)
        if match:
            energies.append(parse_gaussian_float_token(match.group(1)))
    return energies[-1] if energies else None


def parse_charge_multiplicity(lines: list[str]) -> tuple[int | None, int | None]:
    """Return the first Gaussian charge/multiplicity declaration."""

    for line in lines:
        match = re.search(r"Charge\s*=\s*(-?\d+)\s+Multiplicity\s*=\s*(\d+)", line)
        if match:
            return int(match.group(1)), int(match.group(2))
    return None, None


def parse_freq_metadata(lines: list[str]) -> dict[str, object]:
    """Parse compact frequency metadata used by TS descriptor extraction."""

    frequencies: list[float] = []
    red_masses: list[float] = []
    force_constants: list[float] = []
    ir_intensities: list[float] = []
    for line in lines:
        freq_values = standard_frequency_values(line)
        if freq_values is not None:
            frequencies.extend(freq_values)
        elif "Red. masses --" in line:
            red_masses.extend(float(value) for value in line.split("--", 1)[1].split())
        elif "Frc consts  --" in line:
            force_constants.extend(float(value) for value in line.split("--", 1)[1].split())
        elif "IR Inten    --" in line:
            ir_intensities.extend(float(value) for value in line.split("--", 1)[1].split())
    imaginary = [freq for freq in frequencies if freq < 0.0]
    return {
        "frequency_count": len(frequencies),
        "imaginary_frequency_count": len(imaginary),
        "imaginary_frequency_cm-1": imaginary[0] if imaginary else None,
        "imaginary_reduced_mass_amu": red_masses[0] if red_masses else None,
        "imaginary_force_constant_mdyne_per_angstrom": force_constants[0] if force_constants else None,
        "imaginary_ir_intensity_km_per_mol": ir_intensities[0] if ir_intensities else None,
    }


def parse_imaginary_vectors(lines: list[str], natoms: int) -> list[tuple[float, float, float]]:
    """Parse the displacement vectors for the first imaginary frequency."""

    for i, line in enumerate(lines):
        freqs = standard_frequency_values(line)
        if freqs is None:
            continue
        if not freqs or freqs[0] >= 0.0:
            continue
        j = i + 1
        while j < len(lines) and not re.match(r"\s*Atom\s+AN\s+", lines[j]):
            j += 1
        if j >= len(lines):
            raise ValueError("Imaginary frequency block has no displacement table")
        vectors: list[tuple[float, float, float]] = []
        for row in lines[j + 1 : j + 1 + natoms]:
            parts = row.split()
            if len(parts) < 5:
                raise ValueError("Malformed imaginary frequency displacement row")
            vectors.append((float(parts[2]), float(parts[3]), float(parts[4])))
        return vectors
    raise ValueError("No imaginary frequency displacement block found")


def parse_last_mulliken(lines: list[str]) -> dict[int, float]:
    """Return the final Mulliken charge table."""

    return parse_charge_table(lines, "Mulliken charges:", "Sum of Mulliken charges")


def parse_charge_table(lines: list[str], header: str, stop_prefix: str | None = None) -> dict[int, float]:
    """Return the final Gaussian charge table matching ``header``."""

    blocks: list[dict[int, float]] = []
    i = 0
    while i < len(lines):
        if lines[i].strip() != header:
            i += 1
            continue
        i += 1
        block: dict[int, float] = {}
        while i < len(lines):
            if stop_prefix and stop_prefix in lines[i]:
                break
            parts = lines[i].split()
            if len(parts) >= 3 and parts[0].isdigit():
                try:
                    block[int(parts[0])] = parse_gaussian_float_token(parts[2])
                except ValueError:
                    pass
            elif block and (not parts or not parts[0].isdigit()):
                break
            i += 1
        if block:
            blocks.append(block)
    return blocks[-1] if blocks else {}


def parse_frontier_orbitals(lines: list[str]) -> dict[str, float | int | None]:
    """Parse the final alpha/beta frontier orbital block from Gaussian text."""

    blocks: list[dict[str, list[float]]] = []
    current: dict[str, list[float]] = {"alpha_occ": [], "alpha_virt": [], "beta_occ": [], "beta_virt": []}
    saw_virt = False
    for line in lines:
        label = None
        if "Alpha  occ. eigenvalues --" in line or "Alpha occ. eigenvalues --" in line:
            label = "alpha_occ"
        elif "Alpha virt. eigenvalues --" in line:
            label = "alpha_virt"
        elif "Beta  occ. eigenvalues --" in line or "Beta occ. eigenvalues --" in line:
            label = "beta_occ"
        elif "Beta virt. eigenvalues --" in line:
            label = "beta_virt"
        if label is None:
            continue
        if label.endswith("occ") and saw_virt and any(current.values()):
            blocks.append(current)
            current = {"alpha_occ": [], "alpha_virt": [], "beta_occ": [], "beta_virt": []}
            saw_virt = False
        values = [float(value) for value in re.findall(r"[-+]?\d+\.\d+", line.split("--", 1)[1])]
        current[label].extend(values)
        if label.endswith("virt"):
            saw_virt = True
    if any(current.values()):
        blocks.append(current)

    selected = None
    for block in reversed(blocks):
        if block["alpha_occ"] and block["alpha_virt"]:
            selected = block
            break
    if not selected:
        return {}

    alpha_homo = selected["alpha_occ"][-1]
    alpha_lumo = selected["alpha_virt"][0]
    result: dict[str, float | int | None] = {
        "alpha_homo_hartree": alpha_homo,
        "alpha_lumo_hartree": alpha_lumo,
        "alpha_gap_hartree": alpha_lumo - alpha_homo,
        "alpha_homo_ev": alpha_homo * HARTREE_TO_EV,
        "alpha_lumo_ev": alpha_lumo * HARTREE_TO_EV,
        "alpha_gap_ev": (alpha_lumo - alpha_homo) * HARTREE_TO_EV,
        "alpha_occupied_count": len(selected["alpha_occ"]),
        "alpha_virtual_count": len(selected["alpha_virt"]),
    }
    if selected["beta_occ"] and selected["beta_virt"]:
        beta_homo = selected["beta_occ"][-1]
        beta_lumo = selected["beta_virt"][0]
        result.update(
            {
                "beta_homo_hartree": beta_homo,
                "beta_lumo_hartree": beta_lumo,
                "beta_gap_hartree": beta_lumo - beta_homo,
                "beta_homo_ev": beta_homo * HARTREE_TO_EV,
                "beta_lumo_ev": beta_lumo * HARTREE_TO_EV,
                "beta_gap_ev": (beta_lumo - beta_homo) * HARTREE_TO_EV,
                "beta_occupied_count": len(selected["beta_occ"]),
                "beta_virtual_count": len(selected["beta_virt"]),
            }
        )
    return result


def parse_last_dipole(lines: list[str]) -> dict[str, float]:
    """Return the final Gaussian dipole moment block."""

    dipoles: list[dict[str, float]] = []
    pattern = re.compile(
        r"X=\s*([-+]?\d+\.\d+)\s+Y=\s*([-+]?\d+\.\d+)\s+Z=\s*([-+]?\d+\.\d+)\s+Tot=\s*([-+]?\d+\.\d+)"
    )
    for i, line in enumerate(lines):
        if "Dipole moment" not in line:
            continue
        if i + 1 < len(lines):
            match = pattern.search(lines[i + 1])
            if match:
                dipoles.append(
                    {
                        "x_debye": float(match.group(1)),
                        "y_debye": float(match.group(2)),
                        "z_debye": float(match.group(3)),
                        "total_debye": float(match.group(4)),
                    }
                )
    return dipoles[-1] if dipoles else {}


# Standard ``Frequencies --`` lines carry exactly two dashes; ``freq=hpmodes``
# also prints high-precision ``Frequencies ---`` lines that must be skipped.
STANDARD_FREQUENCY_LINE = re.compile(r"\s*Frequencies\s+--\s+(.*)")


def parse_gaussian_frequencies(lines: list[str]) -> list[float]:
    """Parse standard Gaussian frequency rows from one job section."""

    freqs: list[float] = []
    for line in lines:
        match = STANDARD_FREQUENCY_LINE.match(line)
        if not match:
            continue
        freqs.extend(float(part) for part in match.group(1).split())
    return freqs


def parse_convergence_value(token: str) -> float | None:
    """Parse a Gaussian convergence numeric token, tolerating ``****`` overflow."""

    try:
        return float(token.replace("D", "E"))
    except ValueError:
        return None


def parse_gaussian_convergence(lines: list[str]) -> tuple[dict[str, dict[str, str | float]], str | None]:
    """Parse final stationary-point convergence rows from a Gaussian section."""

    convergence_rows: dict[str, dict[str, str | float]] = {}
    stationary_convergence_rows: dict[str, dict[str, str | float]] | None = None
    labels = (
        "Maximum Force",
        "RMS     Force",
        "Maximum Displacement",
        "RMS     Displacement",
    )
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(labels):
            parts = stripped.split()
            if len(parts) >= 5:
                label = " ".join(parts[:2])
                value = parse_convergence_value(parts[2])
                threshold = parse_convergence_value(parts[3])
                convergence_rows[label] = {
                    "value": value if value is not None else parts[2],
                    "threshold": threshold if threshold is not None else parts[3],
                    "converged": parts[4],
                }
        elif "Stationary point found" in stripped and convergence_rows:
            stationary_convergence_rows = {key: dict(value) for key, value in convergence_rows.items()}
    if stationary_convergence_rows is not None:
        return stationary_convergence_rows, "stationary_point"
    if convergence_rows:
        return convergence_rows, "last_section_rows"
    return {}, None


def parse_gaussian_opt_cycle_diagnostics(lines: list[str]) -> dict[str, object]:
    """Parse requested and observed Gaussian Opt step-cycle limits."""

    text = "\n".join(lines)
    requested_values = [int(match) for match in re.findall(r"\bMaxCycles?\s*=\s*(\d+)", text, flags=re.IGNORECASE)]
    printed_pairs = [
        (int(step), int(maximum))
        for step, maximum in re.findall(
            r"Step number\s+(\d+)\s+out of a maximum of\s+(\d+)",
            text,
            flags=re.IGNORECASE,
        )
    ]
    nstep_values = [int(match) for match in re.findall(r"\bNStep\s*=\s*(\d+)", text, flags=re.IGNORECASE)]
    requested = requested_values[-1] if requested_values else None
    printed_step = printed_pairs[-1][0] if printed_pairs else None
    printed = printed_pairs[-1][1] if printed_pairs else None
    nstep = nstep_values[-1] if nstep_values else None
    warnings: list[str] = []
    if requested is not None and printed is not None and requested != printed:
        warnings.append("opt_maxcycle_request_mismatch")
    if any(step == maximum for step, maximum in printed_pairs):
        warnings.append("opt_step_limit_reached")
    return {
        "requested_opt_max_cycles": requested,
        "printed_opt_step": printed_step,
        "printed_opt_maximum_steps": printed,
        "nstep_termination": nstep,
        "max_cycle_request_mismatch": "opt_maxcycle_request_mismatch" in warnings,
        "step_limit_reached": "opt_step_limit_reached" in warnings,
        "warnings": warnings,
    }


def orientation_blocks(lines: list[str], marker: str) -> list[list[tuple[str, float, float, float]]]:
    """Parse Gaussian orientation blocks with element symbols and coordinates."""

    return [
        [(atom.element, atom.x, atom.y, atom.z) for atom in block]
        for block in gaussian_orientation_blocks(lines, marker)
    ]


def final_gaussian_geometry(lines: list[str]) -> list[tuple[str, float, float, float]]:
    """Return the final Standard/Input orientation geometry from a job section."""

    standard = orientation_blocks(lines, "Standard orientation:")
    if standard:
        return standard[-1]
    input_orientation = orientation_blocks(lines, "Input orientation:")
    if input_orientation:
        return input_orientation[-1]
    return []


def parse_gaussian_tsfreq_log(log_path: Path, section_index: int | None = None) -> dict[str, object]:
    """Parse one Gaussian TS/Freq log into validation-neutral backend data."""

    text = log_path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    section = select_gaussian_job_section(lines, section_index)
    section_lines = section["lines"]
    if not isinstance(section_lines, list):
        raise TypeError("internal parser error: section lines are unavailable")
    section_text = "\n".join(section_lines)
    section_frequencies = parse_gaussian_frequencies(section_lines)
    imaginary = [freq for freq in section_frequencies if freq < 0.0]
    atoms = final_gaussian_geometry(section_lines)
    convergence, convergence_source = parse_gaussian_convergence(section_lines)
    opt_cycle_diagnostics = parse_gaussian_opt_cycle_diagnostics(section_lines)
    normal_termination = "Normal termination of Gaussian" in section_text
    error_termination = "Error termination" in section_text
    stationary_point_found = "Stationary point found" in section_text
    final_convergence_evidence_present = bool(convergence)
    final_convergence_satisfied = bool(convergence) and all(
        str(row["converged"]).upper() == "YES" for row in convergence.values()
    )
    validation_failures: list[str] = []
    if not normal_termination:
        validation_failures.append("missing_normal_termination")
    if not stationary_point_found:
        validation_failures.append("missing_stationary_point")
    if len(imaginary) != 1:
        validation_failures.append("imaginary_frequency_count_not_one")
    if not final_convergence_evidence_present:
        validation_failures.append("missing_final_convergence_evidence")
    elif not final_convergence_satisfied:
        validation_failures.append("final_convergence_not_satisfied")
    status = "validated_ts" if not validation_failures else "not_validated_ts"
    summary: dict[str, object] = {
        "status": status,
        "log": str(log_path),
        "section_count": section["section_count"],
        "selected_section_index": section["index"],
        "selected_section_reason": section["selection_reason"],
        "selected_section_start_line": section["start_line"],
        "selected_section_end_line": section["end_line"],
        "normal_termination": normal_termination,
        "error_termination": error_termination,
        "stationary_point_found": stationary_point_found,
        "frequency_count": len(section_frequencies),
        "imaginary_frequency_count": len(imaginary),
        "imaginary_frequencies_cm-1": imaginary,
        "lowest_frequency_cm-1": min(section_frequencies) if section_frequencies else None,
        "electronic_energy_hartree": parse_float(rf"SCF Done:\s+E\([^)]+\)\s+=\s+({GAUSSIAN_FLOAT_TOKEN_RE})", section_text),
        "zero_point_correction_hartree": parse_float(rf"Zero-point correction=\s+({GAUSSIAN_FLOAT_TOKEN_RE})", section_text),
        "thermal_gibbs_correction_hartree": parse_float(
            rf"Thermal correction to Gibbs Free Energy=\s+({GAUSSIAN_FLOAT_TOKEN_RE})", section_text
        ),
        "electronic_plus_zpe_hartree": parse_float(
            rf"Sum of electronic and zero-point Energies=\s+({GAUSSIAN_FLOAT_TOKEN_RE})", section_text
        ),
        "electronic_plus_thermal_free_energy_hartree": parse_float(
            rf"Sum of electronic and thermal Free Energies=\s+({GAUSSIAN_FLOAT_TOKEN_RE})", section_text
        ),
        "force_convergence": convergence,
        "force_convergence_source": convergence_source,
        "opt_cycle_diagnostics": opt_cycle_diagnostics,
        "final_convergence_evidence_present": final_convergence_evidence_present,
        "final_convergence_satisfied": final_convergence_satisfied,
        "validation_failures": validation_failures,
        "final_geometry_atoms": len(atoms),
    }
    return {"summary": summary, "frequencies": section_frequencies, "atoms": atoms}


class GaussianBackendAdapter(FilesystemBackendAdapter):
    """Backend boundary for Gaussian input generation and output parsing."""

    name = "gaussian"

    def prepare(self, request: Mapping[str, Any]) -> BackendInput:
        """Prepare Gaussian input artifacts when an XYZ/output request is supplied."""

        if "xyz" not in request or "output" not in request:
            return super().prepare(request)

        metadata = request.get("metadata", {})
        if not isinstance(metadata, Mapping):
            raise ValueError("backend request metadata must be a mapping")

        output = Path(request["output"])
        frame_index, source_title, coords = read_xyz_frame(Path(request["xyz"]), str(request.get("frame", "only")))
        title = str(request.get("title") or source_title or output.stem)
        chk = str(request.get("chk") or f"{output.stem}.chk")
        route = str(request.get("route") or "#P B3LYP/6-31G(d) opt=(ts,calcfc,noeigen,maxcycles=100) freq")
        extra_sections = tuple(str(section) for section in request.get("extra_sections", ()))
        nproc_value = request.get("nproc", 32)
        mem_value = request.get("mem", "64GB")
        input_request = GaussianInputRequest(
            title=title,
            coords=coords,
            route=route,
            charge=int(request.get("charge", 0)),
            multiplicity=int(request.get("multiplicity", 1)),
            nproc=int(nproc_value) if nproc_value is not None else None,
            mem=str(mem_value) if mem_value is not None else None,
            chk=chk,
            extra_sections=extra_sections,
        )
        write_gaussian_input(output, input_request)
        command_argv = tuple(str(item) for item in request.get("command_argv", ()))
        return BackendInput(
            backend=self.name,
            files=(output,),
            command_argv=command_argv,
            metadata={
                **dict(metadata),
                "frame": frame_index,
                "atoms": len(coords),
                "chk": chk,
                "route_requires_extra_section": route_requires_extra_section(route),
            },
        )

    def parse(self, artifacts: tuple[Path, ...]) -> BackendOutput:
        """Parse Gaussian output artifacts when a log file is present."""

        output = super().parse(artifacts)
        log_path = next(
            (
                artifact
                for artifact in artifacts
                if artifact.exists() and artifact.suffix.lower() in {".out", ".log"}
            ),
            None,
        )
        if log_path is None:
            return output
        parsed = parse_gaussian_tsfreq_log(log_path)
        summary = parsed["summary"]
        properties = dict(output.properties)
        properties.update(
            {
                "parser": "gaussian_tsfreq",
                "summary": summary,
                "frequency_count": summary["frequency_count"],
                "imaginary_frequency_count": summary["imaginary_frequency_count"],
                "status": summary["status"],
            }
        )
        return BackendOutput(
            backend=output.backend,
            artifacts=output.artifacts,
            properties=properties,
            diagnostics=output.diagnostics,
        )
