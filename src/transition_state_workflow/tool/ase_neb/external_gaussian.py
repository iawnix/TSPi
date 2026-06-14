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
    ExternalGaussianCalculatorRequest,
    evaluate_neb_candidate_quality,
    import_ase_bits,
    make_neb_object,
    read_xyz_images_from_dir,
    write_candidate_quality_artifacts,
    write_image_set,
    write_path_summary,
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
    if "force" not in route.lower():
        raise ConfigError("external Gaussian NEB route must include force")


def dry_run_gaussian_neb_inputs(run: ExternalGaussianRun) -> dict[str, Any]:
    """Prepare the tree node and the first Gaussian input without running Gaussian.

    Reads the image directory, writes the input-check and NEB nodes, and writes
    the first image's ``.gjf`` so the user can inspect it before committing
    compute time.
    """

    _require_force_route(run.route)
    ensure_external_gaussian_project(run.project_root)
    node_id = continue_node_id_from_images(run.project_root, run.route)
    images, source_files = read_xyz_images_from_dir(run.xyz_dir, run.pattern, index=0)
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
    write_image_set(images, node_dir, "initial")
    calculator_request = run.calculator_request()
    calc = calculator_request.calculator(
        image_index=0,
        image_dir=node_dir / "calculators" / "image_000",
        tail=calculator_request.tail(),
    )
    calc.write_input(images[0])
    return {
        "ok": True,
        "dry_run": True,
        "node_id": node_id,
        "node_dir": str(node_dir),
        "image_count": len(images),
        "first_input": str(calc.gjf),
    }


def continue_gaussian_neb_from_images(run: ExternalGaussianRun, *, allow_gaussian_neb: bool) -> dict[str, Any]:
    if not allow_gaussian_neb:
        raise ConfigError("external Gaussian NEB requires --allow-gaussian-neb")
    _require_force_route(run.route)
    ensure_external_gaussian_project(run.project_root)
    node_id = continue_node_id_from_images(run.project_root, run.route)
    images, source_files = read_xyz_images_from_dir(run.xyz_dir, run.pattern, index=0)
    calculator_request = run.calculator_request()
    tail = calculator_request.tail()
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
    write_image_set(images, node_dir, "initial")
    calc_root = node_dir / "calculators"
    for index, image in enumerate(images):
        image.calc = calculator_request.calculator(
            image_index=index,
            image_dir=calc_root / f"image_{index:03d}",
            tail=tail,
        )
    neb = make_neb_object({"neb": run.neb_cfg}, images)
    bits = import_ase_bits()
    optimizer_cls = bits["optimizers"][run.optimizer_cfg["name"]]
    (node_dir / "logs").mkdir(parents=True, exist_ok=True)
    opt = optimizer_cls(
        neb,
        trajectory=str(node_dir / "trajectories" / "gaussian_external_neb.traj"),
        logfile=str(node_dir / "logs" / "gaussian_external_neb.log"),
    )
    optimizer_converged = bool(
        opt.run(fmax=float(run.optimizer_cfg["fmax"]), steps=int(run.optimizer_cfg["steps"]))
    )
    write_image_set(images, node_dir, "final")
    summary = write_path_summary(node_dir, images, status="succeeded")
    summary["optimizer_converged"] = optimizer_converged
    summary["candidate_quality"] = evaluate_neb_candidate_quality(
        summary,
        {
            "candidate_selection": run.candidate_selection,
            "endpoint_validation": run.endpoint_validation,
        },
        optimizer_converged=optimizer_converged,
    )
    write_candidate_quality_artifacts(node_dir, summary)
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
    "ExternalGaussianRun",
    "external_gaussian_level_slug",
    "continue_node_id_from_images",
    "ensure_external_gaussian_project",
    "write_external_image_input_node",
    "write_external_gaussian_neb_node",
    "dry_run_gaussian_neb_inputs",
    "continue_gaussian_neb_from_images",
]
