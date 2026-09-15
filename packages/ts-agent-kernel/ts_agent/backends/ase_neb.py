"""ASE NEB preparation and deterministic artifact parsing."""

from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path
from typing import Any

import numpy as np

from ts_agent.runtime import configured_python

from .base import Backend, BackendTask, PreparedTask


ASE_NEB_ARTIFACTS = (
    "ase_neb.out",
    "neb.traj",
    "neb_path.xyz",
    "neb_summary.json",
)
ASE_NEB_REQUIRED_ARTIFACTS = frozenset(ASE_NEB_ARTIFACTS)
_FLOAT = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][-+]?\d+)?"
_SOLVENT = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")
_MAX_SUMMARY_BYTES = 1024 * 1024
_POSITION_TOLERANCE_ANGSTROM = 1.0e-7
_ENERGY_TOLERANCE_EV = 1.0e-7
_RUN_REQUIRED_FIELDS = frozenset(
    {
        "schema_version",
        "backend",
        "task_type",
        "execution_completed",
        "ase_version",
        "calculator",
        "calculator_version",
        "method",
        "charge",
        "uhf",
        "accuracy",
        "electronic_temperature",
        "solvent_model",
        "solvent",
        "optimizer",
        "interpolation",
        "climb",
        "remove_rotation_and_translation",
        "spring_constant_ev_per_angstrom2",
        "fmax_ev_per_angstrom",
        "max_steps",
        "steps",
        "converged",
        "atom_count",
        "image_count",
        "image_energies_ev",
        "highest_energy_image_index",
        "barrier_forward_ev",
        "barrier_reverse_ev",
        "max_neb_force_ev_per_angstrom",
    }
)


def prepare_ase_neb(task: BackendTask) -> PreparedTask:
    if task.task_type != "neb":
        raise ValueError(f"unsupported ASE NEB task_type: {task.task_type}")
    if set(task.inputs) != {"reactant", "product"}:
        raise ValueError("ASE NEB input roles must be exactly ['product', 'reactant']")

    settings = normalize_ase_neb_settings(task.settings)

    python = configured_python() or Path(sys.executable).resolve()
    command = [
        str(python),
        "-m",
        "ts_agent.backends.ase_neb_runner",
        "--reactant",
        task.inputs["reactant"],
        "--product",
        task.inputs["product"],
        "--images",
        str(settings["images"]),
        "--fmax",
        _format_number(settings["fmax"]),
        "--max-steps",
        str(settings["max_steps"]),
        "--spring-constant",
        _format_number(settings["spring_constant"]),
        "--interpolation",
        settings["interpolation"],
        "--method",
        settings["method"],
        "--charge",
        str(settings["charge"]),
        "--uhf",
        str(settings["uhf"]),
        "--climb",
        str(settings["climb"]).lower(),
        "--remove-rotation-and-translation",
        str(settings["remove_rotation_and_translation"]).lower(),
    ]
    if settings["accuracy"] is not None:
        command.extend(["--accuracy", _format_number(settings["accuracy"])])
    if settings["electronic_temperature"] is not None:
        command.extend(
            ["--electronic-temperature", _format_number(settings["electronic_temperature"])]
        )
    if settings["solvent"] is not None and settings["solvent_model"] is not None:
        command.extend(
            ["--solvent-model", settings["solvent_model"], "--solvent", settings["solvent"]]
        )

    return PreparedTask(
        backend="ase_neb",
        node_id=task.node_id,
        command=command,
        input_paths=[task.inputs["reactant"], task.inputs["product"]],
        expected_artifacts=list(ASE_NEB_ARTIFACTS),
    )


def normalize_ase_neb_settings(settings: dict[str, str]) -> dict[str, Any]:
    allowed = {
        "accuracy",
        "charge",
        "climb",
        "electronic_temperature",
        "fmax",
        "images",
        "interpolation",
        "max_steps",
        "method",
        "remove_rotation_and_translation",
        "solvent",
        "solvent_model",
        "spring_constant",
        "uhf",
    }
    unknown = sorted(set(settings) - allowed)
    if unknown:
        raise ValueError(f"unsupported ASE NEB settings: {unknown}")
    method = settings.get("method", "gfn2").lower()
    if method not in {"gfn1", "gfn2"}:
        raise ValueError(f"unsupported ASE NEB xTB method: {method}")
    interpolation = settings.get("interpolation", "idpp").lower()
    if interpolation not in {"linear", "idpp"}:
        raise ValueError(f"unsupported ASE NEB interpolation: {interpolation}")
    solvent = settings.get("solvent")
    solvent_model = settings.get("solvent_model")
    if (solvent is None) != (solvent_model is None):
        raise ValueError("ASE NEB solvent and solvent_model must be provided together")
    if solvent is not None and _SOLVENT.fullmatch(solvent) is None:
        raise ValueError("ASE NEB solvent must be a safe xTB solvent name")
    if solvent_model is not None and solvent_model.lower() not in {"alpb", "gbsa"}:
        raise ValueError(f"unsupported ASE NEB solvent_model: {solvent_model}")
    return {
        "images": _bounded_int(settings.get("images", "7"), "images", 3, 32),
        "fmax": _bounded_float(settings.get("fmax", "0.05"), "fmax", 0.0, 10.0),
        "max_steps": _bounded_int(settings.get("max_steps", "500"), "max_steps", 1, 100_000),
        "spring_constant": _bounded_float(
            settings.get("spring_constant", "0.1"),
            "spring_constant",
            0.0,
            10.0,
        ),
        "interpolation": interpolation,
        "climb": _boolean(settings.get("climb", "false"), "climb"),
        "remove_rotation_and_translation": _boolean(
            settings.get("remove_rotation_and_translation", "true"),
            "remove_rotation_and_translation",
        ),
        "method": method,
        "charge": _bounded_int(settings.get("charge", "0"), "charge", -100, 100),
        "uhf": _bounded_int(settings.get("uhf", "0"), "uhf", 0, 100),
        "accuracy": (
            _bounded_float(settings["accuracy"], "accuracy", 0.0, 100.0)
            if "accuracy" in settings
            else None
        ),
        "electronic_temperature": (
            _bounded_float(
                settings["electronic_temperature"],
                "electronic_temperature",
                0.0,
                1_000_000.0,
                lower_inclusive=True,
            )
            if "electronic_temperature" in settings
            else None
        ),
        "solvent_model": solvent_model.lower() if solvent_model is not None else None,
        "solvent": solvent,
    }


def validate_ase_neb_endpoints(reactant: Path, product: Path) -> dict[str, Any]:
    reactant_frames = _read_xyz_records(reactant)
    product_frames = _read_xyz_records(product)
    if len(reactant_frames) != 1 or len(product_frames) != 1:
        raise ValueError("ASE NEB endpoints must each contain exactly one XYZ frame")
    first = reactant_frames[0]
    last = product_frames[0]
    if first["symbols"] != last["symbols"]:
        raise ValueError("ASE NEB endpoints must have identical atom identities and ordering")
    if _coordinates_equivalent(
        first["coordinates"],
        last["coordinates"],
        allow_rigid_transform=True,
    ):
        raise ValueError("ASE NEB endpoints must differ beyond rigid rotation and translation")
    return {"atom_count": len(first["symbols"]), "symbols": list(first["symbols"])}


def parse_ase_neb_artifacts(
    artifacts: dict[str, Path],
    *,
    reactant: Path | None = None,
    product: Path | None = None,
    expected_settings: dict[str, str] | None = None,
) -> dict[str, Any]:
    summary_path = artifacts.get("neb_summary.json")
    if summary_path is None:
        raise ValueError("ASE NEB parsing requires neb_summary.json")
    if summary_path.stat().st_size > _MAX_SUMMARY_BYTES:
        raise ValueError("ASE NEB summary exceeds 1 MiB")
    try:
        run = json.loads(summary_path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("ASE NEB summary is not valid UTF-8 JSON") from exc
    _validate_run_summary(run)

    presence = {
        name: bool(
            name in artifacts
            and artifacts[name].is_file()
            and artifacts[name].stat().st_size > 0
        )
        for name in sorted(ASE_NEB_REQUIRED_ARTIFACTS)
    }
    stdout = artifacts.get("ase_neb.out")
    completion_marker = bool(
        stdout is not None
        and presence["ase_neb.out"]
        and "ASE_NEB_RUN_COMPLETED" in stdout.read_text(encoding="utf-8", errors="replace")
    )

    path_records: list[dict[str, Any]] = []
    if presence["neb_path.xyz"]:
        path_records = _read_xyz_records(artifacts["neb_path.xyz"])
    path_image_count = len(path_records)
    path_atom_count = len(path_records[0]["symbols"]) if path_records else 0
    path_symbols_consistent = bool(path_records) and all(
        frame["symbols"] == path_records[0]["symbols"] for frame in path_records
    )
    path_atom_counts_consistent = bool(path_records) and all(
        len(frame["symbols"]) == path_atom_count for frame in path_records
    )
    path_energies_ev = [
        frame["energy_ev"]
        for frame in path_records
    ]
    expected_energies = run["image_energies_ev"]
    image_energies_complete = bool(path_records) and len(path_energies_ev) == len(expected_energies) and all(
        observed is not None
        and math.isclose(observed, expected, rel_tol=0.0, abs_tol=_ENERGY_TOLERANCE_EV)
        for observed, expected in zip(path_energies_ev, expected_energies)
    )

    endpoint_match: bool | None = None
    if reactant is not None and product is not None and path_records:
        endpoints = validate_ase_neb_endpoints(reactant, product)
        reactant_record = _read_xyz_records(reactant)[0]
        product_record = _read_xyz_records(product)[0]
        endpoint_match = bool(
            endpoints["symbols"] == path_records[0]["symbols"] == path_records[-1]["symbols"]
            and _coordinates_equivalent(
                reactant_record["coordinates"],
                path_records[0]["coordinates"],
                allow_rigid_transform=run["remove_rotation_and_translation"],
            )
            and _coordinates_equivalent(
                product_record["coordinates"],
                path_records[-1]["coordinates"],
                allow_rigid_transform=run["remove_rotation_and_translation"],
            )
        )

    path_complete = bool(
        path_image_count == run["image_count"]
        and path_atom_count == run["atom_count"]
        and path_symbols_consistent
        and path_atom_counts_consistent
        and image_energies_complete
        and endpoint_match is not False
    )
    force_threshold_satisfied = bool(
        run["max_neb_force_ev_per_angstrom"] <= run["fmax_ev_per_angstrom"] + 1.0e-12
    )
    settings_match: bool | None = None
    if expected_settings is not None:
        settings_match = _run_settings_match(run, normalize_ase_neb_settings(expected_settings))
    summary = {
        key: value
        for key, value in run.items()
        if key not in {"schema_version", "image_energies_ev"}
    }
    summary.update(
        {
            "program_version": run["ase_version"],
            "execution_completed": bool(run["execution_completed"] and completion_marker),
            "path_image_count": path_image_count,
            "path_atom_count": path_atom_count,
            "path_complete": path_complete,
            "endpoint_match": endpoint_match,
            "image_energies_complete": image_energies_complete,
            "image_energies_ev": list(expected_energies),
            "force_threshold_satisfied": force_threshold_satisfied,
            "settings_match": settings_match,
            "artifact_presence": presence,
            "missing_artifacts": [name for name, present in presence.items() if not present],
        }
    )
    return {
        "summary": summary,
        "reaction_path": {
            "schema_version": "ase-neb-reaction-path/1",
            "energy_unit": "eV",
            "distance_unit": "angstrom",
            "images": [
                {
                    "index": index,
                    "symbols": list(frame["symbols"]),
                    "coordinates": frame["coordinates"],
                    "energy_ev": path_energies_ev[index],
                }
                for index, frame in enumerate(path_records)
            ],
        },
    }


def write_ase_neb_parse_artifacts(parsed: dict[str, Any], output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    return [
        _write_json(output_dir / "ase_neb_summary.json", parsed["summary"]),
        _write_json(output_dir / "reaction_path.json", parsed["reaction_path"]),
    ]


class AseNebBackend(Backend):
    name = "ase_neb"

    def prepare(self, task: BackendTask) -> PreparedTask:
        return prepare_ase_neb(task)


def _validate_run_summary(value: Any) -> None:
    if not isinstance(value, dict) or set(value) != _RUN_REQUIRED_FIELDS:
        raise ValueError("ASE NEB summary fields do not match ase.neb/1")
    if (
        value.get("schema_version") != "ase-neb-run/1"
        or value.get("backend") != "ase_neb"
        or value.get("task_type") != "neb"
        or value.get("execution_completed") is not True
    ):
        raise ValueError("ASE NEB summary identity or completion marker is invalid")
    if (
        value.get("calculator") != "xtb_cli"
        or value.get("optimizer") != "FIRE"
        or value.get("method") not in {"gfn1", "gfn2"}
        or value.get("interpolation") not in {"linear", "idpp"}
    ):
        raise ValueError("ASE NEB summary execution method is outside ase.neb/1")
    for field in ("ase_version", "calculator", "method", "optimizer", "interpolation"):
        if not isinstance(value.get(field), str) or not value[field]:
            raise ValueError(f"ASE NEB summary field {field} must be a non-empty string")
    if value.get("calculator_version") is not None and not isinstance(value["calculator_version"], str):
        raise ValueError("ASE NEB calculator_version must be a string or null")
    for field in ("climb", "remove_rotation_and_translation", "converged"):
        if not isinstance(value.get(field), bool):
            raise ValueError(f"ASE NEB summary field {field} must be boolean")
    for field in ("charge", "uhf", "max_steps", "steps", "atom_count", "image_count", "highest_energy_image_index"):
        if isinstance(value.get(field), bool) or not isinstance(value.get(field), int):
            raise ValueError(f"ASE NEB summary field {field} must be an integer")
    if value["atom_count"] < 1 or not 3 <= value["image_count"] <= 32:
        raise ValueError("ASE NEB summary atom_count or image_count is invalid")
    if not 1 <= value["max_steps"] <= 100_000 or not 0 <= value["steps"] <= value["max_steps"]:
        raise ValueError("ASE NEB summary step count is invalid")
    if not -100 <= value["charge"] <= 100 or not 0 <= value["uhf"] <= 100:
        raise ValueError("ASE NEB summary charge or uhf is outside ase.neb/1")
    if not 0 <= value["highest_energy_image_index"] < value["image_count"]:
        raise ValueError("ASE NEB summary highest-energy image index is invalid")
    for field in (
        "spring_constant_ev_per_angstrom2",
        "fmax_ev_per_angstrom",
        "barrier_forward_ev",
        "barrier_reverse_ev",
        "max_neb_force_ev_per_angstrom",
    ):
        if isinstance(value.get(field), bool) or not isinstance(value.get(field), (int, float)):
            raise ValueError(f"ASE NEB summary field {field} must be numeric")
        if not math.isfinite(float(value[field])):
            raise ValueError(f"ASE NEB summary field {field} must be finite")
    if (
        not 0.0 < value["spring_constant_ev_per_angstrom2"] <= 10.0
        or not 0.0 < value["fmax_ev_per_angstrom"] <= 10.0
        or value["barrier_forward_ev"] < 0.0
        or value["barrier_reverse_ev"] < 0.0
        or value["max_neb_force_ev_per_angstrom"] < 0.0
    ):
        raise ValueError("ASE NEB summary convergence values are outside ase.neb/1")
    for field, maximum, allow_zero in (
        ("accuracy", 100.0, False),
        ("electronic_temperature", 1_000_000.0, True),
    ):
        raw = value[field]
        if raw is not None and (
            isinstance(raw, bool)
            or not isinstance(raw, (int, float))
            or not math.isfinite(float(raw))
            or raw < 0.0
            or (raw == 0.0 and not allow_zero)
            or raw > maximum
        ):
            raise ValueError(f"ASE NEB summary field {field} is outside ase.neb/1")
    if (value["solvent"] is None) != (value["solvent_model"] is None):
        raise ValueError("ASE NEB summary solvent settings are incomplete")
    if value["solvent_model"] is not None and value["solvent_model"] not in {"alpb", "gbsa"}:
        raise ValueError("ASE NEB summary solvent_model is outside ase.neb/1")
    if value["solvent"] is not None and (
        not isinstance(value["solvent"], str) or _SOLVENT.fullmatch(value["solvent"]) is None
    ):
        raise ValueError("ASE NEB summary solvent is outside ase.neb/1")
    energies = value.get("image_energies_ev")
    if not isinstance(energies, list) or len(energies) != value["image_count"]:
        raise ValueError("ASE NEB summary image energies do not match image_count")
    if any(
        isinstance(energy, bool)
        or not isinstance(energy, (int, float))
        or not math.isfinite(float(energy))
        for energy in energies
    ):
        raise ValueError("ASE NEB summary image energies must be finite numbers")
    highest = max(range(len(energies)), key=energies.__getitem__)
    if highest != value["highest_energy_image_index"]:
        raise ValueError("ASE NEB summary highest-energy image is inconsistent")
    if not math.isclose(
        value["barrier_forward_ev"],
        energies[highest] - energies[0],
        rel_tol=0.0,
        abs_tol=1.0e-9,
    ) or not math.isclose(
        value["barrier_reverse_ev"],
        energies[highest] - energies[-1],
        rel_tol=0.0,
        abs_tol=1.0e-9,
    ):
        raise ValueError("ASE NEB summary barriers are inconsistent with image energies")


def _run_settings_match(run: dict[str, Any], expected: dict[str, Any]) -> bool:
    mappings = {
        "images": "image_count",
        "fmax": "fmax_ev_per_angstrom",
        "max_steps": "max_steps",
        "spring_constant": "spring_constant_ev_per_angstrom2",
        "interpolation": "interpolation",
        "climb": "climb",
        "remove_rotation_and_translation": "remove_rotation_and_translation",
        "method": "method",
        "charge": "charge",
        "uhf": "uhf",
        "accuracy": "accuracy",
        "electronic_temperature": "electronic_temperature",
        "solvent_model": "solvent_model",
        "solvent": "solvent",
    }
    for expected_name, run_name in mappings.items():
        expected_value = expected[expected_name]
        actual_value = run[run_name]
        if isinstance(expected_value, float):
            if not isinstance(actual_value, (int, float)) or not math.isclose(
                actual_value,
                expected_value,
                rel_tol=0.0,
                abs_tol=1.0e-12,
            ):
                return False
        elif actual_value != expected_value:
            return False
    return True


def _read_xyz_records(path: Path) -> list[dict[str, Any]]:
    lines = path.read_text(encoding="utf-8", errors="strict").splitlines()
    records: list[dict[str, Any]] = []
    index = 0
    while index < len(lines):
        if not lines[index].strip():
            index += 1
            continue
        try:
            count = int(lines[index].strip())
        except ValueError as exc:
            raise ValueError(f"invalid XYZ atom count at line {index + 1}: {path}") from exc
        if count < 1 or index + count + 1 >= len(lines):
            raise ValueError(f"incomplete XYZ frame at line {index + 1}: {path}")
        title = lines[index + 1].strip()
        energy_match = re.search(rf"(?:^|\s)energy_ev:\s*({_FLOAT})", title, flags=re.IGNORECASE)
        symbols: list[str] = []
        coordinates: list[list[float]] = []
        for line_number, line in enumerate(lines[index + 2 : index + count + 2], start=index + 3):
            fields = line.split()
            if len(fields) < 4 or re.fullmatch(r"[A-Z][a-z]?", fields[0]) is None:
                raise ValueError(f"invalid XYZ atom at line {line_number}: {path}")
            try:
                position = [float(field.replace("D", "E").replace("d", "e")) for field in fields[1:4]]
            except ValueError as exc:
                raise ValueError(f"invalid XYZ coordinate at line {line_number}: {path}") from exc
            if not all(math.isfinite(component) for component in position):
                raise ValueError(f"non-finite XYZ coordinate at line {line_number}: {path}")
            symbols.append(fields[0])
            coordinates.append(position)
        energy = None
        if energy_match:
            energy = float(energy_match.group(1).replace("D", "E").replace("d", "e"))
            if not math.isfinite(energy):
                raise ValueError(f"non-finite XYZ energy: {path}")
        records.append(
            {
                "symbols": symbols,
                "coordinates": coordinates,
                "energy_ev": energy,
            }
        )
        index += count + 2
    if not records:
        raise ValueError(f"XYZ artifact contains no frames: {path}")
    return records


def _coordinates_equivalent(
    first: list[list[float]],
    second: list[list[float]],
    *,
    allow_rigid_transform: bool,
) -> bool:
    if len(first) != len(second):
        return False
    reference = np.asarray(first, dtype=float)
    candidate = np.asarray(second, dtype=float)
    if not allow_rigid_transform:
        return bool(np.max(np.linalg.norm(reference - candidate, axis=1)) <= _POSITION_TOLERANCE_ANGSTROM)
    reference = reference - reference.mean(axis=0)
    candidate = candidate - candidate.mean(axis=0)
    left, _singular_values, right_transpose = np.linalg.svd(candidate.T @ reference)
    correction = np.eye(3)
    correction[-1, -1] = np.sign(np.linalg.det(left @ right_transpose))
    rotation = left @ correction @ right_transpose
    aligned = candidate @ rotation
    return bool(
        np.max(np.linalg.norm(reference - aligned, axis=1)) <= _POSITION_TOLERANCE_ANGSTROM
    )


def _bounded_int(value: str, label: str, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"ASE NEB {label} must be an integer") from exc
    if not minimum <= parsed <= maximum:
        raise ValueError(f"ASE NEB {label} must be between {minimum} and {maximum}")
    return parsed


def _bounded_float(
    value: str,
    label: str,
    minimum: float,
    maximum: float,
    *,
    lower_inclusive: bool = False,
) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ValueError(f"ASE NEB {label} must be numeric") from exc
    lower_ok = parsed >= minimum if lower_inclusive else parsed > minimum
    if not math.isfinite(parsed) or not lower_ok or parsed > maximum:
        comparison = "at least" if lower_inclusive else "greater than"
        raise ValueError(
            f"ASE NEB {label} must be finite, {comparison} {minimum}, and at most {maximum}"
        )
    return parsed


def _boolean(value: str, label: str) -> bool:
    normalized = value.lower()
    if normalized not in {"true", "false"}:
        raise ValueError(f"ASE NEB {label} must be true or false")
    return normalized == "true"


def _format_number(value: float) -> str:
    return format(value, ".15g")


def _write_json(path: Path, value: Any) -> Path:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    return path
