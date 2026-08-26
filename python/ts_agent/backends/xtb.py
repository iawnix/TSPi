"""xTB command preparation and deterministic artifact parsing."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .base import Backend, BackendTask, PreparedTask
from .xtb_scan import parse_xtb_scan_artifact
from .xyz import xyz_frame_metadata


XTB_TASK_TYPES = frozenset({"sp", "opt", "freq", "opt_freq", "scan", "md"})
XTB_ARTIFACTS = {
    "sp": ("xtb.out",),
    "opt": ("xtbopt.xyz", "xtb.out"),
    "freq": ("vibspectrum", "xtb.out"),
    "opt_freq": ("xtbopt.xyz", "vibspectrum", "xtb.out"),
    "scan": ("xtbscan.log", "xtbopt.xyz", "xtb.out"),
    "md": ("xtb.trj", "xtb.out"),
}
XTB_REQUIRED_ARTIFACTS = {
    task_type: frozenset(artifacts) for task_type, artifacts in XTB_ARTIFACTS.items()
}
_COMMON_SETTINGS = {
    "accuracy",
    "charge",
    "electronic_temperature",
    "method",
    "solvent",
    "solvent_model",
    "uhf",
}
_OPT_LEVELS = {"crude", "sloppy", "loose", "normal", "tight", "verytight", "extreme"}
_FLOAT = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][-+]?\d+)?"


def prepare_xtb(task: BackendTask) -> PreparedTask:
    if task.task_type not in XTB_TASK_TYPES:
        raise ValueError(f"unsupported xTB task_type: {task.task_type}")
    required_inputs = {"xyz", "control"} if task.task_type in {"scan", "md"} else {"xyz"}
    if set(task.inputs) != required_inputs:
        raise ValueError(
            f"xTB {task.task_type} input roles must be exactly {sorted(required_inputs)}"
        )

    allowed_settings = set(_COMMON_SETTINGS)
    if task.task_type in {"opt", "opt_freq", "scan"}:
        allowed_settings.update({"max_cycles", "opt_level"})
    unknown = sorted(set(task.settings) - allowed_settings)
    if unknown:
        raise ValueError(f"unsupported xTB {task.task_type} settings: {unknown}")

    xyz = task.inputs["xyz"]
    command = ["xtb", xyz]
    if task.task_type == "sp":
        command.append("--sp")
    elif task.task_type == "opt":
        command.extend(["--opt", _opt_level(task.settings)])
    elif task.task_type == "freq":
        command.append("--hess")
    elif task.task_type == "opt_freq":
        command.extend(["--ohess", _opt_level(task.settings)])
    elif task.task_type == "scan":
        command.extend(["--opt", _opt_level(task.settings), "--input", task.inputs["control"]])
    else:
        command.extend(["--md", "--input", task.inputs["control"]])
    command.extend(_common_xtb_args(task.settings))
    if "max_cycles" in task.settings:
        command.extend(["--cycles", str(_positive_int(task.settings["max_cycles"], "max_cycles"))])
    return PreparedTask(
        backend="xtb",
        node_id=task.node_id,
        command=command,
        input_paths=[task.inputs[role] for role in ("xyz", "control") if role in task.inputs],
        expected_artifacts=list(XTB_ARTIFACTS[task.task_type]),
    )


def parse_xtb_artifacts(
    task_type: str,
    artifacts: dict[str, Path],
    *,
    control: Path | None = None,
) -> dict[str, Any]:
    if task_type not in XTB_TASK_TYPES:
        raise ValueError(f"unsupported xTB task_type: {task_type}")
    log = artifacts.get("xtb.out")
    if log is None:
        raise ValueError("xTB parsing requires xtb.out")
    text = log.read_text(encoding="utf-8", errors="replace")
    required = XTB_REQUIRED_ARTIFACTS[task_type]
    method = _last_group(text, r"Hamiltonian\s+([A-Za-z0-9-]+)")
    scc_applicable = not _is_gfnff(method)
    presence = {name: name in artifacts and artifacts[name].is_file() for name in sorted(required)}
    summary: dict[str, Any] = {
        "backend": "xtb",
        "task_type": task_type,
        "program_version": _last_group(text, r"\*\s+xtb version\s+(\S+)"),
        "program_call": _last_group(text, r"program call\s*:\s*(.+)"),
        "method": method,
        "charge": _last_int(text, r"net charge\s+(-?\d+)"),
        "unpaired_electrons": _last_int(text, r"unpaired electrons\s+(\d+)"),
        "execution_completed": "* finished run on" in text,
        "normal_termination_marker": "normal termination of xtb" in text.lower(),
        "scc_convergence_applicable": scc_applicable,
        "scc_converged": (
            "convergence criteria satisfied after" in text if scc_applicable else None
        ),
        "scc_iterations": (
            _last_int(text, r"convergence criteria satisfied after\s+(\d+)\s+iterations")
            if scc_applicable
            else None
        ),
        "total_energy_hartree": _last_float(
            text, rf"(?:\||::)\s*TOTAL ENERGY\s+({_FLOAT})\s+Eh"
        ),
        "gradient_norm_hartree_per_bohr": _last_float(
            text, rf"(?:\||::)\s*GRADIENT NORM\s+({_FLOAT})\s+Eh"
        ),
        "homo_lumo_gap_ev": _last_float(
            text, rf"(?:\||::)\s*HOMO-LUMO GAP\s+({_FLOAT})\s+eV"
        ),
        "total_enthalpy_hartree": _last_float(
            text, rf"(?:\||::)\s*TOTAL ENTHALPY\s+({_FLOAT})\s+Eh"
        ),
        "total_free_energy_hartree": _last_float(
            text, rf"(?:\||::)\s*TOTAL FREE ENERGY\s+({_FLOAT})\s+Eh"
        ),
        "zero_point_energy_hartree": _last_float(text, rf"zero point energy\s+({_FLOAT})\s+Eh"),
        "optimization_converged": "GEOMETRY OPTIMIZATION CONVERGED" in text,
        "optimization_iterations": _last_int(
            text,
            r"GEOMETRY OPTIMIZATION CONVERGED AFTER\s+(\d+)\s+(?:ITERATIONS|CYCLES)",
        ),
        "artifact_presence": presence,
        "missing_artifacts": [name for name, present in presence.items() if not present],
    }

    details: dict[str, Any] = {}
    if task_type in {"opt", "opt_freq", "scan"} and "xtbopt.xyz" in artifacts:
        geometry = xyz_frame_metadata(artifacts["xtbopt.xyz"])
        summary["optimized_geometry_atom_count"] = geometry["atom_count"]
        summary["optimized_geometry_energy_hartree"] = geometry["frames"][0].get("energy_hartree")
        details["optimized_geometry"] = geometry
    if task_type in {"freq", "opt_freq"} and "vibspectrum" in artifacts:
        frequencies = parse_vibrational_spectrum(artifacts["vibspectrum"])
        imaginary = [value for value in frequencies if value < 0.0]
        summary.update(
            {
                "frequency_count": len(frequencies),
                "imaginary_frequency_count": len(imaginary),
                "imaginary_frequencies_cm-1": imaginary,
                "lowest_frequency_cm-1": min(frequencies) if frequencies else None,
            }
        )
        details["frequencies_cm-1"] = frequencies
    if task_type == "scan":
        if control is None:
            raise ValueError("xTB scan parsing requires the bound control input")
        scan = parse_xtb_scan_artifact(control, artifacts.get("xtbscan.log"))
        scan_detected = "RELAXED SCAN" in text
        summary.update(scan["summary"])
        summary["scan_detected"] = scan_detected
        summary["scan_complete"] = bool(
            scan_detected and summary.pop("scan_data_complete")
        )
        details["scan_points"] = scan["points"]
    if task_type == "md":
        summary.update(_parse_md_log(text))
        if "xtb.trj" in artifacts:
            trajectory = xyz_frame_metadata(artifacts["xtb.trj"])
            energies = [
                frame["energy_hartree"]
                for frame in trajectory["frames"]
                if frame.get("energy_hartree") is not None
            ]
            summary.update(
                {
                    "trajectory_frame_count": trajectory["frame_count"],
                    "trajectory_first_energy_hartree": energies[0] if energies else None,
                    "trajectory_last_energy_hartree": energies[-1] if energies else None,
                    "trajectory_min_energy_hartree": min(energies) if energies else None,
                    "trajectory_max_energy_hartree": max(energies) if energies else None,
                }
            )
            details["trajectory"] = trajectory

    task_completed = _xtb_task_completed(task_type, summary)
    summary["task_completed"] = task_completed
    summary["artifacts_complete"] = not summary["missing_artifacts"]
    return {"summary": summary, **details}


def write_xtb_parse_artifacts(parsed: dict[str, Any], output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    written = [_write_json(output_dir / "xtb_summary.json", parsed["summary"])]
    if "frequencies_cm-1" in parsed:
        written.append(
            _write_json(
                output_dir / "frequencies.json",
                {"schema_version": "xtb-frequencies/1", "frequencies_cm-1": parsed["frequencies_cm-1"]},
            )
        )
    if "trajectory" in parsed:
        trajectory = parsed["trajectory"]
        written.append(
            _write_json(
                output_dir / "trajectory_summary.json",
                {
                    "schema_version": "xtb-trajectory-summary/1",
                    "atom_count": trajectory["atom_count"],
                    "frame_count": trajectory["frame_count"],
                    "frames": trajectory["frames"],
                },
            )
        )
    if "scan_points" in parsed:
        written.append(_write_json(output_dir / "scan_points.json", parsed["scan_points"]))
    return written


def parse_vibrational_spectrum(path: Path) -> list[float]:
    frequencies: list[float] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        fields = line.split()
        if len(fields) < 3:
            continue
        try:
            int(fields[0])
        except ValueError:
            continue
        try:
            frequency = _number(fields[1])
        except ValueError:
            try:
                frequency = _number(fields[2])
            except ValueError:
                continue
        frequencies.append(frequency)
    if not frequencies:
        raise ValueError(f"xTB vibrational spectrum contains no modes: {path}")
    return frequencies


def _common_xtb_args(settings: dict[str, str]) -> list[str]:
    charge = _integer(settings.get("charge", "0"), "charge")
    uhf = _nonnegative_int(settings.get("uhf", "0"), "uhf")
    method = settings.get("method", "gfn2").lower()
    if method not in {"gfn0", "gfn1", "gfn2", "gfnff"}:
        raise ValueError(f"unsupported xTB method: {method}")
    args = ["--chrg", str(charge), "--uhf", str(uhf)]
    args.extend(["--gfnff"] if method == "gfnff" else ["--gfn", method.removeprefix("gfn")])
    solvent = settings.get("solvent")
    solvent_model = settings.get("solvent_model")
    if (solvent is None) != (solvent_model is None):
        raise ValueError("xTB solvent and solvent_model must be provided together")
    if solvent_model is not None:
        model = solvent_model.lower()
        if model not in {"alpb", "gbsa"}:
            raise ValueError(f"unsupported xTB solvent_model: {solvent_model}")
        args.extend([f"--{model}", str(solvent)])
    if "accuracy" in settings:
        args.extend(["--acc", str(_positive_float(settings["accuracy"], "accuracy"))])
    if "electronic_temperature" in settings:
        args.extend(
            ["--etemp", str(_positive_float(settings["electronic_temperature"], "electronic_temperature"))]
        )
    return args


def _opt_level(settings: dict[str, str]) -> str:
    value = settings.get("opt_level", "normal").lower()
    if value not in _OPT_LEVELS:
        raise ValueError(f"unsupported xTB opt_level: {value}")
    return value


def _parse_md_log(text: str) -> dict[str, Any]:
    return {
        "md_completed": "normal exit of md()" in text.lower(),
        "md_time_ps": _last_float(text, rf"MD time /ps\s*:\s*({_FLOAT})"),
        "md_timestep_fs": _last_float(text, rf"dt /fs\s*:\s*({_FLOAT})"),
        "md_target_temperature_k": _last_float(text, rf"temperature /K\s*:\s*({_FLOAT})"),
        "md_max_steps": _last_int(text, r"max steps\s*:\s*(\d+)"),
        "md_average_potential_energy_hartree": _last_float(text, rf"\n\s*Epot\s*:\s*({_FLOAT})"),
        "md_average_kinetic_energy_hartree": _last_float(text, rf"\n\s*Ekin\s*:\s*({_FLOAT})"),
        "md_average_total_energy_hartree": _last_float(text, rf"\n\s*Etot\s*:\s*({_FLOAT})"),
        "md_average_temperature_k": _last_float(text, rf"\n\s*T\s*:\s*({_FLOAT})"),
    }


def _xtb_task_completed(task_type: str, summary: dict[str, Any]) -> bool:
    electronic_convergence = (
        not summary["scc_convergence_applicable"] or summary["scc_converged"] is True
    )
    common = bool(summary["execution_completed"] and electronic_convergence)
    if task_type == "sp":
        return common and summary["total_energy_hartree"] is not None
    if task_type == "opt":
        return common and bool(summary["optimization_converged"])
    if task_type == "freq":
        return common and bool(summary.get("frequency_count"))
    if task_type == "opt_freq":
        return common and bool(summary["optimization_converged"] and summary.get("frequency_count"))
    if task_type == "scan":
        return common and bool(summary.get("scan_complete"))
    return common and bool(summary.get("md_completed")) and bool(summary.get("trajectory_frame_count"))


def _write_json(path: Path, value: Any) -> Path:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _number(value: str) -> float:
    return float(value.replace("D", "E").replace("d", "e"))


def _last_float(text: str, pattern: str) -> float | None:
    matches = re.findall(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
    return _number(matches[-1]) if matches else None


def _last_int(text: str, pattern: str) -> int | None:
    matches = re.findall(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
    return int(matches[-1]) if matches else None


def _last_group(text: str, pattern: str) -> str | None:
    matches = re.findall(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
    return matches[-1].strip() if matches else None


def _is_gfnff(method: str | None) -> bool:
    return method is not None and method.upper().replace("-", "") == "GFNFF"


def _integer(value: str, label: str) -> int:
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"xTB {label} must be an integer") from exc


def _nonnegative_int(value: str, label: str) -> int:
    parsed = _integer(value, label)
    if parsed < 0:
        raise ValueError(f"xTB {label} must be nonnegative")
    return parsed


def _positive_int(value: str, label: str) -> int:
    parsed = _integer(value, label)
    if parsed <= 0:
        raise ValueError(f"xTB {label} must be positive")
    return parsed


def _positive_float(value: str, label: str) -> float:
    try:
        parsed = _number(value)
    except ValueError as exc:
        raise ValueError(f"xTB {label} must be numeric") from exc
    if parsed <= 0:
        raise ValueError(f"xTB {label} must be positive")
    return parsed


class XtbBackend(Backend):
    name = "xtb"

    def prepare(self, task: BackendTask) -> PreparedTask:
        return prepare_xtb(task)
