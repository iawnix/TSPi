"""Validation policy: displacement, thresholds, IRC, Gaussian refinement nodes.

Reads a candidate path/structure and emits a validation policy (displacement
ladder, threshold gates, IRC requirement, tracked bonds/angles), then writes
the Gaussian TS/Freq input node and the validation-plan node for downstream
mode-endpoint and IRC follow-up.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from transition_state_workflow.gate.neb_candidate import (
    build_validation_policy as _build_validation_policy,
    displacement_ladder,
    irc_policy,
    threshold_policy,
)
from transition_state_workflow.tools.ase_neb.config import (
    ProjectContext,
    level_slug_from_gaussian_config,
)
from transition_state_workflow.tools.ase_neb.errors import ConfigError
from transition_state_workflow.tools.ase_neb.geometry import read_xyz
from transition_state_workflow.core.ase_neb_workspace import (
    next_node_id,
    node_record,
    read_tree,
    update_tree_node_metadata,
    upsert_tree_node,
    write_json,
    write_markdown,
    write_reflection_template,
)


def find_project_input(project_root: Path, stem: str) -> Path | None:
    inputs = project_root / "inputs"
    if not inputs.exists():
        return None
    matches = sorted(inputs.glob(f"{stem}*.xyz"))
    return matches[0] if matches else None


def build_validation_policy(
    reactant_path: Path,
    product_path: Path,
    *,
    user_bonds: list[tuple[int, int]] | None = None,
    user_angles: list[tuple[int, int, int]] | None = None,
    system_class_override: str = "auto",
    imaginary_frequency: float | None = None,
    publication_grade: bool = False,
    force_irc: bool = False,
    risk_flags: list[str] | None = None,
) -> dict[str, Any]:
    try:
        return _build_validation_policy(
            reactant_path,
            product_path,
            user_bonds=user_bonds,
            user_angles=user_angles,
            system_class_override=system_class_override,
            imaginary_frequency=imaginary_frequency,
            publication_grade=publication_grade,
            force_irc=force_irc,
            risk_flags=risk_flags,
        )
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc


def gaussian_refinement_defaults() -> dict[str, Any]:
    return {
        "route": "# M062X/def2SVP opt=(ts,calcfc,noeigen,maxcycle=100) freq nosymm scf=xqc",
        "charge": 0,
        "multiplicity": 1,
        "nprocshared": None,
        "mem": None,
        "chk": "ts_candidate.chk",
        "title": "TS candidate from ASE NEB",
        "extra_sections": [],
    }


def write_gaussian_input(
    xyz_path: Path,
    output_path: Path,
    gaussian_cfg: dict[str, Any],
) -> Path:
    atoms, comment = read_xyz(xyz_path)
    params = gaussian_refinement_defaults()
    params.update(gaussian_cfg)
    lines: list[str] = []
    if params.get("chk"):
        lines.append(f"%chk={params['chk']}")
    if params.get("nprocshared"):
        lines.append(f"%nprocshared={params['nprocshared']}")
    if params.get("mem"):
        lines.append(f"%mem={params['mem']}")
    lines.append(str(params["route"]))
    lines.append("")
    title = str(params.get("title") or comment or "TS candidate from ASE NEB")
    lines.append(title)
    lines.append("")
    lines.append(f"{int(params['charge'])} {int(params['multiplicity'])}")
    for atom in atoms:
        lines.append(
            f"{atom.element:<3s} {atom.x:16.8f} {atom.y:16.8f} {atom.z:16.8f}"
        )
    lines.append("")
    extra_sections = params.get("extra_sections") or []
    if isinstance(extra_sections, str):
        lines.extend(extra_sections.splitlines())
    else:
        for section in extra_sections:
            lines.extend(str(section).splitlines())
            lines.append("")
    while lines and not lines[-1].strip():
        lines.pop()
    lines.extend(["", "", ""])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path


def create_gaussian_refine_node(
    project_root: Path,
    *,
    source_node_id: str,
    candidate_id: str,
    candidate_xyz: Path,
    gaussian_cfg: dict[str, Any],
) -> tuple[str, Path]:
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
    gjf = write_gaussian_input(
        source_candidate,
        inputs_dir / "ts_candidate_ts_freq.gjf",
        gaussian_cfg,
    )
    validation = {
        "is_validated_transition_state": False,
        "normal_termination": None,
        "stationary_point": None,
        "imaginary_frequencies": None,
        "connectivity_confirmed": None,
        "claim": "Gaussian input prepared; no TS validation has been run.",
    }
    node = node_record(
        node_id=node_id,
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
            "source_candidate_xyz": str(source_candidate),
            "ts_freq_gjf": str(gjf),
        },
        decision="run_gaussian_tsfreq",
        stage="gaussian_tsfreq_input",
        backend="gaussian",
        level=level,
        source={
            "node_id": source_node_id,
            "candidate_id": candidate_id,
            "candidate_xyz": str(candidate_xyz),
        },
        inputs={
            "ts_freq_gjf": str(gjf),
            "source_candidate_xyz": str(source_candidate),
        },
        outputs={
            "expected_out": str(outputs_dir / "ts_candidate_ts_freq.out"),
            "expected_checkpoint": str(outputs_dir / "ts_candidate.chk"),
        },
        validation=validation,
    )
    write_json(node_dir / "node.json", node)
    write_json(node_dir / "validation.json", validation)
    write_markdown(
        node_dir / "report.md",
        f"""# Gaussian TS/Freq Input

- Status: pending
- Source node: {source_node_id}
- Candidate: {candidate_id}
- Level: {level}
- Input: `inputs/ts_candidate_ts_freq.gjf`

This node is only prepared input. It becomes a validated TS node only after a
normal-terminated Gaussian frequency result shows a stationary point with
exactly one imaginary frequency and the mode matches the expected reaction
coordinate.
""",
    )
    write_reflection_template(node_dir, decision="run_gaussian_tsfreq")
    upsert_tree_node(
        project_root,
        node_id,
        parent=source_node_id,
        stage="gaussian_tsfreq_input",
        status="pending",
    )
    update_tree_node_metadata(project_root, node_id, node)
    return node_id, gjf


def maybe_write_refinement_input(
    cfg: dict[str, Any],
    ctx: ProjectContext,
    summary: dict[str, Any],
) -> Path | None:
    gaussian_cfg = cfg.get("refinement", {}).get("gaussian")
    if not gaussian_cfg:
        return None
    _, gjf = create_gaussian_refine_node(
        ctx.root,
        source_node_id=ctx.neb_node_id,
        candidate_id=str(summary["candidate_id"]),
        candidate_xyz=Path(str(summary["ts_candidate_xyz"])),
        gaussian_cfg=gaussian_cfg,
    )
    return gjf


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
            raise ConfigError("source node and candidate are required; no promotable candidate metadata was found")
        source_node_id, candidate_id = inferred
    assert source_node_id is not None
    assert candidate_id is not None
    candidate_json = project_root / "nodes" / source_node_id / "candidates" / f"{candidate_id}.json"
    if not candidate_json.exists():
        raise ConfigError(f"candidate metadata not found: {candidate_json}")
    data = json.loads(candidate_json.read_text(encoding="utf-8"))
    xyz = Path(str(data.get("xyz", "")))
    if not xyz.is_absolute():
        xyz = project_root / xyz
    if not xyz.exists():
        matches = sorted((project_root / "nodes" / source_node_id / "candidates").glob(f"{candidate_id}_*.xyz"))
        if not matches:
            raise ConfigError(f"candidate xyz not found for {candidate_id}")
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
    raise ConfigError("could not infer validation parent node; pass --parent-node")


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
    write_markdown(
        node_dir / "report.md",
        f"""# Validation Plan

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
    )
    write_reflection_template(node_dir, decision="run_mode_endpoint_validation")
    upsert_tree_node(
        project_root,
        node_id,
        parent=parent_node_id,
        stage="validation_plan",
        status="pending",
    )
    update_tree_node_metadata(project_root, node_id, node)
    return node_id, node_dir / "validation_policy.json"


__all__ = [
    "displacement_ladder",
    "threshold_policy",
    "irc_policy",
    "find_project_input",
    "build_validation_policy",
    "gaussian_refinement_defaults",
    "write_gaussian_input",
    "update_tree_node_metadata",
    "create_gaussian_refine_node",
    "maybe_write_refinement_input",
    "latest_promotable_candidate",
    "resolve_candidate",
    "latest_node_with_stage",
    "default_validation_parent",
    "create_validation_plan_node",
]
