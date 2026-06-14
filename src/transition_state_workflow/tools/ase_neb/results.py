"""ASE NEB result artifacts.

This module owns tool-produced NEB artifacts: path tables, force tables,
trajectory snapshots, candidate geometry metadata, and the summary payload.
It deliberately does not write workspace state such as node records, tree
edges, evidence records, reports, or reflections.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from transition_state_workflow.backends.ase import import_ase_bits
from transition_state_workflow.util.json_io import write_json_object


@dataclass(frozen=True)
class AseNebCandidateArtifact:
    """Metadata for the candidate geometry selected from a NEB path."""

    candidate_id: str
    source_image: int
    xyz: Path
    energy_ev: float
    relative_energy_ev: float

    def to_payload(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "source_image": self.source_image,
            "source": "neb_maximum",
            "candidate_state": "candidate",
            "xyz": str(self.xyz),
            "energy_ev": self.energy_ev,
            "relative_energy_ev": self.relative_energy_ev,
            "note": "Candidate requires Gaussian TS/Freq and connectivity validation.",
        }


@dataclass(frozen=True)
class AseNebPathArtifacts:
    """Structured summary of artifacts produced by one ASE NEB run."""

    run_status: str
    image_count: int
    candidate: AseNebCandidateArtifact
    barrier_ev_relative_to_reactant: float
    reaction_energy_ev: float
    energies_csv: Path
    forces_csv: Path
    candidate_json: Path

    def to_summary_payload(self) -> dict[str, Any]:
        return {
            "run_status": self.run_status,
            "images": self.image_count,
            "candidate_id": self.candidate.candidate_id,
            "ts_candidate_index": self.candidate.source_image,
            "barrier_ev_relative_to_reactant": self.barrier_ev_relative_to_reactant,
            "reaction_energy_ev": self.reaction_energy_ev,
            "energies_csv": str(self.energies_csv),
            "forces_csv": str(self.forces_csv),
            "candidate_json": str(self.candidate_json),
            "ts_candidate_xyz": str(self.candidate.xyz),
            "note": "NEB maximum is a TS candidate, not a validated transition state.",
        }


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


def write_json_artifact(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_object(path, payload)
    return path


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
    candidate = AseNebCandidateArtifact(
        candidate_id=candidate_id,
        source_image=ts_index,
        xyz=candidate_xyz,
        energy_ev=ts_row["energy_ev"],
        relative_energy_ev=ts_row["relative_energy_ev"],
    )
    write_json_artifact(candidate_json, candidate.to_payload())
    artifacts = AseNebPathArtifacts(
        run_status=status,
        image_count=len(images),
        candidate=candidate,
        barrier_ev_relative_to_reactant=ts_row["relative_energy_ev"],
        reaction_energy_ev=rows[-1]["relative_energy_ev"],
        energies_csv=energy_csv,
        forces_csv=forces_csv,
        candidate_json=candidate_json,
    )
    summary = artifacts.to_summary_payload()
    write_json_artifact(node_dir / "summary.json", summary)
    return summary


__all__ = [
    "AseNebCandidateArtifact",
    "AseNebPathArtifacts",
    "force_max",
    "collect_path_data",
    "write_json_artifact",
    "write_forces_table",
    "write_path_summary",
]
