"""Gaussian External protocol adapter backed by direct xTB execution.

This module implements the Gaussian-driven direction: Gaussian writes EIn
requests, xTB supplies energy, gradient, and Hessian data, and this adapter
writes EOu replies. It is intentionally separate from
``backends.ase_neb.gaussian_external``, where ASE drives the path and Gaussian
supplies forces.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping, Sequence

from transition_state_workflow.backends.ase_neb.contracts import BOHR_TO_ANG
from transition_state_workflow.backends.base import FilesystemBackendAdapter
from transition_state_workflow.backends.contracts import BackendInput, BackendOutput
from transition_state_workflow.backends.xtb import (
    XtbCommandRequest,
    build_xtb_cli_argv,
    normalize_xtb_charge,
    normalize_xtb_method,
    normalize_xtb_uhf,
    parse_xtb_output_text,
)
from transition_state_workflow.chem.gaussian_log import atomic_symbol
from transition_state_workflow.util.cli import CLIBase, CLIResult, CliError


SUMMARY_FILE_NAME = "gaussian_external_xtb_summary.json"
XYZ_FILE_NAME = "gaussian_external_xtb_input.xyz"
XTB_STDOUT_FILE_NAME = "gaussian_external_xtb.xtb.out"
XTB_STDERR_FILE_NAME = "gaussian_external_xtb.xtb.err"
DEFAULT_HESSIAN_FLAG = "--hess"

_FLOAT_PATTERN = re.compile(
    r"[-+]?(?:(?:\d+(?:\.\d*)?)|(?:\.\d+))(?:[EeDd][-+]?\d+)?"
)


class GaussianExternalXtbError(ValueError):
    """Raised for Gaussian External/xTB protocol or artifact failures."""


@dataclass(frozen=True)
class GaussianExternalAtom:
    """One atom from a Gaussian External EIn request."""

    atomic_number: int
    x_bohr: float
    y_bohr: float
    z_bohr: float
    mm_charge: float

    @property
    def symbol(self) -> str:
        """Return the element symbol used in the xTB XYZ input."""

        return atomic_symbol(self.atomic_number)

    def coordinates_angstrom(self) -> tuple[float, float, float]:
        """Return coordinates converted from Bohr to Angstrom."""

        return (
            self.x_bohr * BOHR_TO_ANG,
            self.y_bohr * BOHR_TO_ANG,
            self.z_bohr * BOHR_TO_ANG,
        )


@dataclass(frozen=True)
class GaussianExternalPointCharge:
    """One unsupported embedded point charge from an EIn tail block."""

    x_bohr: float
    y_bohr: float
    z_bohr: float
    charge: float


@dataclass(frozen=True)
class GaussianExternalRequest:
    """Parsed Gaussian External EIn request."""

    natoms: int
    derivative_level: int
    charge: int
    multiplicity: int
    atoms: tuple[GaussianExternalAtom, ...]
    embedded_charges: tuple[GaussianExternalPointCharge, ...] = ()

    @property
    def has_embedded_charges(self) -> bool:
        """True when unsupported MM or point-charge data are present."""

        if self.embedded_charges:
            return True
        return any(abs(atom.mm_charge) > 1.0e-12 for atom in self.atoms)


@dataclass(frozen=True)
class GaussianExternalXtbOptions:
    """Explicit runtime options for the direct xTB command."""

    executable: str = "xtb"
    method: str | int | None = None
    accuracy: float | str | None = None
    iterations: int | str | None = None
    electronic_temperature: float | str | None = None
    solvent: str | None = None
    solvent_model: str = "alpb"
    parallel: int | None = None
    hessian_flag: str = DEFAULT_HESSIAN_FLAG


@dataclass(frozen=True)
class GaussianExternalXtbResult:
    """Result from one EIn -> xTB -> EOu cycle."""

    energy_hartree: float
    gradient: tuple[tuple[float, float, float], ...] | None
    hessian_lower_triangle: tuple[float, ...] | None
    eou_path: Path
    msg_path: Path
    xyz_path: Path
    summary_path: Path
    xtb_argv: tuple[str, ...]
    artifacts: tuple[Path, ...]
    dry_run: bool

    def to_payload(self) -> dict[str, Any]:
        """Return a JSON-serializable result payload."""

        return {
            "ok": True,
            "backend": "gaussian-external-xtb",
            "candidate_only": True,
            "accepted_ts_capable": False,
            "dry_run": self.dry_run,
            "energy_hartree": self.energy_hartree,
            "gradient_values": 0 if self.gradient is None else 3 * len(self.gradient),
            "hessian_lower_triangle_values": (
                0 if self.hessian_lower_triangle is None else len(self.hessian_lower_triangle)
            ),
            "eou": str(self.eou_path),
            "msg": str(self.msg_path),
            "xyz": str(self.xyz_path),
            "summary": str(self.summary_path),
            "xtb_argv": list(self.xtb_argv),
            "artifacts": [str(path) for path in self.artifacts],
        }


def _parse_float(value: str) -> float:
    return float(value.replace("D", "E").replace("d", "E"))


def _numeric_tokens(line: str) -> list[float]:
    return [_parse_float(match.group(0)) for match in _FLOAT_PATTERN.finditer(line)]


def parse_ein_text(text: str) -> GaussianExternalRequest:
    """Parse Gaussian External EIn text."""

    raw_lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not raw_lines:
        raise GaussianExternalXtbError("empty Gaussian External EIn input")

    header = raw_lines[0].split()
    if len(header) < 4:
        raise GaussianExternalXtbError("EIn header must contain natoms, derivative level, charge, multiplicity")
    natoms = int(header[0])
    derivative_level = int(header[1])
    charge = int(header[2])
    multiplicity = int(header[3])
    if natoms <= 0:
        raise GaussianExternalXtbError("EIn atom count must be positive")
    if derivative_level not in {0, 1, 2}:
        raise GaussianExternalXtbError(f"unsupported Gaussian External derivative level: {derivative_level}")
    if multiplicity <= 0:
        raise GaussianExternalXtbError("EIn multiplicity must be positive")
    if len(raw_lines) < 1 + natoms:
        raise GaussianExternalXtbError(f"EIn declares {natoms} atoms but only {len(raw_lines) - 1} atom lines exist")

    atoms: list[GaussianExternalAtom] = []
    for line in raw_lines[1 : 1 + natoms]:
        parts = line.split()
        if len(parts) < 5:
            raise GaussianExternalXtbError("EIn atom line must contain atomic number, x, y, z, and MM charge")
        atoms.append(
            GaussianExternalAtom(
                atomic_number=int(parts[0]),
                x_bohr=_parse_float(parts[1]),
                y_bohr=_parse_float(parts[2]),
                z_bohr=_parse_float(parts[3]),
                mm_charge=_parse_float(parts[4]),
            )
        )

    embedded_charges: list[GaussianExternalPointCharge] = []
    for line in raw_lines[1 + natoms :]:
        values = _numeric_tokens(line)
        if len(values) < 4:
            raise GaussianExternalXtbError(f"unsupported embedded-charge EIn line: {line!r}")
        embedded_charges.append(
            GaussianExternalPointCharge(
                x_bohr=values[0],
                y_bohr=values[1],
                z_bohr=values[2],
                charge=values[3],
            )
        )

    return GaussianExternalRequest(
        natoms=natoms,
        derivative_level=derivative_level,
        charge=charge,
        multiplicity=multiplicity,
        atoms=tuple(atoms),
        embedded_charges=tuple(embedded_charges),
    )


def parse_ein_file(path: Path) -> GaussianExternalRequest:
    """Parse one Gaussian External EIn file."""

    return parse_ein_text(path.read_text(encoding="utf-8", errors="replace"))


def atoms_to_xyz_text(request: GaussianExternalRequest) -> str:
    """Render an xTB XYZ input from a Gaussian External request."""

    lines = [
        str(request.natoms),
        (
            "Gaussian External xTB input; "
            f"charge={request.charge} multiplicity={request.multiplicity} "
            f"derivative_level={request.derivative_level}; coordinates=angstrom"
        ),
    ]
    for atom in request.atoms:
        x_ang, y_ang, z_ang = atom.coordinates_angstrom()
        lines.append(f"{atom.symbol} {x_ang:.12f} {y_ang:.12f} {z_ang:.12f}")
    return "\n".join(lines) + "\n"


def format_eou_float(value: float) -> str:
    """Format one Gaussian External EOu number as D20.12."""

    if not math.isfinite(value):
        raise GaussianExternalXtbError(f"EOu value is not finite: {value!r}")
    return f"{value:20.12E}".replace("E", "D")


def format_eou_values(values: Sequence[float], *, values_per_line: int = 3) -> str:
    """Format EOu values using Gaussian's fixed-width D exponent fields."""

    lines: list[str] = []
    for index in range(0, len(values), values_per_line):
        chunk = values[index : index + values_per_line]
        lines.append("".join(format_eou_float(float(value)) for value in chunk))
    return "\n".join(lines) + ("\n" if lines else "")


def hessian_lower_triangle_from_square(matrix: Sequence[Sequence[float]]) -> tuple[float, ...]:
    """Return row-major lower-triangle values from a square Hessian matrix."""

    dimension = len(matrix)
    lower: list[float] = []
    for row_index, row in enumerate(matrix):
        if len(row) != dimension:
            raise GaussianExternalXtbError("Hessian matrix must be square")
        for col_index in range(row_index + 1):
            lower.append(float(row[col_index]))
    return tuple(lower)


def serialize_eou(
    *,
    energy_hartree: float,
    natoms: int,
    derivative_level: int,
    gradient: Sequence[Sequence[float]] | None = None,
    hessian_lower_triangle: Sequence[float] | None = None,
    dipole: Sequence[float] = (0.0, 0.0, 0.0),
) -> str:
    """Serialize Gaussian External EOu content."""

    if len(dipole) != 3:
        raise GaussianExternalXtbError("EOu dipole must contain three values")
    if derivative_level not in {0, 1, 2}:
        raise GaussianExternalXtbError(f"unsupported derivative level for EOu: {derivative_level}")

    text = format_eou_values((energy_hartree, *dipole), values_per_line=4)
    if derivative_level == 0:
        return text

    if gradient is None or len(gradient) != natoms:
        raise GaussianExternalXtbError("EOu gradient must contain one xyz triple per atom")
    gradient_values: list[float] = []
    for row in gradient:
        if len(row) != 3:
            raise GaussianExternalXtbError("EOu gradient rows must contain three values")
        gradient_values.extend(float(value) for value in row)
    text += format_eou_values(gradient_values, values_per_line=3)
    if derivative_level == 1:
        return text

    dimension = 3 * natoms
    expected_hessian_values = dimension * (dimension + 1) // 2
    if hessian_lower_triangle is None or len(hessian_lower_triangle) != expected_hessian_values:
        raise GaussianExternalXtbError(
            f"EOu Hessian lower triangle must contain {expected_hessian_values} values"
        )
    polarizability = [0.0] * 6
    dipole_derivatives = [0.0] * (9 * natoms)
    text += format_eou_values(
        [*polarizability, *dipole_derivatives, *[float(value) for value in hessian_lower_triangle]],
        values_per_line=3,
    )
    return text


def build_gaussian_external_xtb_argv(
    request: GaussianExternalRequest,
    options: GaussianExternalXtbOptions,
    xyz_path: Path,
) -> tuple[str, ...]:
    """Build the direct xTB argv for one Gaussian External request."""

    if options.hessian_flag not in {"--hess", "--ohess"}:
        raise GaussianExternalXtbError(f"unsupported xTB Hessian flag: {options.hessian_flag!r}")
    extra_args: tuple[str, ...]
    if request.derivative_level == 2:
        extra_args = (options.hessian_flag,)
    elif request.derivative_level == 1:
        extra_args = ("--grad",)
    else:
        extra_args = ()
    return build_xtb_cli_argv(
        XtbCommandRequest(
            input_file=xyz_path,
            task="singlepoint",
            executable=options.executable,
            method=options.method,
            charge=request.charge,
            multiplicity=request.multiplicity,
            accuracy=options.accuracy,
            iterations=options.iterations,
            electronic_temperature=options.electronic_temperature,
            solvent=options.solvent,
            solvent_model=options.solvent_model,
            extra_args=extra_args,
        )
    )


def _read_energy_from_file(path: Path) -> float | None:
    if not path.exists():
        return None
    values = _numeric_tokens(path.read_text(encoding="utf-8", errors="replace"))
    if not values:
        return None
    return float(values[-1])


def read_xtb_energy_hartree(workdir: Path) -> float:
    """Read the final xTB energy in Hartree from known xTB artifacts."""

    log_candidates = [
        workdir / XTB_STDOUT_FILE_NAME,
        workdir / "xtb.out",
        *(path for path in sorted(workdir.iterdir()) if path.suffix.lower() in {".out", ".log"}),
    ]
    seen: set[Path] = set()
    for path in log_candidates:
        if path in seen or not path.exists():
            continue
        seen.add(path)
        parsed = parse_xtb_output_text(path.read_text(encoding="utf-8", errors="replace"))
        energy = parsed.get("electronic_energy_hartree")
        if energy is not None:
            return float(energy)

    for path in (workdir / "energy", workdir / "gradient"):
        energy = _read_energy_from_file(path)
        if energy is not None and path.name == "energy":
            return energy
    gradient_text = (workdir / "gradient").read_text(encoding="utf-8", errors="replace") if (workdir / "gradient").exists() else ""
    energy_matches = re.findall(r"energy\s*=\s*(" + _FLOAT_PATTERN.pattern + r")", gradient_text, flags=re.IGNORECASE)
    if energy_matches:
        return _parse_float(energy_matches[-1])
    raise GaussianExternalXtbError("xTB energy artifact is missing or unparsable")


def parse_xtb_gradient_file(path: Path, *, natoms: int) -> tuple[tuple[float, float, float], ...]:
    """Parse xTB gradient triples in Hartree/Bohr."""

    if not path.exists():
        raise GaussianExternalXtbError("xTB gradient artifact is missing")
    triples: list[tuple[float, float, float]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("$"):
            continue
        parts = stripped.split()
        first_three: list[float] = []
        for token in parts[:3]:
            try:
                first_three.append(_parse_float(token))
            except ValueError:
                first_three = []
                break
        if len(first_three) == 3:
            triples.append((first_three[0], first_three[1], first_three[2]))
    if len(triples) < natoms:
        raise GaussianExternalXtbError(f"xTB gradient artifact has {len(triples)} triples, expected at least {natoms}")
    return tuple(triples[-natoms:])


def parse_xtb_hessian_file(path: Path, *, natoms: int) -> tuple[float, ...]:
    """Parse xTB Hessian values in Hartree/Bohr^2 as a lower triangle."""

    if not path.exists():
        raise GaussianExternalXtbError("xTB Hessian artifact is missing")
    dimension = 3 * natoms
    lower_count = dimension * (dimension + 1) // 2
    rows: list[list[float]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("$"):
            continue
        parts = stripped.split()
        try:
            values = [_parse_float(token) for token in parts]
        except ValueError:
            continue
        if len(values) == dimension:
            rows.append(values)
    if len(rows) >= dimension:
        return hessian_lower_triangle_from_square(rows[-dimension:])

    values = _numeric_tokens(path.read_text(encoding="utf-8", errors="replace"))
    if len(values) == lower_count:
        return tuple(float(value) for value in values)
    if len(values) == dimension * dimension:
        matrix = [values[index : index + dimension] for index in range(0, len(values), dimension)]
        return hessian_lower_triangle_from_square(matrix)
    if len(values) > dimension * dimension:
        square_values = values[-(dimension * dimension) :]
        matrix = [square_values[index : index + dimension] for index in range(0, len(square_values), dimension)]
        return hessian_lower_triangle_from_square(matrix)
    if len(values) > lower_count:
        return tuple(float(value) for value in values[-lower_count:])
    raise GaussianExternalXtbError(
        f"xTB Hessian artifact has {len(values)} numeric values, expected {lower_count} lower-triangle values"
    )


def _mock_gradient(natoms: int) -> tuple[tuple[float, float, float], ...]:
    rows: list[tuple[float, float, float]] = []
    for index in range(1, natoms + 1):
        rows.append((0.001 * index, -0.002 * index, 0.003 * index))
    return tuple(rows)


def _mock_hessian_lower(natoms: int) -> tuple[float, ...]:
    dimension = 3 * natoms
    matrix: list[list[float]] = []
    for row in range(dimension):
        matrix_row: list[float] = []
        for col in range(dimension):
            if row == col:
                matrix_row.append(0.010 * (row + 1))
            else:
                matrix_row.append(0.0001 * (row + col + 2))
        matrix.append(matrix_row)
    return hessian_lower_triangle_from_square(matrix)


def write_mock_xtb_artifacts(workdir: Path, request: GaussianExternalRequest) -> None:
    """Write deterministic xTB-like artifacts for offline dry-run validation."""

    energy = -0.123456789
    (workdir / XTB_STDOUT_FILE_NAME).write_text(
        f"TOTAL ENERGY      {energy:.12f} Eh\nSCF converged\nnormal termination\n",
        encoding="utf-8",
    )
    if request.derivative_level >= 1:
        gradient_lines = ["$grad"]
        for row in _mock_gradient(request.natoms):
            gradient_lines.append(" ".join(f"{value:.12E}" for value in row))
        gradient_lines.append("$end")
        (workdir / "gradient").write_text("\n".join(gradient_lines) + "\n", encoding="utf-8")
    if request.derivative_level >= 2:
        dimension = 3 * request.natoms
        lower = _mock_hessian_lower(request.natoms)
        matrix = [[0.0 for _ in range(dimension)] for _ in range(dimension)]
        cursor = 0
        for row in range(dimension):
            for col in range(row + 1):
                matrix[row][col] = lower[cursor]
                matrix[col][row] = lower[cursor]
                cursor += 1
        lines = ["$hessian"]
        for row in matrix:
            lines.append(" ".join(f"{value:.12E}" for value in row))
        lines.append("$end")
        (workdir / "hessian").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _xtb_environment(options: GaussianExternalXtbOptions) -> dict[str, str] | None:
    if options.parallel is None:
        return None
    if options.parallel <= 0:
        raise GaussianExternalXtbError("parallelism must be a positive integer")
    env = os.environ.copy()
    env["OMP_NUM_THREADS"] = str(options.parallel)
    return env


def run_xtb_command(argv: Sequence[str], *, workdir: Path, options: GaussianExternalXtbOptions) -> None:
    """Run xTB and persist captured stdout/stderr artifacts."""

    try:
        completed = subprocess.run(
            tuple(argv),
            cwd=workdir,
            env=_xtb_environment(options),
            check=False,
            text=True,
            capture_output=True,
        )
    except FileNotFoundError as exc:
        raise GaussianExternalXtbError(f"xTB executable not found: {argv[0]}") from exc
    (workdir / XTB_STDOUT_FILE_NAME).write_text(completed.stdout or "", encoding="utf-8")
    (workdir / XTB_STDERR_FILE_NAME).write_text(completed.stderr or "", encoding="utf-8")
    if completed.returncode != 0:
        raise GaussianExternalXtbError(f"xTB exited with return code {completed.returncode}")


def _collect_artifacts(workdir: Path, extra_paths: Sequence[Path] = ()) -> tuple[Path, ...]:
    names = (
        XYZ_FILE_NAME,
        XTB_STDOUT_FILE_NAME,
        XTB_STDERR_FILE_NAME,
        "xtb.out",
        "energy",
        "gradient",
        "hessian",
        SUMMARY_FILE_NAME,
    )
    artifacts: list[Path] = []
    seen: set[Path] = set()
    for path in [*(workdir / name for name in names), *extra_paths]:
        if path in seen:
            continue
        seen.add(path)
        if path.exists():
            artifacts.append(path)
    return tuple(artifacts)


def run_gaussian_external_xtb(
    *,
    ein_path: Path,
    eou_path: Path,
    msg_path: Path,
    workdir: Path,
    options: GaussianExternalXtbOptions,
    dry_run: bool = False,
) -> GaussianExternalXtbResult:
    """Run one Gaussian External xTB service request."""

    workdir.mkdir(parents=True, exist_ok=True)
    request = parse_ein_file(ein_path)
    if request.has_embedded_charges:
        raise GaussianExternalXtbError(
            "Gaussian-External-xTB does not support embedded MM charges or point-charge EIn tails yet"
        )

    xyz_path = workdir / XYZ_FILE_NAME
    xyz_path.write_text(atoms_to_xyz_text(request), encoding="utf-8")
    xtb_argv = build_gaussian_external_xtb_argv(request, options, xyz_path)

    if dry_run:
        write_mock_xtb_artifacts(workdir, request)
    else:
        run_xtb_command(xtb_argv, workdir=workdir, options=options)

    energy = read_xtb_energy_hartree(workdir)
    gradient = None
    hessian_lower = None
    if request.derivative_level >= 1:
        gradient = parse_xtb_gradient_file(workdir / "gradient", natoms=request.natoms)
    if request.derivative_level >= 2:
        hessian_lower = parse_xtb_hessian_file(workdir / "hessian", natoms=request.natoms)

    eou_path.parent.mkdir(parents=True, exist_ok=True)
    eou_path.write_text(
        serialize_eou(
            energy_hartree=energy,
            natoms=request.natoms,
            derivative_level=request.derivative_level,
            gradient=gradient,
            hessian_lower_triangle=hessian_lower,
        ),
        encoding="utf-8",
    )
    msg_path.parent.mkdir(parents=True, exist_ok=True)
    msg_path.write_text(
        "Gaussian-External-xTB completed; output is candidate/search evidence only.\n",
        encoding="utf-8",
    )

    artifacts = _collect_artifacts(workdir, extra_paths=(eou_path, msg_path))
    summary_path = workdir / SUMMARY_FILE_NAME
    result = GaussianExternalXtbResult(
        energy_hartree=energy,
        gradient=gradient,
        hessian_lower_triangle=hessian_lower,
        eou_path=eou_path,
        msg_path=msg_path,
        xyz_path=xyz_path,
        summary_path=summary_path,
        xtb_argv=xtb_argv,
        artifacts=artifacts,
        dry_run=dry_run,
    )
    summary_path.write_text(json.dumps(result.to_payload(), ensure_ascii=True, indent=2, sort_keys=True) + "\n")
    return result


def _read_summary_artifact(path: Path) -> dict[str, Any] | None:
    if path.is_dir():
        path = path / SUMMARY_FILE_NAME
    if path.name != SUMMARY_FILE_NAME or not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


class GaussianExternalXtbAdapter(FilesystemBackendAdapter):
    """Backend boundary for Gaussian-driven xTB External calculations."""

    name = "gaussian-external-xtb"

    def prepare(self, request: Mapping[str, Any]) -> BackendInput:
        """Prepare a Gaussian External xTB wrapper command."""

        metadata = request.get("metadata", {})
        if not isinstance(metadata, Mapping):
            raise ValueError("backend request metadata must be a mapping")
        files = tuple(request.get("files", ()))
        input_value = request.get("input_file") or request.get("ein") or (files[0] if files else None)
        if input_value is None:
            raise ValueError("Gaussian-External-xTB request requires input_file or ein")
        ein_path = Path(str(input_value))
        workdir = Path(str(request.get("workdir", ein_path.parent)))
        script = Path(str(request.get("script", "scripts/gaussian_external_xtb.py")))
        python_executable = str(request.get("python", "python"))
        eou_path = Path(str(request.get("eou", workdir / "gaussian_external_xtb.EOu")))
        msg_path = Path(str(request.get("msg", workdir / "gaussian_external_xtb.msg")))
        fchk_path = Path(str(request.get("fchk", workdir / "gaussian_external_xtb.fchk")))
        matel_path = Path(str(request.get("matel", workdir / "gaussian_external_xtb.matel")))
        argv = [
            python_executable,
            str(script),
            "--workdir",
            str(workdir),
            "--xtb",
            str(request.get("executable", "xtb")),
        ]
        for option_name, cli_name in (
            ("method", "--method"),
            ("accuracy", "--accuracy"),
            ("iterations", "--iterations"),
            ("electronic_temperature", "--etemp"),
            ("solvent", "--solvent"),
            ("solvent_model", "--solvent-model"),
        ):
            option_value = request.get(option_name)
            if option_value is not None:
                argv.extend((cli_name, str(option_value)))
        if request.get("parallel") is not None:
            argv.extend(("--parallel", str(request["parallel"])))
        if request.get("dry_run"):
            argv.append("--dry-run")
        argv.extend((str(request.get("layer", "external")), str(ein_path), str(eou_path), str(msg_path), str(fchk_path), str(matel_path)))

        try:
            parsed = parse_ein_file(ein_path) if ein_path.exists() else None
        except GaussianExternalXtbError:
            parsed = None
        method_label = normalize_xtb_method(request.get("method")).label
        charge = parsed.charge if parsed is not None else normalize_xtb_charge(request.get("charge"))
        multiplicity = parsed.multiplicity if parsed is not None else request.get("multiplicity")
        uhf = normalize_xtb_uhf(multiplicity=multiplicity, uhf=request.get("uhf"))
        return BackendInput(
            backend=self.name,
            files=(ein_path,),
            command_argv=tuple(argv),
            metadata={
                **dict(metadata),
                "method": method_label,
                "charge": charge,
                "uhf": uhf,
                "candidate_only": True,
                "accepted_ts_capable": False,
            },
        )

    def parse(self, artifacts: tuple[Path, ...]) -> BackendOutput:
        """Parse Gaussian-External-xTB summary artifacts."""

        properties: dict[str, Any] = {
            "artifact_count": len(artifacts),
            "existing_artifacts": sum(1 for artifact in artifacts if artifact.exists()),
            "candidate_only": True,
            "accepted_ts_capable": False,
        }
        diagnostics: list[str] = []
        for artifact in artifacts:
            summary = _read_summary_artifact(artifact)
            if summary is None:
                continue
            properties["summary"] = summary
            if summary.get("energy_hartree") is not None:
                properties["electronic_energy_hartree"] = summary["energy_hartree"]
            break
        else:
            diagnostics.append("gaussian_external_xtb_summary_missing")
        return BackendOutput(
            backend=self.name,
            artifacts=artifacts,
            properties=properties,
            diagnostics=tuple(diagnostics),
        )


class GaussianExternalXtbCLI(CLIBase):
    """CLI entrypoint for Gaussian External xTB requests."""

    description = "Serve one Gaussian External EIn request by running xTB."

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--workdir", type=Path, help="Directory for xTB fixed-name artifacts.")
        parser.add_argument("--xtb", default="xtb", help="xTB executable path.")
        parser.add_argument("--method", help="xTB method such as gfn2, gfn1, gfn0, or gfnff.")
        parser.add_argument("--accuracy", help="xTB --acc value.")
        parser.add_argument("--iterations", help="xTB --iterations value.")
        parser.add_argument("--etemp", dest="electronic_temperature", help="xTB electronic temperature.")
        parser.add_argument("--parallel", type=int, help="OMP_NUM_THREADS value for xTB.")
        parser.add_argument("--solvent", help="xTB solvent name.")
        parser.add_argument("--solvent-model", default="alpb", help="xTB solvent model: alpb or gbsa.")
        parser.add_argument("--dry-run", action="store_true", help="Write deterministic mock xTB artifacts.")
        parser.add_argument("--pretty", action="store_true", help="Pretty-print the JSON result payload.")
        parser.add_argument(
            "external_args",
            nargs="*",
            help="Gaussian External positional arguments: layer EIn EOu Msg FChk MatEl.",
        )

    def execute(self, args: argparse.Namespace) -> CLIResult:
        if len(args.external_args) != 6:
            raise CliError("Gaussian External invocation requires: layer EIn EOu Msg FChk MatEl")
        _layer, ein_arg, eou_arg, msg_arg, _fchk_arg, _matel_arg = args.external_args
        ein_path = Path(ein_arg)
        eou_path = Path(eou_arg)
        msg_path = Path(msg_arg)
        workdir = args.workdir or eou_path.parent or Path.cwd()
        options = GaussianExternalXtbOptions(
            executable=args.xtb,
            method=args.method,
            accuracy=args.accuracy,
            iterations=args.iterations,
            electronic_temperature=args.electronic_temperature,
            solvent=args.solvent,
            solvent_model=args.solvent_model,
            parallel=args.parallel,
        )
        try:
            result = run_gaussian_external_xtb(
                ein_path=ein_path,
                eou_path=eou_path,
                msg_path=msg_path,
                workdir=workdir,
                options=options,
                dry_run=bool(args.dry_run),
            )
        except GaussianExternalXtbError as exc:
            msg_path.parent.mkdir(parents=True, exist_ok=True)
            msg_path.write_text(f"Gaussian-External-xTB failed: {exc}\n", encoding="utf-8")
            raise CliError(str(exc)) from exc
        return CLIResult(payload=result.to_payload(), pretty=args.pretty)


def main(argv: list[str] | None = None) -> int:
    """Run the Gaussian External xTB CLI."""

    return GaussianExternalXtbCLI().main(argv)


__all__ = [
    "DEFAULT_HESSIAN_FLAG",
    "GaussianExternalAtom",
    "GaussianExternalPointCharge",
    "GaussianExternalRequest",
    "GaussianExternalXtbAdapter",
    "GaussianExternalXtbError",
    "GaussianExternalXtbOptions",
    "GaussianExternalXtbResult",
    "atoms_to_xyz_text",
    "build_gaussian_external_xtb_argv",
    "format_eou_float",
    "format_eou_values",
    "hessian_lower_triangle_from_square",
    "main",
    "parse_ein_file",
    "parse_ein_text",
    "parse_xtb_gradient_file",
    "parse_xtb_hessian_file",
    "read_xtb_energy_hartree",
    "run_gaussian_external_xtb",
    "serialize_eou",
    "write_mock_xtb_artifacts",
]
