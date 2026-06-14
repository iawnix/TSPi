"""ASE NEB workflow command implementations.

This module is the tool-layer orchestration boundary for ASE NEB commands: it
composes core workspace writers, ASE backend runtime/result producers, config
parsing, and validation-node helpers. The public ``ase_neb_framework`` module
keeps parser construction and dispatch only.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
from typing import Any

from transition_state_workflow.backends.ase_neb import (
    AseNebRuntimeRequest,
    evaluate_neb_candidate_quality,
    prepare_ase_neb_initial_path,
    run_ase_neb_candidate_path,
)
from transition_state_workflow.core.ase_neb_nodes import (
    write_input_check_node,
    write_neb_node_metadata,
)
from transition_state_workflow.core.workspace import ensure_tree_skeleton, write_json, write_reflection_template
from transition_state_workflow.cli.ase_neb_external import (
    ExternalGaussianRun,
    continue_gaussian_neb_from_images,
    dry_run_gaussian_neb_inputs,
)
from transition_state_workflow.cli.ase_neb_validation import (
    build_validation_policy,
    create_gaussian_refine_node,
    create_validation_plan_node,
    default_validation_parent,
    find_project_input,
    gaussian_refinement_defaults,
    maybe_write_refinement_input,
    resolve_candidate,
    write_gaussian_input,
)
from transition_state_workflow.tools.ase_neb.config import (
    ProjectContext,
    normalize_config,
    project_context,
    read_text_config,
    resolve_config_paths,
    validate_config,
)
from transition_state_workflow.tools.ase_neb.errors import ConfigError
from transition_state_workflow.tools.ase_neb.geometry import parse_angle_spec, parse_bond_spec
from transition_state_workflow.util.cli import CliError, emit_json, log


def ensure_ase_neb_project_scaffold(
    cfg: dict[str, Any],
    *,
    config_path: Path | None = None,
) -> ProjectContext:
    """Create the workspace scaffold and ASE NEB input copies for a run."""

    ctx = project_context(cfg)
    system_slug = cfg["project"]["system_slug"]
    ensure_tree_skeleton(
        ctx.root,
        system_slug=system_slug,
        readme_body=f"""# TS Search: {system_slug}

Status: candidate_search

This directory is a structured transition-state search tree. NEB outputs are
candidates only; accepted transition states require Gaussian frequency and
connectivity evidence.
""",
    )
    write_json(ctx.root / "inputs" / "config.normalized.json", cfg)
    if config_path is not None and config_path.exists():
        shutil.copyfile(config_path, ctx.root / "inputs" / "config.original.json")
    for key in ("reactant", "product"):
        source = Path(str(cfg[key]))
        if source.exists():
            shutil.copyfile(source, ctx.root / "inputs" / f"{key}{source.suffix or '.xyz'}")
    return ctx


def prepare(cfg: dict[str, Any], *, config_path: Path | None = None) -> ProjectContext:
    ctx = ensure_ase_neb_project_scaffold(cfg, config_path=config_path)
    preparation = prepare_ase_neb_initial_path(cfg, ctx.neb_node)
    write_input_check_node(ctx, cfg, preparation.reactant, preparation.product)
    write_neb_node_metadata(ctx, cfg, status="pending")
    return ctx


def run_neb(
    cfg: dict[str, Any],
    *,
    config_path: Path | None = None,
    allow_gaussian_neb: bool = False,
) -> dict[str, Any]:
    calc_cfg = cfg["calculator"]
    if calc_cfg["type"] in {"gaussian", "gaussian_external"} and not (
        allow_gaussian_neb or calc_cfg.get("allow_neb", False)
    ):
        raise ConfigError(
            "Gaussian NEB requires explicit opt-in: pass --allow-gaussian-neb "
            "or set calculator.allow_neb=true"
        )

    ctx = prepare(cfg, config_path=config_path)
    summary = run_ase_neb_candidate_path(
        node_dir=ctx.neb_node,
        runtime=AseNebRuntimeRequest(cfg=cfg),
    )
    status = "succeeded" if summary["candidate_quality"]["accepted_for_promotion"] else "ambiguous"
    write_neb_node_metadata(ctx, cfg, status=status, summary=summary)
    if summary["candidate_quality"]["accepted_for_promotion"]:
        maybe_write_refinement_input(cfg, ctx, summary)
    return summary


def make_gaussian_refine_from_cli(args: argparse.Namespace) -> Path:
    cfg = gaussian_refinement_defaults()
    for key in ("route", "charge", "multiplicity", "nprocshared", "mem", "chk", "title"):
        value = getattr(args, key)
        if value is not None:
            cfg[key] = value
    if args.extra_section:
        cfg["extra_sections"] = [Path(path).read_text(encoding="utf-8") for path in args.extra_section]
    return write_gaussian_input(args.xyz, args.output, cfg)


def load_config_for_cli(args: argparse.Namespace) -> dict[str, Any]:
    raw = read_text_config(args.config)
    cfg = normalize_config(raw)
    return resolve_config_paths(cfg, args.config)


def command_validate(args: argparse.Namespace) -> int:
    cfg = load_config_for_cli(args)
    warnings = validate_config(
        cfg,
        strict_files=args.strict_files,
        require_deps=args.require_deps,
    )
    emit_json({"ok": True, "warnings": warnings, "config": cfg})
    return 0


def command_prepare(args: argparse.Namespace) -> int:
    cfg = load_config_for_cli(args)
    validate_config(cfg, strict_files=True, require_deps=False)
    ctx = prepare(cfg, config_path=args.config)
    log(f"prepared project: {ctx.root}")
    log(f"neb node: {ctx.neb_node_id}")
    return 0


def command_run(args: argparse.Namespace) -> int:
    cfg = load_config_for_cli(args)
    validate_config(cfg, strict_files=True, require_deps=True)
    summary = run_neb(
        cfg,
        config_path=args.config,
        allow_gaussian_neb=args.allow_gaussian_neb,
    )
    emit_json(summary)
    return 0


def command_make_gaussian(args: argparse.Namespace) -> int:
    output = make_gaussian_refine_from_cli(args)
    log(f"wrote: {output}")
    return 0


def command_promote_candidate(args: argparse.Namespace) -> int:
    project_root = args.project_root.resolve()
    source_node_id, candidate_id, candidate_xyz = resolve_candidate(
        project_root,
        source_node_id=args.source_node,
        candidate_id=args.candidate,
    )
    gaussian_cfg = gaussian_refinement_defaults()
    for key in ("route", "charge", "multiplicity", "nprocshared", "mem", "chk", "title"):
        value = getattr(args, key)
        if value is not None:
            gaussian_cfg[key] = value
    if args.extra_section:
        gaussian_cfg["extra_sections"] = [
            Path(path).read_text(encoding="utf-8") for path in args.extra_section
        ]
    node_id, gjf = create_gaussian_refine_node(
        project_root,
        source_node_id=source_node_id,
        candidate_id=candidate_id,
        candidate_xyz=candidate_xyz,
        gaussian_cfg=gaussian_cfg,
    )
    emit_json({"node_id": node_id, "gaussian_input": str(gjf)})
    return 0


def command_reflect(args: argparse.Namespace) -> int:
    project_root = args.project_root.resolve()
    node_dir = project_root / "nodes" / args.node_id
    if not node_dir.exists():
        raise CliError(f"node not found: {node_dir}")
    path = write_reflection_template(node_dir, decision=args.decision, force=args.force)
    log(f"reflection: {path}")
    return 0


def command_plan_validation(args: argparse.Namespace) -> int:
    project_root = args.project_root.resolve()
    reactant = args.reactant or find_project_input(project_root, "reactant")
    product = args.product or find_project_input(project_root, "product")
    if reactant is None or product is None:
        raise ConfigError("reactant/product are required or must exist in project inputs/")
    parent_node = args.parent_node or default_validation_parent(project_root)
    risk_flags: list[str] = []
    for flag_name in (
        "multi_product",
        "flat_pes",
        "solvent_participates",
        "post_ts_bifurcation",
        "large_nonreactive_rearrangement",
    ):
        if getattr(args, flag_name):
            risk_flags.append(flag_name)
    policy = build_validation_policy(
        reactant,
        product,
        user_bonds=[parse_bond_spec(item) for item in args.bond],
        user_angles=[parse_angle_spec(item) for item in args.angle],
        system_class_override=args.system_class,
        imaginary_frequency=args.imag_frequency,
        publication_grade=args.publication_grade,
        force_irc=args.force_irc,
        risk_flags=risk_flags,
    )
    node_id, policy_path = create_validation_plan_node(
        project_root,
        parent_node_id=parent_node,
        policy=policy,
    )
    emit_json(
        {
            "node_id": node_id,
            "policy": str(policy_path),
            "system_class": policy["system_class"],
            "tracked_bonds": policy["reaction_center"]["tracked_bonds"],
            "tracked_angles": policy["reaction_center"]["tracked_angles"],
            "displacement_ladder_max_atom_a": policy["imaginary_mode_follow"]["displacement_ladder_max_atom_a"],
            "irc_policy": policy["irc_decision"],
        }
    )
    return 0


def command_continue_gaussian_neb_from_images(args: argparse.Namespace) -> int:
    run = ExternalGaussianRun(
        project_root=args.project_root.resolve(),
        xyz_dir=args.xyz_dir.resolve(),
        pattern=args.pattern,
        route=args.route,
        charge=args.charge,
        multiplicity=args.multiplicity,
        template_gjf=args.template_gjf.resolve() if args.template_gjf else None,
        tail_file=args.tail_file.resolve() if args.tail_file else None,
        command=args.command,
        mem=args.mem,
        nprocshared=args.nprocshared,
        neb_cfg={
            "climb": args.climb,
            "k": args.k,
            "method": args.method,
            "dynamic": args.dynamic,
            "remove_rotation_and_translation": args.remove_rotation_and_translation,
        },
        optimizer_cfg={"name": args.optimizer, "fmax": args.fmax, "steps": args.steps},
        candidate_selection={
            "min_barrier_ev": args.min_barrier_ev,
            "allow_endpoint_candidate": args.allow_endpoint_candidate,
        },
        endpoint_validation={
            "reactant_state": args.reactant_endpoint_state,
            "product_state": args.product_endpoint_state,
            "level": args.endpoint_level or "",
            "evidence": args.endpoint_evidence or "",
        },
        parent_node_id=args.parent_node,
        require_normal_termination=args.require_normal_termination,
        output_suffix=args.output_suffix,
    )
    if args.dry_run_inputs:
        emit_json(dry_run_gaussian_neb_inputs(run))
        return 0
    try:
        summary = continue_gaussian_neb_from_images(run, allow_gaussian_neb=args.allow_gaussian_neb)
    except RuntimeError as exc:
        raise CliError(f"gaussian neb continuation failed: {exc}") from exc
    emit_json(summary)
    return 0


__all__ = [
    "command_continue_gaussian_neb_from_images",
    "command_make_gaussian",
    "command_plan_validation",
    "command_prepare",
    "command_promote_candidate",
    "command_reflect",
    "command_run",
    "command_validate",
    "ensure_ase_neb_project_scaffold",
    "evaluate_neb_candidate_quality",
    "load_config_for_cli",
    "make_gaussian_refine_from_cli",
    "prepare",
    "run_neb",
]
