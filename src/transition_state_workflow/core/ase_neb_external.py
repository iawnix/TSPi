"""Core state writers for external-Gaussian ASE NEB continuation nodes."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from transition_state_workflow.base.ase_neb import input_node_id, safe_slug
from transition_state_workflow.core.workspace import (
    append_evidence_record,
    ensure_tree_skeleton,
    finalize_node_report_and_tree,
    next_node_id,
    node_record,
    write_json,
)


def external_gaussian_level_slug(route: str) -> str:
    match = re.search(r"#\s*([A-Za-z0-9+\-.]+)\s*/\s*([A-Za-z0-9+\-().,]+)", route)
    if match:
        return safe_slug(f"{match.group(1)}_{match.group(2)}")
    return "gaussian_external"


def continue_node_id_from_images(root: Path, route: str) -> str:
    return next_node_id(root, f"neb_gaussian_external_{external_gaussian_level_slug(route)}_from_images", start=20)


def ensure_external_gaussian_project(project_root: Path) -> None:
    system_slug = safe_slug(project_root.name, "system")
    ensure_tree_skeleton(
        project_root,
        system_slug=system_slug,
        manifest_extra={"entry": "external_gaussian_neb_from_existing_images"},
        readme_body=f"""# TS Search: {system_slug}

Status: candidate_search

This tree was initialized from an existing NEB image path and an external
Gaussian force-calculator refinement branch. NEB outputs are candidates only.
""",
    )


def write_external_image_input_node(
    project_root: Path,
    *,
    source_files: list[Path],
    images: list[Any],
    cfg: dict[str, Any],
) -> str:
    ensure_external_gaussian_project(project_root)
    node_id = input_node_id()
    node_dir = project_root / "nodes" / node_id
    node_dir.mkdir(parents=True, exist_ok=True)
    validation = {
        "atom_order_checked": True,
        "atom_count": len(images[0]) if images else 0,
        "image_count": len(images),
        "same_ordered_symbols": True,
        "source_xyz_dir": cfg["source_xyz_dir"],
        "xyz_pattern": cfg["xyz_pattern"],
    }
    write_json(node_dir / "validation.json", validation)
    write_json(
        node_dir / "source_images.json",
        {
            "source_xyz_dir": cfg["source_xyz_dir"],
            "xyz_pattern": cfg["xyz_pattern"],
            "files": [str(path) for path in source_files],
        },
    )
    node = node_record(
        node_id=node_id,
        parent_id=None,
        node_type="root",
        hypothesis="Existing NEB image directory defines the initial path for an external Gaussian NEB refinement branch.",
        changed_variables={},
        status="succeeded",
        evidence={
            "validation": str(node_dir / "validation.json"),
            "source_images": str(node_dir / "source_images.json"),
        },
        decision="split",
        stage="input_check",
        backend="ase",
        validation=validation,
        inputs={
            "source_xyz_dir": cfg["source_xyz_dir"],
            "xyz_pattern": cfg["xyz_pattern"],
        },
    )
    write_json(node_dir / "node.json", node)
    append_evidence_record(
        project_root,
        node_id=node_id,
        kind="external_source_images",
        path=node_dir / "source_images.json",
        claim="Existing image path was recorded as external candidate-generation input.",
        evidence_state="prepared",
    )
    append_evidence_record(
        project_root,
        node_id=node_id,
        kind="external_input_validation",
        path=node_dir / "validation.json",
        claim="Existing image path atom order and image count were checked.",
        evidence_state="prepared",
    )
    finalize_node_report_and_tree(
        project_root,
        node_dir,
        node_id,
        node,
        parent=None,
        stage="input_check",
        status="succeeded",
        report_body=f"""# Input Check

- Status: succeeded
- Source image count: {len(images)}
- Atom count: {len(images[0]) if images else 0}
- Source directory: `{cfg['source_xyz_dir']}`
- Pattern: `{cfg['xyz_pattern']}`

The existing path is an input candidate path. It does not validate a transition
state until Gaussian TS/Freq and connectivity evidence pass.
""",
        reflection_decision="split_to_external_gaussian_neb",
    )
    return node_id


def write_external_gaussian_neb_node(
    project_root: Path,
    node_id: str,
    *,
    parent_node_id: str | None,
    status: str,
    cfg: dict[str, Any],
    source_files: list[Path],
    summary: dict[str, Any] | None = None,
) -> Path:
    ensure_external_gaussian_project(project_root)
    node_dir = project_root / "nodes" / node_id
    node_dir.mkdir(parents=True, exist_ok=True)
    quality = summary.get("candidate_quality", {}) if summary else {}
    accepted_for_promotion = bool(quality.get("accepted_for_promotion", False))
    decision = "run_gaussian_neb_refinement" if summary is None else (
        "promote" if accepted_for_promotion else "backtrack"
    )
    validation = {
        "is_validated_transition_state": False,
        "claim": "External Gaussian NEB refinement is a candidate-generation/refinement branch, not TS validation.",
    }
    evidence = {
        "config": str(node_dir / "config.json"),
        "validation": str(node_dir / "validation.json"),
        "source_images": str(node_dir / "inputs" / "source_images.json"),
    }
    if summary:
        evidence["summary"] = str(node_dir / "summary.json")
        evidence["candidate_json"] = str(summary.get("candidate_json"))
    node = node_record(
        node_id=node_id,
        parent_id=parent_node_id,
        node_type="candidate_refinement",
        hypothesis="Continue an existing NEB image path with external Gaussian single-point forces under ASE NEB.",
        changed_variables={
            "source_images": "inputs/source_images.json",
            "route": cfg["route"],
            "charge": cfg["charge"],
            "multiplicity": cfg["multiplicity"],
            "optimizer": cfg["optimizer"],
            "neb": cfg["neb"],
        },
        status=status,
        evidence=evidence,
        decision=decision,
        outcome_code=None if accepted_for_promotion or summary is None else quality.get("outcome_code"),
        stage="gaussian_external_neb",
        backend="gaussian_external",
        level=external_gaussian_level_slug(cfg["route"]),
        config={
            "route": cfg["route"],
            "charge": cfg["charge"],
            "multiplicity": cfg["multiplicity"],
            "command": cfg["command"],
            "mem": cfg["mem"],
            "nprocshared": cfg["nprocshared"],
            "neb": cfg["neb"],
            "optimizer": cfg["optimizer"],
            "candidate_selection": cfg["candidate_selection"],
            "require_normal_termination": cfg["require_normal_termination"],
            "output_suffix": cfg["output_suffix"],
        },
        inputs={
            "source_images": "inputs/source_images.json",
            "source_image_count": len(source_files),
        },
        outputs={
            "images": "images/",
            "trajectories": "trajectories/",
            "tables": "tables/",
            "candidates": "candidates/",
            "calculators": "calculators/",
        },
        validation=validation,
    )
    if summary:
        node["summary"] = summary
        append_evidence_record(
            project_root,
            node_id=node_id,
            kind="gaussian_external_neb_summary",
            path=node_dir / "summary.json",
            claim=(
                "External Gaussian NEB produced a promotable candidate geometry."
                if accepted_for_promotion
                else "External Gaussian NEB did not pass candidate-promotion gates."
            ),
            evidence_state="candidate_found" if accepted_for_promotion else "ambiguous",
        )
        if summary.get("candidate_json"):
            append_evidence_record(
                project_root,
                node_id=node_id,
                kind="gaussian_external_neb_candidate",
                path=str(summary["candidate_json"]),
                claim="External Gaussian NEB maximum geometry is candidate-only evidence.",
                evidence_state="candidate_found" if accepted_for_promotion else "ambiguous",
            )
    write_json(node_dir / "node.json", node)
    write_json(node_dir / "config.json", cfg)
    write_json(node_dir / "validation.json", validation)
    write_json(
        node_dir / "inputs" / "source_images.json",
        {
            "source_xyz_dir": cfg["source_xyz_dir"],
            "xyz_pattern": cfg["xyz_pattern"],
            "files": [str(path) for path in source_files],
        },
    )
    append_evidence_record(
        project_root,
        node_id=node_id,
        kind="gaussian_external_neb_config",
        path=node_dir / "config.json",
        claim="External Gaussian NEB candidate-generation configuration was recorded.",
        evidence_state="prepared",
    )
    append_evidence_record(
        project_root,
        node_id=node_id,
        kind="gaussian_external_neb_source_images",
        path=node_dir / "inputs" / "source_images.json",
        claim="External Gaussian NEB source image list was recorded.",
        evidence_state="prepared",
    )
    append_evidence_record(
        project_root,
        node_id=node_id,
        kind="gaussian_external_neb_validation_policy",
        path=node_dir / "validation.json",
        claim="External Gaussian NEB remains candidate-only until TS/Freq and connectivity validation pass.",
        evidence_state="prepared",
    )
    lines = [
        "# External Gaussian NEB Continuation",
        "",
        f"- Status: {status}",
        f"- Source images: {len(source_files)}",
        "- Backend: external Gaussian force calculator",
        f"- Route: `{cfg['route']}`",
        f"- Optimizer: {cfg['optimizer']['name']}",
        "",
        "This branch refines an existing NEB path. The output remains a candidate until Gaussian TS/Freq and connectivity validation pass.",
    ]
    if summary:
        lines.extend(
            [
                "",
                "## Candidate",
                f"- Candidate: {summary['candidate_id']}",
                f"- Source image: {summary['ts_candidate_index']}",
                f"- Barrier vs first image: {summary['barrier_ev_relative_to_reactant']} eV",
                f"- Promotion gate: {'passed' if accepted_for_promotion else 'failed'}",
                f"- Gate reasons: {'; '.join(quality.get('reasons', [])) if quality else 'not evaluated'}",
            ]
        )
    reflection = None
    if summary:
        reflection = {
            "computational_outcome": (
                "External Gaussian NEB refinement completed and passed promotion gates."
                if accepted_for_promotion
                else "External Gaussian NEB refinement completed but failed promotion gates."
            ),
            "mechanistic_implication": (
                "The branch remains candidate-only; Gaussian TS/Freq and connectivity validation are still required."
                if accepted_for_promotion
                else "The branch should not be promoted until refinement quality issues are resolved."
            ),
            "knowledge_update": (
                "External Gaussian NEB produced a promotable candidate geometry."
                if accepted_for_promotion
                else "External Gaussian NEB did not produce a promotable candidate geometry."
            ),
            "next_branch": (
                "Prepare Gaussian TS/Freq validation."
                if accepted_for_promotion
                else "Backtrack to source images or branch-variable adjustment."
            ),
        }
    finalize_node_report_and_tree(
        project_root,
        node_dir,
        node_id,
        node,
        parent=parent_node_id,
        stage="gaussian_external_neb",
        status=status,
        report_body="\n".join(lines),
        reflection=reflection,
        reflection_decision=decision,
    )
    return node_dir


__all__ = [
    "external_gaussian_level_slug",
    "continue_node_id_from_images",
    "ensure_external_gaussian_project",
    "write_external_image_input_node",
    "write_external_gaussian_neb_node",
]
