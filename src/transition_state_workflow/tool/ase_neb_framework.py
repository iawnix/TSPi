#!/usr/bin/env python3
"""Run ASE-managed NEB workflows with xTB or Gaussian calculators.

The script keeps imports for ASE and calculator packages lazy so that config
validation and Gaussian input generation work on machines that do not have the
chemistry stack installed.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from transition_state_workflow.tools.ase_neb.constants import OPTIMIZER_NAMES
from transition_state_workflow.tools.ase_neb.errors import ConfigError
from transition_state_workflow.tools.ase_neb.mechanism import ENDPOINT_STATE_CHOICES
from transition_state_workflow.tool.ase_neb.workflow import (
    command_continue_gaussian_neb_from_images,
    command_make_gaussian,
    command_plan_validation,
    command_prepare,
    command_promote_candidate,
    command_reflect,
    command_run,
    command_validate,
    evaluate_neb_candidate_quality,
    load_config_for_cli,
    make_gaussian_refine_from_cli,
    prepare,
    run_neb,
)
from transition_state_workflow.util.cli import CliError, run_cli


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
