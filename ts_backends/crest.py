"""CREST conformer-search command preparation and deterministic parsing."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .base import Backend, BackendTask, PreparedTask
from .xyz import xyz_frame_metadata


CREST_TASK_TYPES = frozenset({"conformer_search"})
CREST_REQUIRED_ARTIFACTS = frozenset(
    {"crest.out", "crest_best.xyz", "crest_conformers.xyz", "crest.energies"}
)
_SETTINGS = {
    "charge",
    "method",
    "opt_level",
    "search_level",
    "solvent",
    "solvent_model",
    "threads",
    "uhf",
}


def prepare_crest(task: BackendTask) -> PreparedTask:
    if task.task_type not in CREST_TASK_TYPES:
        raise ValueError(f"unsupported CREST task_type: {task.task_type}")
    if set(task.inputs) != {"xyz"}:
        raise ValueError("CREST conformer_search input roles must be exactly ['xyz']")
    unknown = sorted(set(task.settings) - _SETTINGS)
    if unknown:
        raise ValueError(f"unsupported CREST conformer_search settings: {unknown}")

    command = ["crest", task.inputs["xyz"]]
    charge = _integer(task.settings.get("charge", "0"), "charge")
    uhf = _nonnegative_int(task.settings.get("uhf", "0"), "uhf")
    command.extend(["-chrg", str(charge), "-uhf", str(uhf)])
    method = task.settings.get("method", "gfn2").lower()
    if method not in {"gfn0", "gfn1", "gfn2", "gfnff"}:
        raise ValueError(f"unsupported CREST method: {method}")
    command.append("-gfnff" if method == "gfnff" else f"-{method}")
    search_level = task.settings.get("search_level", "normal").lower()
    if search_level not in {"normal", "quick", "squick", "mquick"}:
        raise ValueError(f"unsupported CREST search_level: {search_level}")
    if search_level != "normal":
        command.append(f"-{search_level}")
    opt_level = task.settings.get("opt_level", "vtight").lower()
    if opt_level not in {"vloose", "loose", "normal", "tight", "vtight"}:
        raise ValueError(f"unsupported CREST opt_level: {opt_level}")
    command.extend(["-opt", opt_level])
    if "threads" in task.settings:
        command.extend(["-T", str(_positive_int(task.settings["threads"], "threads"))])
    solvent = task.settings.get("solvent")
    solvent_model = task.settings.get("solvent_model")
    if (solvent is None) != (solvent_model is None):
        raise ValueError("CREST solvent and solvent_model must be provided together")
    if solvent_model is not None:
        model = solvent_model.lower()
        if model not in {"alpb", "gbsa"}:
            raise ValueError(f"unsupported CREST solvent_model: {solvent_model}")
        command.extend(["-alpb" if model == "alpb" else "-g", str(solvent)])
    return PreparedTask(
        backend="crest",
        act_id=task.act_id,
        command=command,
        input_paths=[task.inputs["xyz"]],
        expected_artifacts=sorted(CREST_REQUIRED_ARTIFACTS),
    )


def parse_crest_artifacts(artifacts: dict[str, Path]) -> dict[str, Any]:
    log = artifacts.get("crest.out")
    if log is None:
        raise ValueError("CREST parsing requires crest.out")
    text = log.read_text(encoding="utf-8", errors="replace")
    presence = {
        name: name in artifacts and artifacts[name].is_file()
        for name in sorted(CREST_REQUIRED_ARTIFACTS)
    }
    summary: dict[str, Any] = {
        "backend": "crest",
        "task_type": "conformer_search",
        "program_version": _crest_version(text),
        "execution_completed": "CREST terminated normally." in text,
        "artifact_presence": presence,
        "missing_artifacts": [name for name, present in presence.items() if not present],
    }
    details: dict[str, Any] = {}
    if "crest_conformers.xyz" in artifacts:
        ensemble = xyz_frame_metadata(artifacts["crest_conformers.xyz"])
        energies = [frame.get("energy_hartree") for frame in ensemble["frames"]]
        summary.update(
            {
                "conformer_count": ensemble["frame_count"],
                "atom_count": ensemble["atom_count"],
                "lowest_conformer_energy_hartree": min(
                    (energy for energy in energies if energy is not None),
                    default=None,
                ),
            }
        )
        details["ensemble"] = ensemble
    if "crest_best.xyz" in artifacts:
        best = xyz_frame_metadata(artifacts["crest_best.xyz"])
        summary["best_structure_energy_hartree"] = best["frames"][0].get("energy_hartree")
    if "crest.energies" in artifacts:
        relative = _relative_energies(artifacts["crest.energies"])
        summary.update(
            {
                "relative_energy_count": len(relative),
                "relative_energy_max_kcal_mol": max(
                    (item["relative_energy_kcal_mol"] for item in relative),
                    default=None,
                ),
            }
        )
        details["relative_energies"] = relative
    counts_match = (
        summary.get("conformer_count") is not None
        and summary.get("conformer_count") == summary.get("relative_energy_count")
    )
    summary["ensemble_counts_match"] = counts_match
    summary["artifacts_complete"] = not summary["missing_artifacts"]
    summary["task_completed"] = bool(
        summary["execution_completed"]
        and summary["artifacts_complete"]
        and summary.get("conformer_count")
        and counts_match
    )
    return {"summary": summary, **details}


def write_crest_parse_artifacts(parsed: dict[str, Any], output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    written = [_write_json(output_dir / "crest_summary.json", parsed["summary"])]
    if "relative_energies" in parsed:
        written.append(
            _write_json(
                output_dir / "conformer_energies.json",
                {
                    "schema_version": "crest-conformer-energies/1",
                    "relative_energies": parsed["relative_energies"],
                },
            )
        )
    if "ensemble" in parsed:
        ensemble = parsed["ensemble"]
        written.append(
            _write_json(
                output_dir / "ensemble_summary.json",
                {
                    "schema_version": "crest-ensemble-summary/1",
                    "atom_count": ensemble["atom_count"],
                    "frame_count": ensemble["frame_count"],
                    "frames": ensemble["frames"],
                },
            )
        )
    return written


def _relative_energies(path: Path) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        try:
            index = int(parts[0])
            energy = float(parts[1].replace("D", "E").replace("d", "e"))
        except ValueError:
            continue
        values.append({"conformer_index": index, "relative_energy_kcal_mol": energy})
    if not values:
        raise ValueError(f"CREST energy table contains no conformers: {path}")
    return values


def _crest_version(text: str) -> str | None:
    matches = re.findall(r"\bVersion\s+(\d+\.\d+(?:\.\d+)?)", text)
    return matches[-1] if matches else None


def _write_json(path: Path, value: Any) -> Path:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _integer(value: str, label: str) -> int:
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"CREST {label} must be an integer") from exc


def _nonnegative_int(value: str, label: str) -> int:
    parsed = _integer(value, label)
    if parsed < 0:
        raise ValueError(f"CREST {label} must be nonnegative")
    return parsed


def _positive_int(value: str, label: str) -> int:
    parsed = _integer(value, label)
    if parsed <= 0:
        raise ValueError(f"CREST {label} must be positive")
    return parsed


class CrestBackend(Backend):
    name = "crest"

    def prepare(self, task: BackendTask) -> PreparedTask:
        return prepare_crest(task)
