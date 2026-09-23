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
_HISTORY_RECORD_LIMIT = 256
_NEB_METHODS = frozenset({"aseneb", "improvedtangent", "eb", "spline", "string"})
_OPTIMIZERS = frozenset({"FIRE", "BFGS", "LBFGS", "MDMin"})
_SETTINGS_FIELDS = frozenset(
    {
        "images",
        "fmax",
        "max_steps",
        "spring_constant",
        "interpolation",
        "neb_method",
        "optimizer",
        "climb",
        "ci_neb",
        "ci_fmax",
        "remove_rotation_and_translation",
        "method",
        "charge",
        "uhf",
        "accuracy",
        "electronic_temperature",
        "solvent_model",
        "solvent",
    }
)
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
_RUN_OPTIONAL_FIELDS = frozenset(
    {
        "ci_neb",
        "ci_fmax_ev_per_angstrom",
        "neb_method",
        "settings",
        "stages",
        "history",
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
        "--neb-method",
        settings["neb_method"],
        "--optimizer",
        settings["optimizer"],
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
    # These flags are explicit in the prepared command so remote execution
    # cannot silently fall back to a runner default.  They are inserted before
    # the legacy optional xTB flags to keep the old command suffix stable.
    command.extend(["--ci-neb", str(settings["ci_neb"]).lower()])
    if settings["ci_fmax"] is not None:
        command.extend(["--ci-fmax", _format_number(settings["ci_fmax"])])
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
        "neb_method",
        "optimizer",
        "remove_rotation_and_translation",
        "ci_neb",
        "ci_fmax",
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
    neb_method = settings.get("neb_method", "aseneb").lower()
    if neb_method not in _NEB_METHODS:
        raise ValueError(f"unsupported ASE NEB path method: {neb_method}")
    optimizer = settings.get("optimizer", "FIRE").strip().lower()
    optimizer_names = {
        "fire": "FIRE",
        "bfgs": "BFGS",
        "lbfgs": "LBFGS",
        "mdmin": "MDMin",
    }
    if optimizer not in optimizer_names:
        raise ValueError(f"unsupported ASE NEB optimizer: {settings.get('optimizer')}")
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
    fmax = _bounded_float(settings.get("fmax", "0.05"), "fmax", 0.0, 10.0)
    climb = _boolean(settings.get("climb", "false"), "climb")
    ci_neb = _boolean(settings.get("ci_neb", "false"), "ci_neb")
    if ci_neb and climb:
        raise ValueError("ASE NEB climb and ci_neb are mutually exclusive; use ci_neb for two-stage CI-NEB")
    ci_fmax = (
        _bounded_float(settings["ci_fmax"], "ci_fmax", 0.0, 10.0)
        if "ci_fmax" in settings
        else None
    )
    if ci_fmax is not None and not ci_neb:
        raise ValueError("ASE NEB ci_fmax requires ci_neb=true")
    if ci_neb and ci_fmax is None:
        ci_fmax = fmax
    return {
        "images": _bounded_int(settings.get("images", "7"), "images", 3, 32),
        "fmax": fmax,
        "max_steps": _bounded_int(settings.get("max_steps", "500"), "max_steps", 1, 100_000),
        "spring_constant": _bounded_float(
            settings.get("spring_constant", "0.1"),
            "spring_constant",
            0.0,
            10.0,
        ),
        "interpolation": interpolation,
        "neb_method": neb_method,
        "optimizer": optimizer_names[optimizer],
        "climb": climb,
        "ci_neb": ci_neb,
        "ci_fmax": ci_fmax,
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
    effective_fmax = run["fmax_ev_per_angstrom"]
    run_stages = run.get("stages")
    if isinstance(run_stages, list) and run_stages:
        effective_fmax = run_stages[-1]["fmax_ev_per_angstrom"]
    force_threshold_satisfied = bool(
        run["max_neb_force_ev_per_angstrom"] <= effective_fmax + 1.0e-12
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
    history = run.get("history")
    if isinstance(history, dict):
        records = history.get("records")
        stages = [record.get("stage") for record in records] if isinstance(records, list) else []
        summary.update(
            {
                "history_present": True,
                "history_complete": True,
                "history_record_count": len(records) if isinstance(records, list) else 0,
                "history_stages": list(dict.fromkeys(stages)),
            }
        )
    else:
        summary.update(
            {
                "history_present": False,
                "history_complete": None,
                "history_record_count": 0,
                "history_stages": [],
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
    if not isinstance(value, dict) or not _RUN_REQUIRED_FIELDS <= set(value):
        raise ValueError("ASE NEB summary fields do not match ase.neb/1")
    if set(value) - _RUN_REQUIRED_FIELDS - _RUN_OPTIONAL_FIELDS:
        raise ValueError("ASE NEB summary fields do not match ase.neb/1")
    if (
        value.get("schema_version") != "ase-neb-run/1"
        or value.get("backend") != "ase_neb"
        or value.get("task_type") != "neb"
        or value.get("execution_completed") is not True
    ):
        raise ValueError("ASE NEB summary identity or completion marker is invalid")
    optimizer = value.get("optimizer")
    neb_method = value.get("neb_method", "aseneb")
    if (
        value.get("calculator") != "xtb_cli"
        or not isinstance(optimizer, str)
        or optimizer not in _OPTIMIZERS
        or value.get("method") not in {"gfn1", "gfn2"}
        or value.get("interpolation") not in {"linear", "idpp"}
    ):
        raise ValueError("ASE NEB summary execution method is outside ase.neb/1")
    if not isinstance(neb_method, str) or neb_method not in _NEB_METHODS:
        raise ValueError("ASE NEB summary path method is outside ase.neb/1")
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

    _validate_optional_run_fields(value)
    _validate_settings_echo(value)


def _validate_settings_echo(value: dict[str, Any]) -> None:
    """Cross-check the effective settings object when a new runner emits it."""

    if "settings" not in value:
        return
    settings = value["settings"]
    if not isinstance(settings, dict) or set(settings) != _SETTINGS_FIELDS:
        raise ValueError("ASE NEB summary settings fields are invalid")
    expected = {
        "images": value["image_count"],
        "fmax": value["fmax_ev_per_angstrom"],
        "max_steps": value["max_steps"],
        "spring_constant": value["spring_constant_ev_per_angstrom2"],
        "interpolation": value["interpolation"],
        "neb_method": value.get("neb_method", "aseneb"),
        "optimizer": value["optimizer"],
        "climb": value["climb"],
        "ci_neb": value.get("ci_neb", False),
        "ci_fmax": (
            value.get("ci_fmax_ev_per_angstrom", value["fmax_ev_per_angstrom"])
            if value.get("ci_neb", False)
            else value.get("ci_fmax_ev_per_angstrom")
        ),
        "remove_rotation_and_translation": value["remove_rotation_and_translation"],
        "method": value["method"],
        "charge": value["charge"],
        "uhf": value["uhf"],
        "accuracy": value["accuracy"],
        "electronic_temperature": value["electronic_temperature"],
        "solvent_model": value["solvent_model"],
        "solvent": value["solvent"],
    }
    for key, expected_value in expected.items():
        actual_value = settings[key]
        if isinstance(expected_value, float):
            if not isinstance(actual_value, (int, float)) or not math.isclose(
                actual_value, expected_value, rel_tol=0.0, abs_tol=1.0e-12
            ):
                raise ValueError(f"ASE NEB summary settings {key} disagree with run fields")
        elif actual_value != expected_value:
            raise ValueError(f"ASE NEB summary settings {key} disagree with run fields")


def _validate_optional_run_fields(value: dict[str, Any]) -> None:
    """Validate additive two-stage/history fields while accepting old runs."""

    if "ci_neb" in value and not isinstance(value["ci_neb"], bool):
        raise ValueError("ASE NEB summary ci_neb must be boolean")
    if value.get("ci_neb") is True and value["climb"] is True:
        raise ValueError("ASE NEB summary climb and ci_neb are mutually exclusive")
    if "stages" in value and value["stages"] is None:
        raise ValueError("ASE NEB summary stages cannot be null")
    if "history" in value and value["history"] is None:
        raise ValueError("ASE NEB summary history cannot be null")
    ci_neb = value.get("ci_neb", False)
    if "ci_fmax_ev_per_angstrom" in value:
        ci_fmax = value["ci_fmax_ev_per_angstrom"]
        if ci_fmax is None:
            if ci_neb:
                raise ValueError("ASE NEB summary CI-NEB requires ci_fmax")
        elif (
            isinstance(ci_fmax, bool)
            or not isinstance(ci_fmax, (int, float))
            or not math.isfinite(float(ci_fmax))
            or not 0.0 < float(ci_fmax) <= 10.0
        ):
            raise ValueError("ASE NEB summary ci_fmax is outside ase.neb/1")
        elif not ci_neb:
            raise ValueError("ASE NEB summary ci_fmax requires ci_neb")

    stages = value.get("stages")
    if stages is not None:
        if not isinstance(stages, list) or not 1 <= len(stages) <= 2:
            raise ValueError("ASE NEB summary stages are invalid")
        expected_names = ["neb", "ci_neb"]
        names: list[str] = []
        for stage in stages:
            if not isinstance(stage, dict):
                raise ValueError("ASE NEB summary stage is not an object")
            if set(stage) != {
                "stage",
                "climb",
                "fmax_ev_per_angstrom",
                "max_steps",
                "steps",
                "converged",
                "image_energies_ev",
                "max_neb_force_ev_per_angstrom",
            }:
                raise ValueError("ASE NEB summary stage fields are invalid")
            name = stage["stage"]
            if name not in expected_names or name in names:
                raise ValueError("ASE NEB summary stage order is invalid")
            names.append(name)
            if not isinstance(stage["climb"], bool) or not isinstance(stage["converged"], bool):
                raise ValueError("ASE NEB summary stage boolean is invalid")
            if name == "neb" and stage["climb"] != value["climb"]:
                raise ValueError("ASE NEB summary ordinary NEB climb disagrees with settings")
            if name == "ci_neb" and stage["climb"] is not True:
                raise ValueError("ASE NEB summary CI-NEB stage is not climbing")
            if (
                isinstance(stage["max_steps"], bool)
                or not isinstance(stage["max_steps"], int)
                or not 1 <= stage["max_steps"] <= 100_000
                or isinstance(stage["steps"], bool)
                or not isinstance(stage["steps"], int)
                or not 0 <= stage["steps"] <= stage["max_steps"]
            ):
                raise ValueError("ASE NEB summary stage step count is invalid")
            fmax = stage["fmax_ev_per_angstrom"]
            force = stage["max_neb_force_ev_per_angstrom"]
            if (
                isinstance(fmax, bool)
                or not isinstance(fmax, (int, float))
                or not math.isfinite(float(fmax))
                or not 0.0 < float(fmax) <= 10.0
                or isinstance(force, bool)
                or not isinstance(force, (int, float))
                or not math.isfinite(float(force))
                or float(force) < 0.0
            ):
                raise ValueError("ASE NEB summary stage convergence value is invalid")
            expected_fmax = (
                value["fmax_ev_per_angstrom"]
                if name == "neb"
                else (
                    value.get("ci_fmax_ev_per_angstrom")
                    or value["fmax_ev_per_angstrom"]
                )
            )
            if not math.isclose(fmax, expected_fmax, rel_tol=0.0, abs_tol=1.0e-12):
                raise ValueError("ASE NEB summary stage fmax disagrees with settings")
            if stage["max_steps"] != value["max_steps"]:
                raise ValueError("ASE NEB summary stage max_steps disagrees with settings")
            if stage["converged"] and force > fmax + 1.0e-12:
                raise ValueError("ASE NEB summary stage convergence exceeds fmax")
            energies = stage["image_energies_ev"]
            if (
                not isinstance(energies, list)
                or len(energies) != value["image_count"]
                or any(
                    isinstance(energy, bool)
                    or not isinstance(energy, (int, float))
                    or not math.isfinite(float(energy))
                    for energy in energies
                )
            ):
                raise ValueError("ASE NEB summary stage energies are invalid")
        if names != expected_names[: len(names)]:
            raise ValueError("ASE NEB summary stage order is invalid")
        ci_neb = value.get("ci_neb")
        if ci_neb is True:
            if value["stages"][0]["climb"]:
                raise ValueError("ASE NEB summary ordinary NEB stage cannot climb")
            if names == ["neb"] and value["stages"][0]["converged"]:
                raise ValueError("ASE NEB summary CI-NEB stage is missing")
            if names == expected_names and not value["stages"][0]["converged"]:
                raise ValueError("ASE NEB summary CI-NEB stage ran before NEB converged")
            if names == expected_names and not value["stages"][1]["climb"]:
                raise ValueError("ASE NEB summary CI-NEB stage is not climbing")
        elif names != ["neb"]:
            raise ValueError("ASE NEB summary CI-NEB stage is not enabled")

        final_stage = stages[-1]
        if value["converged"] != final_stage["converged"]:
            raise ValueError("ASE NEB summary convergence disagrees with final stage")
        if value["steps"] != final_stage["steps"]:
            raise ValueError("ASE NEB summary steps disagree with final stage")
        if not math.isclose(
            value["max_neb_force_ev_per_angstrom"],
            final_stage["max_neb_force_ev_per_angstrom"],
            rel_tol=0.0,
            abs_tol=_ENERGY_TOLERANCE_EV,
        ):
            raise ValueError("ASE NEB summary force disagrees with final stage")
        if len(value["image_energies_ev"]) != len(final_stage["image_energies_ev"]) or any(
            not math.isclose(observed, expected, rel_tol=0.0, abs_tol=_ENERGY_TOLERANCE_EV)
            for observed, expected in zip(
                value["image_energies_ev"], final_stage["image_energies_ev"]
            )
        ):
            raise ValueError("ASE NEB summary energies disagree with final stage")
    elif value.get("ci_neb") is True:
        raise ValueError("ASE NEB summary CI-NEB run is missing stages")

    history = value.get("history")
    if history is not None:
        if not isinstance(history, dict) or set(history) != {
            "schema_version",
            "image_count",
            "records",
        }:
            raise ValueError("ASE NEB summary history fields are invalid")
        if history["schema_version"] != "ase-neb-history/1" or history["image_count"] != value["image_count"]:
            raise ValueError("ASE NEB summary history identity is invalid")
        records = history["records"]
        if not isinstance(records, list) or not records:
            raise ValueError("ASE NEB summary history must contain records")
        if len(records) > _HISTORY_RECORD_LIMIT:
            raise ValueError("ASE NEB summary history is too large")
        previous_stage = None
        previous_step = -1
        history_stages: list[str] = []
        for record in records:
            if not isinstance(record, dict) or set(record) != {
                "stage",
                "step",
                "max_neb_force_ev_per_angstrom",
                "image_energies_ev",
            }:
                raise ValueError("ASE NEB summary history record is invalid")
            stage = record["stage"]
            if stage not in {"neb", "ci_neb"}:
                raise ValueError("ASE NEB summary history stage is invalid")
            if previous_stage is None:
                if stage != "neb":
                    raise ValueError("ASE NEB summary history must start with NEB")
                history_stages.append(stage)
            if previous_stage is not None and stage != previous_stage:
                if previous_stage == "ci_neb" or stage != "ci_neb":
                    raise ValueError("ASE NEB summary history stage order is invalid")
                previous_step = -1
                history_stages.append(stage)
            if (
                isinstance(record["step"], bool)
                or not isinstance(record["step"], int)
                or record["step"] < 0
                or record["step"] < previous_step
            ):
                raise ValueError("ASE NEB summary history step is invalid")
            force = record["max_neb_force_ev_per_angstrom"]
            if (
                isinstance(force, bool)
                or not isinstance(force, (int, float))
                or not math.isfinite(float(force))
                or float(force) < 0.0
            ):
                raise ValueError("ASE NEB summary history force is invalid")
            energies = record["image_energies_ev"]
            if (
                not isinstance(energies, list)
                or len(energies) != value["image_count"]
                or any(
                    isinstance(energy, bool)
                    or not isinstance(energy, (int, float))
                    or not math.isfinite(float(energy))
                    for energy in energies
                )
            ):
                raise ValueError("ASE NEB summary history energies are invalid")
            previous_stage = stage
            previous_step = record["step"]
        if stages is not None and history_stages != [stage["stage"] for stage in stages]:
            raise ValueError("ASE NEB summary history stages disagree with stages")
        if stages is not None:
            for stage_summary in stages:
                stage_records = [
                    record for record in records if record["stage"] == stage_summary["stage"]
                ]
                if not stage_records:
                    raise ValueError("ASE NEB summary history is missing a stage")
                final_record = stage_records[-1]
                if final_record["step"] != stage_summary["steps"]:
                    raise ValueError("ASE NEB summary history steps disagree with stage")
                if not math.isclose(
                    final_record["max_neb_force_ev_per_angstrom"],
                    stage_summary["max_neb_force_ev_per_angstrom"],
                    rel_tol=0.0,
                    abs_tol=_ENERGY_TOLERANCE_EV,
                ) or any(
                    not math.isclose(observed, expected, rel_tol=0.0, abs_tol=_ENERGY_TOLERANCE_EV)
                    for observed, expected in zip(
                        final_record["image_energies_ev"], stage_summary["image_energies_ev"]
                    )
                ):
                    raise ValueError("ASE NEB summary history does not match stage")
        elif history_stages:
            if "ci_neb" in history_stages and value.get("ci_neb") is not True:
                raise ValueError("ASE NEB summary history CI-NEB stage is not enabled")
            if history_stages != ["neb"]:
                raise ValueError("ASE NEB summary history stage order is invalid")
            final_record = records[-1]
            if final_record["step"] != value["steps"]:
                raise ValueError("ASE NEB summary history steps disagree with run")
            if not math.isclose(
                final_record["max_neb_force_ev_per_angstrom"],
                value["max_neb_force_ev_per_angstrom"],
                rel_tol=0.0,
                abs_tol=_ENERGY_TOLERANCE_EV,
            ) or any(
                not math.isclose(observed, expected, rel_tol=0.0, abs_tol=_ENERGY_TOLERANCE_EV)
                for observed, expected in zip(
                    final_record["image_energies_ev"], value["image_energies_ev"]
                )
            ):
                raise ValueError("ASE NEB summary history does not match run")


def _run_settings_match(run: dict[str, Any], expected: dict[str, Any]) -> bool:
    mappings = {
        "images": "image_count",
        "fmax": "fmax_ev_per_angstrom",
        "max_steps": "max_steps",
        "spring_constant": "spring_constant_ev_per_angstrom2",
        "interpolation": "interpolation",
        "neb_method": "neb_method",
        "optimizer": "optimizer",
        "climb": "climb",
        "ci_neb": "ci_neb",
        "ci_fmax": "ci_fmax_ev_per_angstrom",
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
        # Runs written before the two-stage extension have no additive fields;
        # infer the legacy defaults so their settings still validate.
        if expected_name == "ci_neb":
            actual_value = run.get(run_name, False)
        elif expected_name == "ci_fmax":
            if run_name in run:
                actual_value = run[run_name]
            elif run.get("ci_neb", False):
                actual_value = run["fmax_ev_per_angstrom"]
            else:
                actual_value = None
        elif expected_name == "neb_method":
            actual_value = run.get(run_name, "aseneb")
        else:
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
