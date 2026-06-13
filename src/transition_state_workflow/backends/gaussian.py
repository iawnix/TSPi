"""Gaussian backend adapter and TS/Freq log parsing."""

from __future__ import annotations

from pathlib import Path
import re

from transition_state_workflow.backends.base import FilesystemBackendAdapter
from transition_state_workflow.backends.contracts import BackendOutput
from transition_state_workflow.chem.gaussian_log import atomic_symbol


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

    blocks: list[list[tuple[str, float, float, float]]] = []
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
        atoms: list[tuple[str, float, float, float]] = []
        while j < len(lines) and not lines[j].strip().startswith("----"):
            parts = lines[j].split()
            if len(parts) >= 6:
                try:
                    atomic_number = int(parts[1])
                    element = atomic_symbol(atomic_number)
                    atoms.append((element, float(parts[3]), float(parts[4]), float(parts[5])))
                except (ValueError, IndexError):
                    pass
            j += 1
        if atoms:
            blocks.append(atoms)
    return blocks


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
