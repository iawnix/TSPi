"""NEB driver primitives: build the NEB object, run forces, score candidates.

These functions only need ASE images and a candidate-selection cfg. They do not
mutate workspace bookkeeping — the orchestrating ``run_neb`` and continuation
paths call them and then hand the result to the workspace writers.
"""

from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Any

from transition_state_workflow.backends.ase import import_ase_bits
from transition_state_workflow.tools.ase_neb.errors import ConfigError
from transition_state_workflow.tool.ase_neb.gaussian_calc import create_calculator
from transition_state_workflow.tools.ase_neb.mechanism import endpoint_validation_summary
from transition_state_workflow.tools.ase_neb.workspace import write_json


def make_neb_object(cfg: dict[str, Any], images: list[Any]) -> Any:
    bits = import_ase_bits()
    neb_cfg = cfg["neb"]
    kwargs = {
        "climb": bool(neb_cfg.get("climb", False)),
        "k": neb_cfg.get("k", 0.1),
        "method": neb_cfg.get("method", "improvedtangent"),
        "remove_rotation_and_translation": bool(
            neb_cfg.get("remove_rotation_and_translation", False)
        ),
    }
    if neb_cfg.get("dynamic", False):
        dyneb = bits["DyNEB"]
        if dyneb is None:
            raise ConfigError("DyNEB requested but this ASE version does not provide it")
        return dyneb(images, **kwargs)
    return bits["NEB"](images, **kwargs)


def attach_calculators(cfg: dict[str, Any], images: list[Any], output: Path) -> None:
    calc_cfg = cfg["calculator"]
    calc_root = output / "calculators"
    for index, image in enumerate(images):
        image.calc = create_calculator(calc_cfg, index, calc_root)


def force_max(forces: Any) -> float:
    if forces is None:
        return math.nan
    max_force = 0.0
    for vector in forces:
        value = math.sqrt(sum(float(component) ** 2 for component in vector))
        max_force = max(max_force, value)
    return max_force


def collect_path_data(images: list[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, image in enumerate(images):
        energy = float(image.get_potential_energy())
        try:
            fmax = force_max(image.get_forces())
        except Exception:
            fmax = math.nan
        rows.append({"image": index, "energy_ev": energy, "fmax_ev_a": fmax})
    e0 = rows[0]["energy_ev"]
    for row in rows:
        row["relative_energy_ev"] = row["energy_ev"] - e0
    return rows


def write_forces_table(node_dir: Path, images: list[Any]) -> Path:
    path = node_dir / "tables" / "forces.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["image", "atom_index", "symbol", "fx_ev_a", "fy_ev_a", "fz_ev_a"],
        )
        writer.writeheader()
        for image_index, image in enumerate(images):
            symbols = image.get_chemical_symbols()
            try:
                forces = image.get_forces()
            except Exception:
                forces = []
            for atom_index, vector in enumerate(forces):
                writer.writerow(
                    {
                        "image": image_index,
                        "atom_index": atom_index,
                        "symbol": symbols[atom_index],
                        "fx_ev_a": float(vector[0]),
                        "fy_ev_a": float(vector[1]),
                        "fz_ev_a": float(vector[2]),
                    }
                )
    return path


def write_path_summary(node_dir: Path, images: list[Any], *, status: str) -> dict[str, Any]:
    bits = import_ase_bits()
    write = bits["write"]
    rows = collect_path_data(images)
    tables_dir = node_dir / "tables"
    candidates_dir = node_dir / "candidates"
    trajectories_dir = node_dir / "trajectories"
    tables_dir.mkdir(parents=True, exist_ok=True)
    candidates_dir.mkdir(parents=True, exist_ok=True)
    trajectories_dir.mkdir(parents=True, exist_ok=True)
    energy_csv = tables_dir / "energies.csv"
    with energy_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["image", "energy_ev", "relative_energy_ev", "fmax_ev_a"],
        )
        writer.writeheader()
        writer.writerows(rows)

    ts_row = max(rows, key=lambda row: row["relative_energy_ev"])
    ts_index = int(ts_row["image"])
    candidate_id = "cand_001"
    candidate_xyz = candidates_dir / f"{candidate_id}_img{ts_index:02d}.xyz"
    candidate_json = candidates_dir / f"{candidate_id}.json"
    write(trajectories_dir / "final_path.xyz", images)
    write(candidate_xyz, images[ts_index])
    forces_csv = write_forces_table(node_dir, images)
    candidate_data = {
        "candidate_id": candidate_id,
        "source_image": ts_index,
        "source": "neb_maximum",
        "candidate_state": "candidate",
        "xyz": str(candidate_xyz),
        "energy_ev": ts_row["energy_ev"],
        "relative_energy_ev": ts_row["relative_energy_ev"],
        "note": "Candidate requires Gaussian TS/Freq and connectivity validation.",
    }
    write_json(candidate_json, candidate_data)
    summary = {
        "run_status": status,
        "images": len(images),
        "candidate_id": candidate_id,
        "ts_candidate_index": ts_index,
        "barrier_ev_relative_to_reactant": ts_row["relative_energy_ev"],
        "reaction_energy_ev": rows[-1]["relative_energy_ev"],
        "energies_csv": str(energy_csv),
        "forces_csv": str(forces_csv),
        "candidate_json": str(candidate_json),
        "ts_candidate_xyz": str(candidate_xyz),
        "note": "NEB maximum is a TS candidate, not a validated transition state.",
    }
    write_json(node_dir / "summary.json", summary)
    return summary


def evaluate_neb_candidate_quality(
    summary: dict[str, Any],
    cfg: dict[str, Any],
    *,
    optimizer_converged: bool,
) -> dict[str, Any]:
    candidate_selection = cfg.get("candidate_selection", {})
    min_barrier = float(candidate_selection.get("min_barrier_ev", 0.03))
    allow_endpoint = bool(candidate_selection.get("allow_endpoint_candidate", False))
    image_count = int(summary["images"])
    ts_index = int(summary["ts_candidate_index"])
    barrier = float(summary["barrier_ev_relative_to_reactant"])
    reasons: list[str] = []
    # Collected in priority order: a prerequisite or numerical failure invalidates
    # the path before any chemical interpretation of its barrier/endpoint geometry,
    # so the primary outcome_code is the highest-priority code present rather than
    # whichever check happened to run last.
    failure_codes: list[str] = []
    endpoint_validation = endpoint_validation_summary(cfg)
    if not endpoint_validation["endpoint_minima_ready"]:
        reasons.append(
            "reactant/product endpoints are not declared as validated_minimum, lower_level_minimum, or constrained_reference"
        )
        failure_codes.append("endpoint_minima_missing")
    if not optimizer_converged:
        reasons.append("NEB optimizer did not report convergence within the configured step limit")
        failure_codes.append("neb_not_converged")
    if ts_index in {0, image_count - 1} and not allow_endpoint:
        reasons.append("maximum-energy image is an endpoint")
        failure_codes.append("neb_endpoint_candidate")
    if barrier < min_barrier:
        reasons.append(f"barrier {barrier:.6f} eV is below min_barrier_ev {min_barrier:.6f}")
        failure_codes.append("neb_no_barrier")
    accepted = not reasons
    failure_type = failure_codes[0] if failure_codes else None
    return {
        "accepted_for_promotion": accepted,
        "outcome_code": failure_type,
        "failure_codes": failure_codes,
        "reasons": reasons or ["internal non-endpoint maximum passed candidate gates"],
        "gates": {
            "optimizer_converged": optimizer_converged,
            "ts_candidate_not_endpoint": ts_index not in {0, image_count - 1} or allow_endpoint,
            "barrier_at_least_minimum": barrier >= min_barrier,
            "min_barrier_ev": min_barrier,
            "allow_endpoint_candidate": allow_endpoint,
            "endpoint_minima_ready": endpoint_validation["endpoint_minima_ready"],
            "endpoint_states": {
                "reactant": endpoint_validation["reactant_state"],
                "product": endpoint_validation["product_state"],
            },
        },
    }


__all__ = [
    "make_neb_object",
    "attach_calculators",
    "force_max",
    "collect_path_data",
    "write_forces_table",
    "write_path_summary",
    "evaluate_neb_candidate_quality",
]
