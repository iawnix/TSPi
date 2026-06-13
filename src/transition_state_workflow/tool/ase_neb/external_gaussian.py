"""External-Gaussian NEB continuation pipeline.

A self-contained second pipeline that refines an *existing* NEB image directory
with external Gaussian single-point forces. It has its own project scaffold,
input-check node, and NEB node writers — parallel to the main path's
``ensure_project_scaffold`` / ``node_writers`` but rooted in supplied images
rather than reactant/product endpoints.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from pathlib import Path
from typing import Any

from transition_state_workflow.tool.ase_neb.config import input_node_id, safe_slug
from transition_state_workflow.tool.ase_neb.driver import (
    evaluate_neb_candidate_quality,
    make_neb_object,
    write_path_summary,
)
from transition_state_workflow.tool.ase_neb.errors import ConfigError
from transition_state_workflow.tool.ase_neb.gaussian_calc import (
    ExternalGaussianForceCalculator,
    extract_gaussian_tail_from_template,
    import_ase_bits,
)
from transition_state_workflow.tool.ase_neb.images import read_xyz_images_from_dir, write_image_set
from transition_state_workflow.tool.ase_neb.workspace import (
    append_evidence_record,
    ensure_tree_skeleton,
    finalize_node_report_and_tree,
    next_node_id,
    node_record,
    write_json,
)


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

        if self.tail_file:
            return self.tail_file.read_text(encoding="utf-8").rstrip() + "\n"
        if self.template_gjf:
            return extract_gaussian_tail_from_template(self.template_gjf)
        return ""

    def calculator(self, *, image_index: int, image_dir: Path, tail: str) -> ExternalGaussianForceCalculator:
        """Build an external-Gaussian force calculator for one image."""

        return ExternalGaussianForceCalculator(
            image_index=image_index,
            image_dir=image_dir,
            route=self.route,
            charge=self.charge,
            multiplicity=self.multiplicity,
            mem=self.mem,
            nprocshared=self.nprocshared,
            tail=tail,
            command=self.command,
            require_normal_termination=self.require_normal_termination,
            output_suffix=self.output_suffix,
        )


def _require_force_route(route: str) -> None:
    if "force" not in route.lower():
        raise ConfigError("external Gaussian NEB route must include force")


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
    calc = run.calculator(
        image_index=0,
        image_dir=node_dir / "calculators" / "image_000",
        tail=run.tail(),
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
    tail = run.tail()
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
        image.calc = run.calculator(
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
    candidate_json = Path(str(summary["candidate_json"]))
    if candidate_json.exists():
        candidate_data = json.loads(candidate_json.read_text(encoding="utf-8"))
        candidate_data["candidate_quality"] = summary["candidate_quality"]
        candidate_data["candidate_state"] = (
            "candidate"
            if summary["candidate_quality"]["accepted_for_promotion"]
            else "rejected"
        )
        write_json(candidate_json, candidate_data)
    write_json(node_dir / "summary.json", summary)
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
    "ExternalGaussianRun",
    "external_gaussian_level_slug",
    "continue_node_id_from_images",
    "ensure_external_gaussian_project",
    "write_external_image_input_node",
    "write_external_gaussian_neb_node",
    "dry_run_gaussian_neb_inputs",
    "continue_gaussian_neb_from_images",
]
