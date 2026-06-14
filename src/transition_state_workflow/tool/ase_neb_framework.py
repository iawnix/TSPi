#!/usr/bin/env python3
"""Run ASE-managed NEB workflows with xTB or Gaussian calculators.

The script keeps imports for ASE and calculator packages lazy so that config
validation and Gaussian input generation work on machines that do not have the
chemistry stack installed.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from transition_state_workflow.backends.ase import import_ase_bits
from transition_state_workflow.tools.ase_neb.config import (
    ProjectContext,
    normalize_config,
    read_text_config,
    resolve_config_paths,
    validate_config,
)
from transition_state_workflow.tools.ase_neb.constants import OPTIMIZER_NAMES
from transition_state_workflow.tool.ase_neb.driver import (
    attach_calculators,
    evaluate_neb_candidate_quality,
    make_neb_object,
)
from transition_state_workflow.tools.ase_neb.results import write_path_summary
from transition_state_workflow.tools.ase_neb.errors import ConfigError
from transition_state_workflow.tool.ase_neb.external_gaussian import (
    ExternalGaussianRun,
    continue_gaussian_neb_from_images,
    dry_run_gaussian_neb_inputs,
)
from transition_state_workflow.tool.ase_neb.gaussian_calc import temporary_env
from transition_state_workflow.tools.ase_neb.geometry import parse_angle_spec, parse_bond_spec
from transition_state_workflow.tools.ase_neb.images import (
    build_images_from_endpoints,
    load_endpoint_images,
    write_image_set,
)
from transition_state_workflow.tools.ase_neb.mechanism import ENDPOINT_STATE_CHOICES
from transition_state_workflow.core.ase_neb_nodes import (
    write_input_check_node,
    write_neb_node_metadata,
)
from transition_state_workflow.tool.ase_neb.validation import (
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
from transition_state_workflow.core.ase_neb_workspace import (
    ensure_project_scaffold,
    write_json,
    write_reflection_template,
)
from transition_state_workflow.util.cli import CliError, emit_json, log, run_cli


def prepare(cfg: dict[str, Any], *, config_path: Path | None = None) -> ProjectContext:
    ctx = ensure_project_scaffold(cfg, config_path=config_path)
    reactant, product = load_endpoint_images(cfg)
    write_input_check_node(ctx, cfg, reactant, product)
    images = build_images_from_endpoints(cfg, reactant, product)
    write_image_set(images, ctx.neb_node, "initial")
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
    bits = import_ase_bits()
    read = bits["read"]
    images = [
        read(ctx.neb_node / "images" / f"initial_image_{i:02d}.xyz")
        for i in range(cfg["images"])
    ]
    attach_calculators(cfg, images, ctx.neb_node)
    neb = make_neb_object(cfg, images)

    optimizer_cfg = cfg["optimizer"]
    optimizer_cls = bits["optimizers"][optimizer_cfg["name"]]
    (ctx.neb_node / "logs").mkdir(parents=True, exist_ok=True)
    opt = optimizer_cls(
        neb,
        trajectory=str(ctx.neb_node / "trajectories" / "neb.traj"),
        logfile=str(ctx.neb_node / "logs" / "neb.log"),
    )
    with temporary_env(cfg["calculator"].get("env", {})):
        optimizer_converged = bool(
            opt.run(fmax=float(optimizer_cfg["fmax"]), steps=int(optimizer_cfg["steps"]))
        )

    write_image_set(images, ctx.neb_node, "final")
    summary = write_path_summary(ctx.neb_node, images, status="succeeded")
    summary["optimizer_converged"] = optimizer_converged
    summary["candidate_quality"] = evaluate_neb_candidate_quality(
        summary,
        cfg,
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
    write_json(ctx.neb_node / "summary.json", summary)
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
        # External Gaussian failures (non-zero exit, missing output, abnormal
        # termination) are reported to the user as a CLI error envelope.
        raise CliError(f"gaussian neb continuation failed: {exc}") from exc
    emit_json(summary)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate-config", help="Validate a NEB config.")
    validate.add_argument("config", type=Path)
    validate.add_argument("--strict-files", action="store_true")
    validate.add_argument("--require-deps", action="store_true")
    validate.set_defaults(func=command_validate)

    prepare_cmd = subparsers.add_parser(
        "prepare",
        help="Build interpolated ASE images and write initial path files.",
    )
    prepare_cmd.add_argument("config", type=Path)
    prepare_cmd.set_defaults(func=command_prepare)

    run_cmd = subparsers.add_parser("run", help="Run ASE NEB with configured calculator.")
    run_cmd.add_argument("config", type=Path)
    run_cmd.add_argument(
        "--allow-gaussian-neb",
        action="store_true",
        help="Explicitly allow Gaussian as the force calculator inside NEB.",
    )
    run_cmd.set_defaults(func=command_run)

    gaussian = subparsers.add_parser(
        "make-gaussian-refine",
        help="Create a Gaussian Opt(TS)+Freq input from an XYZ candidate.",
    )
    gaussian.add_argument("xyz", type=Path)
    gaussian.add_argument("-o", "--output", type=Path, required=True)
    gaussian.add_argument("--route")
    gaussian.add_argument("--charge", type=int)
    gaussian.add_argument("--multiplicity", type=int)
    gaussian.add_argument("--nprocshared", type=int)
    gaussian.add_argument("--mem")
    gaussian.add_argument("--chk")
    gaussian.add_argument("--title")
    gaussian.add_argument(
        "--extra-section",
        action="append",
        default=[],
        help="Append an extra Gaussian section from a file, e.g. Gen basis.",
    )
    gaussian.set_defaults(func=command_make_gaussian)

    promote = subparsers.add_parser(
        "promote-candidate",
        help="Create a project-tree Gaussian TS/Freq node from a candidate.",
    )
    promote.add_argument("project_root", type=Path)
    promote.add_argument("--source-node")
    promote.add_argument("--candidate")
    promote.add_argument("--route")
    promote.add_argument("--charge", type=int)
    promote.add_argument("--multiplicity", type=int)
    promote.add_argument("--nprocshared", type=int)
    promote.add_argument("--mem")
    promote.add_argument("--chk")
    promote.add_argument("--title")
    promote.add_argument(
        "--extra-section",
        action="append",
        default=[],
        help="Append an extra Gaussian section from a file, e.g. Gen basis.",
    )
    promote.set_defaults(func=command_promote_candidate)

    reflect = subparsers.add_parser(
        "reflect",
        help="Create or refresh a structured reflection template for a node.",
    )
    reflect.add_argument("project_root", type=Path)
    reflect.add_argument("node_id")
    reflect.add_argument("--decision", default="pending")
    reflect.add_argument("--force", action="store_true")
    reflect.set_defaults(func=command_reflect)

    plan = subparsers.add_parser(
        "plan-validation",
        help="Plan adaptive TS connectivity validation gates and follow-up jobs.",
    )
    plan.add_argument("project_root", type=Path)
    plan.add_argument("--parent-node")
    plan.add_argument("--reactant", type=Path)
    plan.add_argument("--product", type=Path)
    plan.add_argument("--bond", action="append", default=[], help="Tracked forming/breaking bond i-j.")
    plan.add_argument("--angle", action="append", default=[], help="Tracked reaction-center angle i-j-k.")
    plan.add_argument(
        "--system-class",
        choices=["auto", "small_rigid", "flexible", "h_transfer", "metal"],
        default="auto",
    )
    plan.add_argument("--imag-frequency", type=float, help="Imaginary frequency in cm^-1, if known.")
    plan.add_argument("--publication-grade", action="store_true")
    plan.add_argument("--force-irc", action="store_true")
    plan.add_argument("--multi-product", action="store_true")
    plan.add_argument("--flat-pes", action="store_true")
    plan.add_argument("--solvent-participates", action="store_true")
    plan.add_argument("--post-ts-bifurcation", action="store_true")
    plan.add_argument("--large-nonreactive-rearrangement", action="store_true")
    plan.set_defaults(func=command_plan_validation)

    cont = subparsers.add_parser(
        "continue-gaussian-neb-from-images",
        help="Continue an existing XYZ image path with an external Gaussian force calculator.",
    )
    cont.add_argument("project_root", type=Path)
    cont.add_argument("--xyz-dir", type=Path, required=True)
    cont.add_argument("--pattern", default="image_*.xyz")
    cont.add_argument("--route", required=True, help="Gaussian route; must request forces.")
    cont.add_argument("--charge", type=int, required=True)
    cont.add_argument("--multiplicity", type=int, required=True)
    cont.add_argument("--template-gjf", type=Path, help="Template gjf whose post-coordinate section is reused.")
    cont.add_argument("--tail-file", type=Path, help="Explicit post-coordinate Gaussian section file.")
    cont.add_argument("--command", default="g16", help="Gaussian executable or shell command.")
    cont.add_argument("--mem")
    cont.add_argument("--nprocshared", type=int)
    cont.add_argument("--output-suffix", default=".out")
    cont.add_argument("--require-normal-termination", action=argparse.BooleanOptionalAction, default=True)
    cont.add_argument("--parent-node")
    cont.add_argument("--optimizer", choices=sorted(OPTIMIZER_NAMES), default="BFGS")
    cont.add_argument("--fmax", type=float, default=0.05)
    cont.add_argument("--steps", type=int, default=1)
    cont.add_argument("--climb", action="store_true")
    cont.add_argument("--k", type=float, default=0.1)
    cont.add_argument("--method", default="improvedtangent")
    cont.add_argument("--dynamic", action="store_true")
    cont.add_argument("--remove-rotation-and-translation", action="store_true")
    cont.add_argument("--min-barrier-ev", type=float, default=0.03)
    cont.add_argument("--allow-endpoint-candidate", action="store_true")
    cont.add_argument(
        "--reactant-endpoint-state",
        choices=ENDPOINT_STATE_CHOICES,
        default="reference_hypothesis",
        help="Declared readiness of the reactant endpoint feeding these images. "
        "Promotion requires both endpoints to be validated_minimum, lower_level_minimum, "
        "or constrained_reference.",
    )
    cont.add_argument(
        "--product-endpoint-state",
        choices=ENDPOINT_STATE_CHOICES,
        default="reference_hypothesis",
        help="Declared readiness of the product endpoint feeding these images.",
    )
    cont.add_argument("--endpoint-level", help="Level/method that established endpoint readiness.")
    cont.add_argument("--endpoint-evidence", help="Pointer to the endpoint-readiness evidence record.")
    cont.add_argument(
        "--allow-gaussian-neb",
        action="store_true",
        help="Required for real external Gaussian NEB execution.",
    )
    cont.add_argument(
        "--dry-run-inputs",
        action="store_true",
        help="Prepare tree node and first Gaussian input without running Gaussian.",
    )
    cont.set_defaults(func=command_continue_gaussian_neb_from_images)

    return parser


def _dispatch(argv: list[str] | None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


def main(argv: list[str] | None = None) -> int:
    # ConfigError and CliError both raise inside the command functions; the shared
    # ``run_cli`` wrapper turns them into a single ``{ok: false, error}`` envelope
    # on stderr with a stable exit code, so individual commands do not catch
    # them by hand.
    return run_cli(_translate_config_error, argv)


def _translate_config_error(argv: list[str] | None) -> int:
    try:
        return _dispatch(argv)
    except ConfigError as exc:
        # ConfigError is a ValueError, which run_cli does not catch; translate it
        # here. FileNotFoundError is handled by run_cli directly.
        raise CliError(str(exc)) from exc


if __name__ == "__main__":
    raise SystemExit(main())
