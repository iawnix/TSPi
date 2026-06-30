"""Gaussian TS/Freq input preparation and artifact parsing."""

from __future__ import annotations

import argparse
import json
import re
import sys
from .base import Backend, BackendTask, PreparedTask
from pathlib import Path
from typing import List, Tuple


Coord = Tuple[str, float, float, float]
Frame = Tuple[str, List[Coord]]


PERIODIC_TABLE = [
    "",
    "H", "He",
    "Li", "Be", "B", "C", "N", "O", "F", "Ne",
    "Na", "Mg", "Al", "Si", "P", "S", "Cl", "Ar",
    "K", "Ca", "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn",
    "Ga", "Ge", "As", "Se", "Br", "Kr",
    "Rb", "Sr", "Y", "Zr", "Nb", "Mo", "Tc", "Ru", "Rh", "Pd", "Ag", "Cd",
    "In", "Sn", "Sb", "Te", "I", "Xe",
    "Cs", "Ba", "La", "Ce", "Pr", "Nd", "Pm", "Sm", "Eu", "Gd", "Tb", "Dy",
    "Ho", "Er", "Tm", "Yb", "Lu", "Hf", "Ta", "W", "Re", "Os", "Ir", "Pt",
    "Au", "Hg", "Tl", "Pb", "Bi", "Po", "At", "Rn",
]


def prepare_gaussian(task: BackendTask) -> PreparedTask:
    gjf = task.inputs["gjf"]
    output = task.settings.get("output", f"nodes/{task.node_id}/outputs/gaussian.out")
    return PreparedTask(
        backend="gaussian",
        node_id=task.node_id,
        command=["g16", gjf],
        input_paths=[gjf],
        expected_artifacts=[output],
    )


class GaussianBackend(Backend):
    name = "gaussian"

    def prepare(self, task: BackendTask) -> PreparedTask:
        return prepare_gaussian(task)


def read_xyz_frames(path: Path) -> list[Frame]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        raise ValueError(f"{path} is empty")

    frames: list[Frame] = []
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

        coords: list[Coord] = []
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


def select_frame(frames: list[Frame], selector: str) -> tuple[int, str, list[Coord]]:
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


def read_xyz(path: Path, frame: str = "only") -> tuple[int, str, list[Coord]]:
    return select_frame(read_xyz_frames(path), frame)


def normalize_route(route: str) -> str:
    route = route.strip()
    if not route:
        raise ValueError("Gaussian route section cannot be empty")
    if route.startswith("#"):
        return route
    return f"#P {route}"


def write_gjf(
    path: Path,
    title: str,
    coords: list[Coord],
    route: str,
    charge: int,
    multiplicity: int,
    nproc: int,
    mem: str,
    chk: str,
    extra_sections: list[str],
) -> None:
    if nproc <= 0:
        raise ValueError("--nproc must be positive")
    if multiplicity <= 0:
        raise ValueError("--multiplicity must be positive")

    lines = [
        f"%chk={chk}",
        f"%nprocshared={nproc}",
        f"%mem={mem}",
        normalize_route(route),
        "",
        title,
        "",
        f"{charge} {multiplicity}",
    ]
    for element, x, y, z in coords:
        lines.append(f"{element:<3s} {x:16.8f} {y:16.8f} {z:16.8f}")
    lines.append("")
    for section in extra_sections:
        section_lines = section.rstrip().splitlines()
        if section_lines:
            lines.extend(section_lines)
            lines.append("")
    lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def read_extra_sections(paths: list[Path]) -> list[str]:
    return [path.read_text(encoding="utf-8") for path in paths]


def route_requires_extra_section(route: str) -> bool:
    normalized = normalize_route(route).lower()
    return bool(re.search(r"(^|[\s/#(),])gen(ecp)?($|[\s/#(),])", normalized))


def compact_route(route: str) -> str:
    route = route.strip()
    route = re.sub(r"^\s*#\s*[pnPN]?\s*", "", route)
    return re.sub(r"\s+", " ", route).strip().lower()


def read_gjf_route(path: Path) -> str:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    route_lines: list[str] = []
    in_route = False
    for line in lines:
        stripped = line.strip()
        if not in_route:
            if stripped.startswith("#"):
                route_lines.append(stripped)
                in_route = True
            continue
        if not stripped:
            break
        route_lines.append(stripped)
    return " ".join(route_lines)


def extract_log_route(lines: list[str]) -> str | None:
    route_lines: list[str] = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith("#"):
            continue
        route_lines.append(stripped)
        for following in lines[index + 1 :]:
            next_line = following.strip()
            if not next_line or next_line.startswith("----"):
                break
            route_lines.append(next_line)
        break
    if not route_lines:
        return None
    return " ".join(route_lines)


def route_settings(route: str | None) -> dict[str, object]:
    if not route:
        return {}
    compacted = compact_route(route)
    settings: dict[str, object] = {
        "route_compact": compacted,
        "has_opt": "opt" in compacted,
        "has_irc": "irc" in compacted,
        "has_freq": "freq" in compacted,
        "has_qst2": "qst2" in compacted,
        "has_qst3": "qst3" in compacted,
    }
    for key in ("maxcycle", "maxcycles", "maxpoints", "stepsize"):
        match = re.search(rf"\b{key}\s*=\s*(\d+)", compacted)
        if match:
            canonical = "maxcycle" if key == "maxcycles" else key
            settings[canonical] = int(match.group(1))
    return settings


def route_expectation(expected_route: str | None, log_route: str | None, text: str) -> dict[str, object]:
    if not expected_route:
        return {"checked": False, "reason": "no_expected_route"}
    expected_compact = compact_route(expected_route)
    log_compact = compact_route(log_route or "")
    expected_settings = route_settings(expected_route)
    log_settings = route_settings(log_route)
    mismatches: list[str] = []
    if not log_compact:
        mismatches.append("missing_log_route")
    elif expected_compact != log_compact:
        mismatches.append("route_text_differs")
    for key in ("maxcycle", "maxpoints", "stepsize"):
        if key in expected_settings and key in log_settings and expected_settings[key] != log_settings[key]:
            mismatches.append(f"{key}_differs")
    effective_maxima = sorted({int(value) for value in re.findall(r"out of a maximum of\s+(\d+)", text, flags=re.I)})
    expected_maxcycle = expected_settings.get("maxcycle")
    if isinstance(expected_maxcycle, int) and effective_maxima and expected_maxcycle not in effective_maxima:
        mismatches.append("maxcycle_not_seen_in_effective_step_limits")
    return {
        "checked": True,
        "matched": not mismatches,
        "mismatches": mismatches,
        "expected_route": expected_route,
        "log_route": log_route,
        "expected_settings": expected_settings,
        "log_settings": log_settings,
        "effective_step_maxima": effective_maxima,
    }


def split_job_sections(lines: list[str]) -> list[dict[str, object]]:
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


def select_job_section(lines: list[str], section_index: int | None = None) -> dict[str, object]:
    sections = split_job_sections(lines)
    if section_index is None:
        section = dict(sections[-1])
        section["selection_reason"] = "default_final_section"
        section["section_count"] = len(sections)
        return section
    if section_index < 0 or section_index >= len(sections):
        raise ValueError(f"section index {section_index} out of range for {len(sections)} section(s)")
    section = dict(sections[section_index])
    section["selection_reason"] = "explicit_section_index"
    section["section_count"] = len(sections)
    return section


def parse_float(pattern: str, text: str) -> float | None:
    matches = re.findall(pattern, text)
    if not matches:
        return None
    value = matches[-1]
    if isinstance(value, tuple):
        value = value[-1]
    return float(value.replace("D", "E"))


def parse_frequencies(lines: list[str]) -> list[float]:
    freqs: list[float] = []
    for line in lines:
        if "Frequencies --" not in line:
            continue
        _, values = line.split("--", 1)
        freqs.extend(float(part) for part in values.split())
    return freqs


def parse_convergence(lines: list[str]) -> tuple[dict[str, dict[str, str | float]], str | None]:
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
                convergence_rows[label] = {
                    "value": float(parts[2].replace("D", "E")),
                    "threshold": float(parts[3].replace("D", "E")),
                    "converged": parts[4],
                }
        elif "Stationary point found" in stripped and convergence_rows:
            stationary_convergence_rows = {key: dict(value) for key, value in convergence_rows.items()}
    if stationary_convergence_rows is not None:
        return stationary_convergence_rows, "stationary_point"
    if convergence_rows:
        return convergence_rows, "last_section_rows"
    return {}, None


def orientation_blocks(lines: list[str], marker: str) -> list[list[Coord]]:
    blocks: list[list[Coord]] = []
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
        atoms: list[Coord] = []
        while j < len(lines) and not lines[j].strip().startswith("----"):
            parts = lines[j].split()
            if len(parts) >= 6:
                try:
                    atomic_number = int(parts[1])
                    element = PERIODIC_TABLE[atomic_number] if atomic_number < len(PERIODIC_TABLE) else f"X{atomic_number}"
                    atoms.append((element, float(parts[3]), float(parts[4]), float(parts[5])))
                except (ValueError, IndexError):
                    pass
            j += 1
        if atoms:
            blocks.append(atoms)
    return blocks


def final_geometry(lines: list[str]) -> list[Coord]:
    standard = orientation_blocks(lines, "Standard orientation:")
    if standard:
        return standard[-1]
    input_orientation = orientation_blocks(lines, "Input orientation:")
    if input_orientation:
        return input_orientation[-1]
    return []


def write_xyz(path: Path, atoms: list[Coord], comment: str) -> None:
    lines = [str(len(atoms)), comment]
    for element, x, y, z in atoms:
        lines.append(f"{element:<3s} {x:16.8f} {y:16.8f} {z:16.8f}")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_log(
    log_path: Path,
    section_index: int | None = None,
    expected_route: str | None = None,
) -> dict[str, object]:
    text = log_path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    section = select_job_section(lines, section_index)
    section_lines = section["lines"]
    if not isinstance(section_lines, list):
        raise TypeError("internal parser error: section lines are unavailable")
    section_text = "\n".join(section_lines)
    log_route = extract_log_route(section_lines)
    section_frequencies = parse_frequencies(section_lines)
    imaginary = [freq for freq in section_frequencies if freq < 0.0]
    atoms = final_geometry(section_lines)
    convergence, convergence_source = parse_convergence(section_lines)
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
        "gaussian_route": log_route,
        "gaussian_route_settings": route_settings(log_route),
        "route_expectation": route_expectation(expected_route, log_route, section_text),
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


def write_parse_artifacts(parsed: dict[str, object], output_dir: Path, log_stem: str, log_name: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = parsed["summary"]
    frequencies = parsed["frequencies"]
    atoms = parsed["atoms"]
    if not isinstance(summary, dict) or not isinstance(frequencies, list) or not isinstance(atoms, list):
        raise TypeError("parsed Gaussian artifact has unexpected shape")
    (output_dir / "validation_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (output_dir / "frequencies_cm-1.txt").write_text(
        "\n".join(f"{float(freq):.6f}" for freq in frequencies) + ("\n" if frequencies else ""),
        encoding="utf-8",
    )
    if atoms:
        write_xyz(output_dir / f"{log_stem}_final.xyz", atoms, f"Final geometry extracted from {log_name}")


def build_prepare_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare a Gaussian TS/frequency input from an XYZ-like structure file.")
    parser.add_argument("xyz", type=Path, help="Input XYZ/extXYZ file. Extra columns are ignored.")
    parser.add_argument("output", type=Path, help="Output Gaussian .gjf/.com path.")
    parser.add_argument(
        "--frame",
        default="only",
        help="XYZ frame selector: only, first, last, or zero-based index. Default refuses multi-frame input.",
    )
    parser.add_argument("--title", help="Gaussian title line. Defaults to the XYZ comment or filename.")
    parser.add_argument("--charge", type=int, default=0)
    parser.add_argument("--multiplicity", type=int, default=1)
    parser.add_argument("--nproc", type=int, default=32)
    parser.add_argument("--mem", default="64GB")
    parser.add_argument("--chk", help="Checkpoint filename. Defaults to <output_stem>.chk.")
    parser.add_argument(
        "--route",
        default="#P B3LYP/6-31G(d) opt=(ts,calcfc,noeigen,maxcycles=100) freq",
        help="Gaussian route section. If it does not start with '#', '#P' is prepended.",
    )
    parser.add_argument(
        "--append-section",
        type=Path,
        action="append",
        default=[],
        help="Append an extra Gaussian input section, e.g. Gen/ECP basis blocks. May be repeated.",
    )
    return parser


def prepare_input_main(argv: list[str] | None = None) -> int:
    args = build_prepare_parser().parse_args(argv)
    frame_index, source_title, coords = read_xyz(args.xyz, args.frame)
    title = args.title or source_title or args.output.stem
    chk = args.chk or f"{args.output.stem}.chk"
    extra_sections = read_extra_sections(args.append_section)
    if route_requires_extra_section(args.route) and not extra_sections:
        print(
            "warning: route appears to use Gen/GenECP but no --append-section was provided",
            file=sys.stderr,
        )
    write_gjf(
        path=args.output,
        title=title,
        coords=coords,
        route=args.route,
        charge=args.charge,
        multiplicity=args.multiplicity,
        nproc=args.nproc,
        mem=args.mem,
        chk=chk,
        extra_sections=extra_sections,
    )
    print(f"Wrote {args.output} with {len(coords)} atoms from frame {frame_index}; chk={chk}")
    return 0


def build_parse_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Parse a Gaussian TS/frequency log and emit validation artifacts.")
    parser.add_argument("log", type=Path, help="Gaussian .log file")
    parser.add_argument("-o", "--output-dir", type=Path, default=None, help="Directory for parsed artifacts")
    parser.add_argument("--section-index", type=int, default=None, help="Evaluate a specific zero-based job section")
    parser.add_argument("--expected-route", help="Expected Gaussian route section for log readback diagnostics")
    parser.add_argument("--input-gjf", type=Path, help="Read expected route from a Gaussian input file")
    parser.add_argument("--strict", action="store_true", help="Return a non-zero exit code if TS validation fails")
    return parser


def parse_result_main(argv: list[str] | None = None) -> int:
    args = build_parse_parser().parse_args(argv)
    expected_route = args.expected_route
    if args.input_gjf is not None:
        expected_route = read_gjf_route(args.input_gjf)
    output_dir = args.output_dir or args.log.with_suffix("").with_name(f"{args.log.stem}_parsed")
    parsed = parse_log(args.log, section_index=args.section_index, expected_route=expected_route)
    summary = parsed["summary"]
    if not isinstance(summary, dict):
        raise TypeError("parsed Gaussian summary has unexpected shape")
    write_parse_artifacts(parsed, output_dir, args.log.stem, args.log.name)

    print(
        f"{summary['status']}: section={summary['selected_section_index']}/{summary['section_count']} "
        f"normal={summary['normal_termination']} "
        f"stationary={summary['stationary_point_found']} imag={summary['imaginary_frequency_count']}"
    )
    if args.strict and summary["status"] != "validated_ts":
        return 2
    return 0
