"""External-Gaussian NEB continuation pipeline.

A self-contained second pipeline that refines an *existing* NEB image directory
with external Gaussian single-point forces. It has its own project scaffold,
input-check node, and NEB node-state writes rooted in supplied images rather
than reactant/product endpoints.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from transition_state_workflow.backends.ase_neb import (
    AseNebConfigError,
    ExternalGaussianCalculatorRequest,
    ExternalGaussianNebRuntimeRequest,
    read_xyz_images_from_dir,
    require_external_gaussian_force_route,
    run_external_gaussian_neb_continuation,
    write_external_gaussian_dry_run_input,
)
from transition_state_workflow.core.ase_neb_external import (
    continue_node_id_from_images,
    ensure_external_gaussian_project,
    external_gaussian_level_slug,
    write_external_gaussian_neb_node,
    write_external_image_input_node,
)
from transition_state_workflow.tools.ase_neb.errors import ConfigError


@dataclass(frozen=True)
class ExternalGaussianRun:
    """All inputs for one external-Gaussian NEB continuation.

    Capturing them in one struct removes the 16-argument signature that the real
    run and the dry-run otherwise duplicate, and makes the node ``config.json``
    payload a single ``cfg()`` source instead of two hand-built dicts.
    """

    project_root: Path
    xyz_dir: Path
    pattern: str
    route: str
    charge: int
    multiplicity: int
    template_gjf: Path | None
    tail_file: Path | None
    command: str
    mem: str | None
    nprocshared: int | None
    neb_cfg: dict[str, Any]
    optimizer_cfg: dict[str, Any]
    candidate_selection: dict[str, Any]
    endpoint_validation: dict[str, Any]
    parent_node_id: str | None
    require_normal_termination: bool
    output_suffix: str

    def calculator_request(self) -> ExternalGaussianCalculatorRequest:
        """Return the backend runtime request for Gaussian force calculators."""

        return ExternalGaussianCalculatorRequest(
            route=self.route,
            charge=self.charge,
            multiplicity=self.multiplicity,
            template_gjf=self.template_gjf,
            tail_file=self.tail_file,
            command=self.command,
            mem=self.mem,
            nprocshared=self.nprocshared,
            require_normal_termination=self.require_normal_termination,
            output_suffix=self.output_suffix,
        )

    def runtime_request(self) -> ExternalGaussianNebRuntimeRequest:
        """Return the backend runtime request for the ASE NEB continuation."""

        return ExternalGaussianNebRuntimeRequest(
            calculator_request=self.calculator_request(),
            neb_cfg=self.neb_cfg,
            optimizer_cfg=self.optimizer_cfg,
            candidate_selection=self.candidate_selection,
            endpoint_validation=self.endpoint_validation,
        )

    def cfg(self, *, dry_run_inputs: bool = False) -> dict[str, Any]:
        """Return the node ``config.json`` payload for this run."""

        data: dict[str, Any] = {
            "source_xyz_dir": str(self.xyz_dir),
            "xyz_pattern": self.pattern,
            "route": self.route,
            "charge": self.charge,
            "multiplicity": self.multiplicity,
            "template_gjf": str(self.template_gjf) if self.template_gjf else None,
            "tail_file": str(self.tail_file) if self.tail_file else None,
            "command": self.command,
            "mem": self.mem,
            "nprocshared": self.nprocshared,
            "neb": self.neb_cfg,
            "optimizer": self.optimizer_cfg,
            "candidate_selection": self.candidate_selection,
            "endpoint_validation": self.endpoint_validation,
            "require_normal_termination": self.require_normal_termination,
            "output_suffix": self.output_suffix,
        }
        if dry_run_inputs:
            data["dry_run_inputs"] = True
        return data

    def tail(self) -> str:
        """Resolve the post-coordinate Gaussian section (template or tail file)."""

        return self.calculator_request().tail()

    def calculator(self, *, image_index: int, image_dir: Path, tail: str | None = None) -> Any:
        """Build an external-Gaussian force calculator for one image."""

        return self.calculator_request().calculator(
            image_index=image_index,
            image_dir=image_dir,
            tail=tail,
        )


def _require_force_route(route: str) -> None:
    try:
        require_external_gaussian_force_route(route)
    except AseNebConfigError as exc:
        raise ConfigError(str(exc)) from exc


def _read_xyz_images_from_dir(xyz_dir: Path, pattern: str) -> tuple[list[Any], list[Path]]:
    try:
        return read_xyz_images_from_dir(xyz_dir, pattern, index=0)
    except AseNebConfigError as exc:
        raise ConfigError(str(exc)) from exc


def dry_run_gaussian_neb_inputs(run: ExternalGaussianRun) -> dict[str, Any]:
    """Prepare the tree node and the first Gaussian input without running Gaussian.

    Reads the image directory, writes the input-check and NEB nodes, and writes
    the first image's ``.gjf`` so the user can inspect it before committing
    compute time.
    """

    _require_force_route(run.route)
    ensure_external_gaussian_project(run.project_root)
    node_id = continue_node_id_from_images(run.project_root, run.route)
    images, source_files = _read_xyz_images_from_dir(run.xyz_dir, run.pattern)
    cfg = run.cfg(dry_run_inputs=True)
    parent_node = run.parent_node_id
    if parent_node is None:
        parent_node = write_external_image_input_node(
            run.project_root, source_files=source_files, images=images, cfg=cfg
        )
    node_dir = write_external_gaussian_neb_node(
        run.project_root,
        node_id,
        parent_node_id=parent_node,
        status="pending",
        cfg=cfg,
        source_files=source_files,
    )
    try:
        first_input = write_external_gaussian_dry_run_input(
            node_dir=node_dir,
            images=images,
            calculator_request=run.calculator_request(),
        )
    except AseNebConfigError as exc:
        raise ConfigError(str(exc)) from exc
    return {
        "ok": True,
        "dry_run": True,
        "node_id": node_id,
        "node_dir": str(node_dir),
        "image_count": len(images),
        "first_input": str(first_input),
    }


def continue_gaussian_neb_from_images(run: ExternalGaussianRun, *, allow_gaussian_neb: bool) -> dict[str, Any]:
    if not allow_gaussian_neb:
        raise ConfigError("external Gaussian NEB requires --allow-gaussian-neb")
    _require_force_route(run.route)
    ensure_external_gaussian_project(run.project_root)
    node_id = continue_node_id_from_images(run.project_root, run.route)
    images, source_files = _read_xyz_images_from_dir(run.xyz_dir, run.pattern)
    cfg = run.cfg()
    parent_node_id = run.parent_node_id
    if parent_node_id is None:
        parent_node_id = write_external_image_input_node(
            run.project_root, source_files=source_files, images=images, cfg=cfg
        )
    node_dir = write_external_gaussian_neb_node(
        run.project_root,
        node_id,
        parent_node_id=parent_node_id,
        status="running",
        cfg=cfg,
        source_files=source_files,
    )
    try:
        summary = run_external_gaussian_neb_continuation(
            node_dir=node_dir,
            images=images,
            runtime=run.runtime_request(),
        )
    except AseNebConfigError as exc:
        raise ConfigError(str(exc)) from exc
    final_status = "succeeded" if summary["candidate_quality"]["accepted_for_promotion"] else "ambiguous"
    write_external_gaussian_neb_node(
        run.project_root,
        node_id,
        parent_node_id=parent_node_id,
        status=final_status,
        cfg=cfg,
        source_files=source_files,
        summary=summary,
    )
    return summary


__all__ = [
    "ExternalGaussianCalculatorRequest",
    "ExternalGaussianNebRuntimeRequest",
    "ExternalGaussianRun",
    "external_gaussian_level_slug",
    "continue_node_id_from_images",
    "ensure_external_gaussian_project",
    "write_external_image_input_node",
    "write_external_gaussian_neb_node",
    "dry_run_gaussian_neb_inputs",
    "continue_gaussian_neb_from_images",
]
