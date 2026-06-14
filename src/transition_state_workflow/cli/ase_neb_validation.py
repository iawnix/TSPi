"""Validation policy: displacement, thresholds, IRC, Gaussian refinement nodes.

Reads a candidate path/structure and emits a validation policy (displacement
ladder, threshold gates, IRC requirement, tracked bonds/angles), then writes
the Gaussian TS/Freq input node and the validation-plan node for downstream
mode-endpoint and IRC follow-up.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from transition_state_workflow.base.ase_neb import ProjectContext
from transition_state_workflow.backends.gaussian import (
    gaussian_refinement_defaults as _gaussian_refinement_defaults,
    write_gaussian_refinement_input,
)
from transition_state_workflow.core.ase_neb_validation import (
    create_validation_plan_node,
    default_validation_parent as _default_validation_parent,
    find_project_input,
    latest_node_with_stage,
    latest_promotable_candidate,
    prepare_gaussian_refine_node_layout,
    resolve_candidate as _resolve_candidate,
    write_gaussian_refine_node_state,
)
from transition_state_workflow.core.workspace import update_tree_node_metadata
from transition_state_workflow.gate.neb_candidate import (
    build_validation_policy as _build_validation_policy,
    displacement_ladder,
    irc_policy,
    threshold_policy,
)
from transition_state_workflow.tools.ase_neb.errors import ConfigError


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
    return _gaussian_refinement_defaults()


def write_gaussian_input(
    xyz_path: Path,
    output_path: Path,
    gaussian_cfg: dict[str, Any],
) -> Path:
    try:
        return write_gaussian_refinement_input(xyz_path, output_path, gaussian_cfg)
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc


def create_gaussian_refine_node(
    project_root: Path,
    *,
    source_node_id: str,
    candidate_id: str,
    candidate_xyz: Path,
    gaussian_cfg: dict[str, Any],
) -> tuple[str, Path]:
    layout = prepare_gaussian_refine_node_layout(
        project_root,
        candidate_id=candidate_id,
        candidate_xyz=candidate_xyz,
        gaussian_cfg=gaussian_cfg,
    )
    write_gaussian_input(layout.source_candidate, layout.gaussian_input, gaussian_cfg)
    return write_gaussian_refine_node_state(
        project_root,
        layout,
        source_node_id=source_node_id,
        candidate_id=candidate_id,
        candidate_xyz=candidate_xyz,
        gaussian_cfg=gaussian_cfg,
    )


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


def resolve_candidate(
    project_root: Path,
    *,
    source_node_id: str | None,
    candidate_id: str | None,
) -> tuple[str, str, Path]:
    try:
        return _resolve_candidate(
            project_root,
            source_node_id=source_node_id,
            candidate_id=candidate_id,
        )
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc


def default_validation_parent(project_root: Path) -> str:
    try:
        return _default_validation_parent(project_root)
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc


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
