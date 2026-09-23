"""PySCF/CF22D command preparation and deterministic result parsing.

The scientific runtime is intentionally optional from the kernel process.  A
prepared task points at a bound Python runtime and the executable runner only
imports PySCF when the calculation process starts.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from ts_agent.runtime import configured_python

from .base import Backend, BackendTask, PreparedTask
from .xyz import xyz_frame_metadata


PYSCF_TASK_TYPES = frozenset(
    {"sp", "opt", "ts", "freq", "thermo", "opt_freq", "ts_freq"}
)
PYSCF_ARTIFACTS: dict[str, tuple[str, ...]] = {
    "sp": ("pyscf.out", "pyscf_result.json"),
    "opt": ("pyscf.out", "pyscf_result.json", "pyscf_geometry.xyz"),
    "ts": ("pyscf.out", "pyscf_result.json", "pyscf_geometry.xyz"),
    "freq": (
        "pyscf.out",
        "pyscf_result.json",
        "pyscf_frequencies.json",
        "pyscf_hessian.npy",
    ),
    "thermo": (
        "pyscf.out",
        "pyscf_result.json",
        "pyscf_frequencies.json",
        "pyscf_hessian.npy",
        "pyscf_thermo.json",
    ),
    "opt_freq": (
        "pyscf.out",
        "pyscf_result.json",
        "pyscf_geometry.xyz",
        "pyscf_frequencies.json",
        "pyscf_hessian.npy",
    ),
    "ts_freq": (
        "pyscf.out",
        "pyscf_result.json",
        "pyscf_geometry.xyz",
        "pyscf_frequencies.json",
        "pyscf_hessian.npy",
    ),
}
PYSCF_REQUIRED_ARTIFACTS = {
    task_type: frozenset(names) for task_type, names in PYSCF_ARTIFACTS.items()
}

_UNITS = {"angstrom", "bohr"}
_RESULT_MAX_BYTES = 8 * 1024 * 1024


def prepare_pyscf(task: BackendTask) -> PreparedTask:
    """Prepare one bounded PySCF workflow without importing PySCF."""

    if task.task_type not in PYSCF_TASK_TYPES:
        raise ValueError(f"unsupported PySCF task_type: {task.task_type}")
    if set(task.inputs) != {"xyz"}:
        raise ValueError("PySCF input roles must be exactly ['xyz']")

    settings = normalize_pyscf_settings(task.settings, task.task_type)
    python = configured_python()
    command = [
        str(python or Path(__import__("sys").executable).resolve()),
        "-m",
        "ts_agent.backends.pyscf_runner",
        "--xyz",
        task.inputs["xyz"],
        "--task",
        task.task_type,
        "--output-dir",
        ".",
    ]
    for option, key in (
        ("--basis", "basis"),
        ("--charge", "charge"),
        ("--spin", "spin"),
        ("--unit", "unit"),
        ("--verbose", "verbose"),
        ("--xc", "xc"),
        ("--grid-level", "grid_level"),
        ("--conv-tol", "conv_tol"),
        ("--max-cycle", "max_cycle"),
        ("--max-steps", "max_steps"),
        ("--threads", "threads"),
        ("--memory-mb", "memory_mb"),
        ("--imaginary-threshold-cm", "imaginary_threshold_cm"),
        ("--temperature", "temperature"),
        ("--pressure", "pressure"),
    ):
        command.extend([option, _format_value(settings[key])])
    if settings["use_initial_hessian"]:
        command.append("--use-initial-hessian")
    elif task.task_type in {"ts", "ts_freq"}:
        # The source runner enables an initial Hessian for TS searches by
        # default. Keep an explicit negative flag so an intent can disable it
        # without being overridden by the task-specific CLI default.
        command.append("--no-use-initial-hessian")

    return PreparedTask(
        backend="pyscf",
        node_id=task.node_id,
        command=command,
        input_paths=[task.inputs["xyz"]],
        expected_artifacts=list(PYSCF_ARTIFACTS[task.task_type]),
    )


def normalize_pyscf_settings(
    settings: dict[str, str], task_type: str | None = None
) -> dict[str, Any]:
    """Normalize capability scalars into the runner's bounded settings."""

    allowed = {
        "basis",
        "charge",
        "spin",
        "unit",
        "verbose",
        "xc",
        "grid_level",
        "conv_tol",
        "max_cycle",
        "max_steps",
        "threads",
        "memory_mb",
        "imaginary_threshold_cm",
        "temperature",
        "pressure",
        "use_initial_hessian",
    }
    unknown = sorted(set(settings) - allowed)
    if unknown:
        raise ValueError(f"unsupported PySCF settings: {unknown}")
    if task_type is not None and task_type not in PYSCF_TASK_TYPES:
        raise ValueError(f"unsupported PySCF task_type: {task_type}")

    unit = str(settings.get("unit", "angstrom")).lower()
    if unit not in _UNITS:
        raise ValueError(f"unsupported PySCF unit: {unit}")
    basis = str(settings.get("basis", "def2-tzvp")).strip()
    xc = str(settings.get("xc", "CF22D")).strip()
    if not basis or len(basis) > 128:
        raise ValueError("PySCF basis must be 1-128 characters")
    if not xc or len(xc) > 128:
        raise ValueError("PySCF xc must be 1-128 characters")
    if xc.upper() != "CF22D":
        raise ValueError("the CF22D backend only permits xc=CF22D")
    xc = "CF22D"

    normalized = {
        "basis": basis,
        "charge": _integer(settings.get("charge", "0"), "charge", -100, 100),
        "spin": _integer(settings.get("spin", "0"), "spin", 0, 200),
        "unit": unit,
        "verbose": _integer(settings.get("verbose", "4"), "verbose", 0, 9),
        "xc": xc,
        "grid_level": _integer(settings.get("grid_level", "6"), "grid_level", 0, 9),
        "conv_tol": _positive_float(settings.get("conv_tol", "1e-10"), "conv_tol", 1.0),
        "max_cycle": _integer(settings.get("max_cycle", "400"), "max_cycle", 1, 100_000),
        "max_steps": _integer(settings.get("max_steps", "100"), "max_steps", 1, 10_000),
        "threads": _integer(settings.get("threads", "1"), "threads", 1, 4096),
        "memory_mb": _integer(settings.get("memory_mb", "4000"), "memory_mb", 1, 4_000_000),
        "imaginary_threshold_cm": _negative_float(
            settings.get("imaginary_threshold_cm", "-20"), "imaginary_threshold_cm"
        ),
        "temperature": _bounded_float(
            settings.get("temperature", "298.15"), "temperature", 0.0, 10_000.0
        ),
        "pressure": _positive_float(settings.get("pressure", "101325"), "pressure", 10_000_000.0),
        "use_initial_hessian": _boolean(
            settings.get(
                "use_initial_hessian",
                "true" if task_type in {"ts", "ts_freq"} else "false",
            ),
            "use_initial_hessian",
        ),
    }
    return normalized


def parse_pyscf_artifacts(
    task_type: str,
    artifacts: dict[str, Path],
    *,
    expected_settings: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Parse the fixed runner manifest and verify artifact bindings."""

    if task_type not in PYSCF_TASK_TYPES:
        raise ValueError(f"unsupported PySCF task_type: {task_type}")
    result_path = artifacts.get("pyscf_result.json")
    if result_path is None:
        raise ValueError("PySCF parsing requires pyscf_result.json")
    if result_path.stat().st_size > _RESULT_MAX_BYTES:
        raise ValueError("PySCF result exceeds 8 MiB")
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("PySCF result is not valid UTF-8 JSON") from exc
    if not isinstance(result, dict):
        raise ValueError("PySCF result must be a JSON object")
    if result.get("schema_version") != "pyscf-run/1":
        raise ValueError("unsupported PySCF result schema")
    if result.get("backend") != "pyscf" or result.get("task_type") != task_type:
        raise ValueError("PySCF result does not match the requested task")

    required = PYSCF_REQUIRED_ARTIFACTS[task_type]
    presence = {
        name: bool(
            name in artifacts
            and artifacts[name].is_file()
            and artifacts[name].stat().st_size > 0
        )
        for name in sorted(required)
    }
    missing = [name for name, present in presence.items() if not present]
    summary = result.get("summary")
    if not isinstance(summary, dict):
        raise ValueError("PySCF result summary must be an object")
    summary = dict(summary)
    summary.update(
        {
            "backend": "pyscf",
            "task_type": task_type,
            "execution_completed": result.get("execution_completed") is True,
            "program_version": result.get("pyscf_version"),
            "artifact_presence": presence,
            "missing_artifacts": missing,
            "output_completion_marker": _completion_marker(artifacts),
        }
    )

    run_settings = result.get("settings")
    settings_match = _settings_match(run_settings, expected_settings, task_type)
    summary["settings_match"] = settings_match
    _enforce_optimization_evidence(summary, task_type)

    parsed: dict[str, Any] = {"summary": summary}
    if "pyscf_frequencies.json" in artifacts:
        try:
            frequencies = json.loads(
                artifacts["pyscf_frequencies.json"].read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("PySCF frequency artifact is not valid JSON") from exc
        _validate_frequency_payload(frequencies)
        _check_frequency_summary(summary, frequencies)
        parsed["frequencies"] = frequencies
    if "pyscf_thermo.json" in artifacts:
        try:
            thermo = json.loads(artifacts["pyscf_thermo.json"].read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("PySCF thermochemistry artifact is not valid JSON") from exc
        _validate_thermo_payload(thermo)
        _check_thermo_summary(summary, thermo)
        parsed["thermochemistry"] = thermo
    if "pyscf_geometry.xyz" in artifacts:
        geometry = xyz_frame_metadata(artifacts["pyscf_geometry.xyz"])
        atom_count = summary.get("optimized_geometry_atom_count")
        if atom_count is not None and geometry.get("atom_count") != atom_count:
            raise ValueError("PySCF geometry atom count does not match result summary")
        parsed["geometry"] = geometry
    return parsed


def write_pyscf_parse_artifacts(parsed: dict[str, Any], output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    written = [_write_json(output_dir / "pyscf_summary.json", parsed["summary"])]
    if "frequencies" in parsed:
        written.append(_write_json(output_dir / "pyscf_frequencies.json", parsed["frequencies"]))
    if "thermochemistry" in parsed:
        written.append(_write_json(output_dir / "pyscf_thermo.json", parsed["thermochemistry"]))
    if "geometry" in parsed:
        written.append(_write_json(output_dir / "pyscf_geometry.json", parsed["geometry"]))
    return written


class PyscfBackend(Backend):
    name = "pyscf"

    def prepare(self, task: BackendTask) -> PreparedTask:
        return prepare_pyscf(task)


def _settings_match(
    actual: Any, expected: dict[str, str] | None, task_type: str
) -> bool:
    if expected is None:
        return True
    if not isinstance(actual, dict):
        return False
    try:
        normalized = normalize_pyscf_settings(expected, task_type)
    except ValueError:
        return False
    for key, value in normalized.items():
        if key not in actual:
            return False
        candidate = actual[key]
        if isinstance(value, bool):
            if isinstance(candidate, str):
                candidate = candidate.strip().lower() in {"true", "1", "yes", "on"}
            if bool(candidate) != value:
                return False
        elif isinstance(value, float):
            try:
                if not math.isclose(float(candidate), value, rel_tol=1e-12, abs_tol=1e-12):
                    return False
            except (TypeError, ValueError):
                return False
        elif str(candidate) != str(value):
            return False
    return True


def _completion_marker(artifacts: dict[str, Path]) -> bool:
    output = artifacts.get("pyscf.out")
    if output is None or not output.is_file():
        return False
    return "PYSCF_RUN_COMPLETED" in output.read_text(encoding="utf-8", errors="replace")


def _validate_frequency_payload(value: Any) -> None:
    if not isinstance(value, dict) or value.get("schema_version") != "pyscf-frequencies/1":
        raise ValueError("PySCF frequency artifact has an invalid schema")
    frequencies = value.get("frequencies_cm-1")
    imaginary = value.get("imaginary_frequencies_cm-1")
    if not isinstance(frequencies, list) or not isinstance(imaginary, list):
        raise ValueError("PySCF frequency artifact must contain frequency arrays")
    if not all(_finite_number(item) for item in [*frequencies, *imaginary]):
        raise ValueError("PySCF frequency artifact contains non-finite values")
    threshold = value.get("imaginary_threshold_cm")
    if not _finite_number(threshold) or float(threshold) >= 0.0:
        raise ValueError("PySCF frequency artifact has an invalid imaginary threshold")
    if any(float(item) >= 0.0 for item in imaginary):
        raise ValueError("PySCF imaginary frequency artifact contains a non-negative mode")
    expected_imaginary = [item for item in frequencies if float(item) < float(threshold)]
    if len(expected_imaginary) != len(imaginary) or any(
        not math.isclose(float(actual), float(expected), rel_tol=1e-12, abs_tol=1e-12)
        for actual, expected in zip(imaginary, expected_imaginary)
    ):
        raise ValueError("PySCF frequency artifact imaginary modes do not match its threshold")
    if value.get("n_modes") != len(frequencies) or value.get("n_imaginary") != len(imaginary):
        raise ValueError("PySCF frequency artifact counts are inconsistent")


def _check_frequency_summary(summary: dict[str, Any], frequencies: dict[str, Any]) -> None:
    for summary_key, artifact_key in (
        ("frequency_count", "n_modes"),
        ("imaginary_frequency_count", "n_imaginary"),
    ):
        value = summary.get(summary_key)
        if value is not None and value != frequencies.get(artifact_key):
            raise ValueError(
                f"PySCF frequency summary {summary_key} disagrees with the frequency artifact"
            )
    summary_imaginary = summary.get("imaginary_frequencies_cm-1")
    artifact_imaginary = frequencies.get("imaginary_frequencies_cm-1")
    if summary_imaginary is not None and summary_imaginary != artifact_imaginary:
        raise ValueError("PySCF frequency summary imaginary modes disagree with the artifact")


def _enforce_optimization_evidence(summary: dict[str, Any], task_type: str) -> None:
    if task_type not in {"opt", "ts", "opt_freq", "ts_freq"}:
        return
    present = summary.get("optimization_convergence_evidence_present")
    satisfied = summary.get("optimization_convergence_satisfied")
    if present is not True or not isinstance(satisfied, bool):
        # A successful process alone is not proof that geomeTRIC reached its
        # convergence criteria.  Make task validation fail closed when a
        # runner version omitted the evidence fields or reported them as null.
        summary["optimization_converged"] = None
        return
    summary["optimization_converged"] = satisfied


def _validate_thermo_payload(value: Any) -> None:
    if not isinstance(value, dict) or value.get("schema_version") != "pyscf-thermo/1":
        raise ValueError("PySCF thermochemistry artifact has an invalid schema")
    for key in ("temperature_K", "pressure_Pa"):
        if not _finite_number(value.get(key)):
            raise ValueError(f"PySCF thermochemistry artifact is missing {key}")
    for key in (
        "electronic_energy_hartree",
        "zpe_hartree",
        "energy_0k_hartree",
        "thermal_energy_hartree",
        "enthalpy_hartree",
        "entropy",
        "gibbs_hartree",
        "thermal_energy_correction_hartree",
        "enthalpy_correction_hartree",
        "gibbs_correction_hartree",
    ):
        if not _finite_number(value.get(key)):
            raise ValueError(f"PySCF thermochemistry artifact is missing {key}")
    electronic = float(value["electronic_energy_hartree"])
    for total_key, correction_key in (
        ("thermal_energy_hartree", "thermal_energy_correction_hartree"),
        ("enthalpy_hartree", "enthalpy_correction_hartree"),
        ("gibbs_hartree", "gibbs_correction_hartree"),
    ):
        expected = float(value[total_key]) - electronic
        if not math.isclose(
            float(value[correction_key]), expected, rel_tol=1e-12, abs_tol=1e-12
        ):
            raise ValueError(
                f"PySCF thermochemistry artifact {correction_key} is inconsistent"
            )


def _check_thermo_summary(summary: dict[str, Any], thermo: dict[str, Any]) -> None:
    summary_gibbs = summary.get("gibbs_hartree")
    thermo_gibbs = thermo.get("gibbs_hartree")
    if summary_gibbs is not None and not math.isclose(
        float(summary_gibbs), float(thermo_gibbs), rel_tol=1e-12, abs_tol=1e-12
    ):
        raise ValueError("PySCF thermochemistry summary disagrees with the artifact")


def _finite_number(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _write_json(path: Path, value: Any) -> Path:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True, default=str) + "\n",
        encoding="utf-8",
    )
    return path


def _format_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return format(value, ".15g")
    return str(value)


def _integer(value: Any, label: str, lower: int, upper: int) -> int:
    try:
        parsed = int(str(value), 10)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"PySCF {label} must be an integer") from exc
    if not lower <= parsed <= upper:
        raise ValueError(f"PySCF {label} must be between {lower} and {upper}")
    return parsed


def _bounded_float(value: Any, label: str, lower: float, upper: float) -> float:
    try:
        parsed = float(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"PySCF {label} must be numeric") from exc
    if not math.isfinite(parsed) or not lower <= parsed <= upper:
        raise ValueError(f"PySCF {label} must be finite and between {lower} and {upper}")
    return parsed


def _positive_float(value: Any, label: str, upper: float) -> float:
    parsed = _bounded_float(value, label, 0.0, upper)
    if parsed <= 0.0:
        raise ValueError(f"PySCF {label} must be positive")
    return parsed


def _negative_float(value: Any, label: str) -> float:
    try:
        parsed = float(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"PySCF {label} must be numeric") from exc
    if not math.isfinite(parsed) or parsed >= 0.0:
        raise ValueError(f"PySCF {label} must be negative and finite")
    return parsed


def _boolean(value: Any, label: str) -> bool:
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes", "on"}:
        return True
    if normalized in {"false", "0", "no", "off"}:
        return False
    raise ValueError(f"PySCF {label} must be boolean")


__all__ = [
    "PYSCF_ARTIFACTS",
    "PYSCF_REQUIRED_ARTIFACTS",
    "PYSCF_TASK_TYPES",
    "PyscfBackend",
    "normalize_pyscf_settings",
    "parse_pyscf_artifacts",
    "prepare_pyscf",
    "write_pyscf_parse_artifacts",
]
