"""Core state writers for ASE NEB validation and Gaussian TS/Freq follow-up."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import shutil
from typing import Any

from transition_state_workflow.base.ase_neb import level_slug_from_gaussian_config
from transition_state_workflow.core.ase_neb_workspace import (
    finalize_node_report_and_tree,
    next_node_id,
    node_record,
    read_tree,
    write_json,
)


@dataclass(frozen=True)
class GaussianRefineNodeLayout:
    """Filesystem layout for a Gaussian TS/Freq validation input node."""

    node_id: str
    node_dir: Path
    inputs_dir: Path
    structures_dir: Path
    outputs_dir: Path
    source_candidate: Path
    gaussian_input: Path
    level: str


def find_project_input(project_root: Path, stem: str) -> Path | None:
    inputs = project_root / "inputs"
    if not inputs.exists():
        return None
    matches = sorted(inputs.glob(f"{stem}*.xyz"))
    return matches[0] if matches else None


def latest_promotable_candidate(project_root: Path) -> tuple[str, str] | None:
    """Infer the latest promotable candidate from node-local candidate metadata."""

    candidates: list[tuple[int, str, str]] = []
    for candidate_json in sorted((project_root / "nodes").glob("*/candidates/*.json")):
        source_node_id = candidate_json.parents[1].name
        try:
            data = json.loads(candidate_json.read_text(encoding="utf-8"))
        except Exception:
            continue
        candidate_id = str(data.get("candidate_id") or candidate_json.stem)
        quality = data.get("candidate_quality") if isinstance(data.get("candidate_quality"), dict) else {}
        candidate_state = str(data.get("candidate_state") or "")
        promotable = bool(quality.get("accepted_for_promotion")) or candidate_state == "candidate"
        if not promotable:
            continue
        match = re.match(r"n(\d{3})_", source_node_id)
        order = int(match.group(1)) if match else -1
        candidates.append((order, source_node_id, candidate_id))
    if not candidates:
        return None
    _, source_node_id, candidate_id = sorted(candidates)[-1]
    return source_node_id, candidate_id


def resolve_candidate(
    project_root: Path,
    *,
    source_node_id: str | None,
    candidate_id: str | None,
) -> tuple[str, str, Path]:
    if source_node_id is None or candidate_id is None:
        inferred = latest_promotable_candidate(project_root)
        if inferred is None:
            raise ValueError("source node and candidate are required; no promotable candidate metadata was found")
        source_node_id, candidate_id = inferred
    assert source_node_id is not None
    assert candidate_id is not None
    candidate_json = project_root / "nodes" / source_node_id / "candidates" / f"{candidate_id}.json"
    if not candidate_json.exists():
        raise ValueError(f"candidate metadata not found: {candidate_json}")
    data = json.loads(candidate_json.read_text(encoding="utf-8"))
    xyz = Path(str(data.get("xyz", "")))
    if not xyz.is_absolute():
        xyz = project_root / xyz
    if not xyz.exists():
        matches = sorted((project_root / "nodes" / source_node_id / "candidates").glob(f"{candidate_id}_*.xyz"))
        if not matches:
            raise ValueError(f"candidate xyz not found for {candidate_id}")
        xyz = matches[0]
    return source_node_id, candidate_id, xyz


def latest_node_with_stage(project_root: Path, stage_prefix: str) -> str | None:
    tree = read_tree(project_root)
    candidates: list[tuple[int, str]] = []
    for node_id, entry in tree.get("nodes", {}).items():
        if not str(entry.get("stage", "")).startswith(stage_prefix):
            continue
        match = re.match(r"n(\d{3})_", node_id)
        candidates.append((int(match.group(1)) if match else -1, node_id))
    if not candidates:
        return None
    return sorted(candidates)[-1][1]


def default_validation_parent(project_root: Path) -> str:
    gaussian_node = latest_node_with_stage(project_root, "gaussian_tsfreq")
    if gaussian_node:
        return gaussian_node
    candidate = latest_promotable_candidate(project_root)
    if candidate:
        return candidate[0]
    raise ValueError("could not infer validation parent node; pass --parent-node")


def prepare_gaussian_refine_node_layout(
    project_root: Path,
    *,
    candidate_id: str,
    candidate_xyz: Path,
    gaussian_cfg: dict[str, Any],
) -> GaussianRefineNodeLayout:
    level = level_slug_from_gaussian_config(gaussian_cfg)
    node_id = next_node_id(project_root, f"gaussian_tsfreq_{level}_from_{candidate_id}")
    node_dir = project_root / "nodes" / node_id
    inputs_dir = node_dir / "inputs"
    structures_dir = node_dir / "structures"
    outputs_dir = node_dir / "outputs"
    for directory in (inputs_dir, structures_dir, outputs_dir):
        directory.mkdir(parents=True, exist_ok=True)

    source_candidate = structures_dir / "source_candidate.xyz"
    shutil.copyfile(candidate_xyz, source_candidate)
    return GaussianRefineNodeLayout(
        node_id=node_id,
        node_dir=node_dir,
        inputs_dir=inputs_dir,
        structures_dir=structures_dir,
        outputs_dir=outputs_dir,
        source_candidate=source_candidate,
        gaussian_input=inputs_dir / "ts_candidate_ts_freq.gjf",
        level=level,
    )


def write_gaussian_refine_node_state(
    project_root: Path,
    layout: GaussianRefineNodeLayout,
    *,
    source_node_id: str,
    candidate_id: str,
    candidate_xyz: Path,
    gaussian_cfg: dict[str, Any],
) -> tuple[str, Path]:
    validation = {
        "is_validated_transition_state": False,
        "normal_termination": None,
        "stationary_point": None,
        "imaginary_frequencies": None,
        "connectivity_confirmed": None,
        "claim": "Gaussian input prepared; no TS validation has been run.",
    }
    node = node_record(
        node_id=layout.node_id,
        parent_id=source_node_id,
        node_type="ts_frequency_validation",
        hypothesis="Gaussian Opt(TS)+Freq validates whether the promoted candidate is a first-order saddle point.",
        changed_variables={
            "gaussian_route": gaussian_cfg.get("route"),
            "charge": gaussian_cfg.get("charge"),
            "multiplicity": gaussian_cfg.get("multiplicity"),
            "output_suffix": ".out",
        },
        status="pending",
        evidence={
            "source_candidate_xyz": str(layout.source_candidate),
            "ts_freq_gjf": str(layout.gaussian_input),
        },
        decision="run_gaussian_tsfreq",
        stage="gaussian_tsfreq_input",
        backend="gaussian",
        level=layout.level,
        source={
            "node_id": source_node_id,
            "candidate_id": candidate_id,
            "candidate_xyz": str(candidate_xyz),
        },
        inputs={
            "ts_freq_gjf": str(layout.gaussian_input),
            "source_candidate_xyz": str(layout.source_candidate),
        },
        outputs={
            "expected_out": str(layout.outputs_dir / "ts_candidate_ts_freq.out"),
            "expected_checkpoint": str(layout.outputs_dir / "ts_candidate.chk"),
        },
        validation=validation,
    )
    write_json(layout.node_dir / "node.json", node)
    write_json(layout.node_dir / "validation.json", validation)
    finalize_node_report_and_tree(
        project_root,
        layout.node_dir,
        layout.node_id,
        node,
        parent=source_node_id,
        stage="gaussian_tsfreq_input",
        status="pending",
        report_body=f"""# Gaussian TS/Freq Input

- Status: pending
- Source node: {source_node_id}
- Candidate: {candidate_id}
- Level: {layout.level}
- Input: `inputs/ts_candidate_ts_freq.gjf`

This node is only prepared input. It becomes a validated TS node only after a
normal-terminated Gaussian frequency result shows a stationary point with
exactly one imaginary frequency and the mode matches the expected reaction
coordinate.
""",
        reflection_decision="run_gaussian_tsfreq",
    )
    return layout.node_id, layout.gaussian_input


def create_validation_plan_node(
    project_root: Path,
    *,
    parent_node_id: str,
    policy: dict[str, Any],
) -> tuple[str, Path]:
    node_id = next_node_id(project_root, "validation_plan_mode_endpoint_irc", start=30)
    node_dir = project_root / "nodes" / node_id
    node_dir.mkdir(parents=True, exist_ok=True)
    write_json(node_dir / "validation_policy.json", policy)
    validation = {
        "tsfreq_validated": None,
        "mode_endpoint_connected": None,
        "irc_connected": None,
        "accepted_ts_ready": False,
        "irc_policy": policy["irc_decision"]["policy"],
        "claim": "Validation policy planned; endpoint/IRC jobs have not been run.",
    }
    write_json(node_dir / "validation.json", validation)
    node = node_record(
        node_id=node_id,
        parent_id=parent_node_id,
        node_type="connectivity_validation",
        hypothesis="Plan imaginary-mode endpoint and IRC connectivity gates for the validated TS candidate.",
        changed_variables={
            "system_class": policy["system_class"],
            "tracked_bonds": policy["reaction_center"]["tracked_bonds"],
            "tracked_angles": policy["reaction_center"]["tracked_angles"],
            "irc_policy": policy["irc_decision"]["policy"],
        },
        status="pending",
        evidence={
            "validation_policy": str(node_dir / "validation_policy.json"),
            "validation": str(node_dir / "validation.json"),
        },
        decision="run_mode_endpoint_validation",
        stage="validation_plan",
        backend="policy",
        inputs={
            "reactant": policy["reactant"],
            "product": policy["product"],
        },
        validation=validation,
        policy_file=str(node_dir / "validation_policy.json"),
    )
    write_json(node_dir / "node.json", node)
    tracked = policy["reaction_center"]["tracked_bonds"]
    angles = policy["reaction_center"]["tracked_angles"]
    ladders = ", ".join(str(value) for value in policy["imaginary_mode_follow"]["displacement_ladder_max_atom_a"])
    thresholds = policy["connectivity_metrics"]["thresholds"]
    finalize_node_report_and_tree(
        project_root,
        node_dir,
        node_id,
        node,
        parent=parent_node_id,
        stage="validation_plan",
        status="pending",
        report_body=f"""# Validation Plan

- Status: pending
- Parent node: {parent_node_id}
- System class: {policy['system_class']}
- Tracked bonds: {', '.join(tracked) if tracked else 'none inferred'}
- Tracked angles: {', '.join(angles) if angles else 'none inferred'}
- Imaginary-mode displacement ladder: {ladders} Angstrom max atom displacement
- IRC policy: {policy['irc_decision']['policy']}
- IRC reasons: {'; '.join(policy['irc_decision']['reasons'])}

## Primary Gates

- Reaction-center RMSD: pass <= {thresholds['reaction_center_rmsd_a']['pass']} A; borderline <= {thresholds['reaction_center_rmsd_a']['borderline']} A
- Key bond delta: pass <= {thresholds['key_bond_a']['pass']} A; borderline <= {thresholds['key_bond_a']['borderline']} A
- Key angle delta: pass <= {thresholds['angle_deg']['pass']} deg; borderline <= {thresholds['angle_deg']['borderline']} deg

The final TS claim should remain false until frequency validation and
connectivity evidence are written back to this node or a child validation node.
""",
        reflection_decision="run_mode_endpoint_validation",
    )
    return node_id, node_dir / "validation_policy.json"


__all__ = [
    "GaussianRefineNodeLayout",
    "find_project_input",
    "latest_promotable_candidate",
    "resolve_candidate",
    "latest_node_with_stage",
    "default_validation_parent",
    "prepare_gaussian_refine_node_layout",
    "write_gaussian_refine_node_state",
    "create_validation_plan_node",
]
