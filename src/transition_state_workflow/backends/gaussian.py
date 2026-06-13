"""Gaussian backend adapter and TS/Freq log parsing."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Mapping

from transition_state_workflow.backends.base import FilesystemBackendAdapter
from transition_state_workflow.backends.contracts import BackendInput, BackendOutput
from transition_state_workflow.chem.gaussian_log import orientation_blocks as gaussian_orientation_blocks

GaussianCoord = tuple[str, float, float, float]
GaussianFrame = tuple[str, list[GaussianCoord]]


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


def parse_float(pattern: str, text: str) -> float | None:
    """Return the last float matching ``pattern`` in Gaussian text."""

    matches = re.findall(pattern, text)
    if not matches:
        return None
    value = matches[-1]
    if isinstance(value, tuple):
        value = value[-1]
    return float(value.replace("D", "E"))


def parse_gaussian_energy_hartree(output_path: Path) -> float:
    """Return the last SCF energy from a Gaussian output in hartree."""

    scf_re = re.compile(
        r"SCF Done:\s+E\([^)]+\)\s+=\s+([-+]?\d+\.\d+(?:[DEde][-+]?\d+)?)"
    )
    energy = None
    with output_path.open("r", errors="ignore") as handle:
        for line in handle:
            match = scf_re.search(line)
            if match:
                energy = float(match.group(1).replace("D", "E").replace("d", "E"))
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
        "electronic_energy_hartree": parse_float(r"SCF Done:\s+E\([RU]?\w+\)\s+=\s+([-+]?\d+\.\d+)", section_text),
        "zero_point_correction_hartree": parse_float(r"Zero-point correction=\s+([-+]?\d+\.\d+)", section_text),
        "thermal_gibbs_correction_hartree": parse_float(
            r"Thermal correction to Gibbs Free Energy=\s+([-+]?\d+\.\d+)", section_text
        ),
        "electronic_plus_zpe_hartree": parse_float(
            r"Sum of electronic and zero-point Energies=\s+([-+]?\d+\.\d+)", section_text
        ),
        "electronic_plus_thermal_free_energy_hartree": parse_float(
            r"Sum of electronic and thermal Free Energies=\s+([-+]?\d+\.\d+)", section_text
        ),
        "force_convergence": convergence,
        "force_convergence_source": convergence_source,
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
