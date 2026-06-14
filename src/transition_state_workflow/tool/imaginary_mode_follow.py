#!/usr/bin/env python3
"""Follow Gaussian imaginary modes with node-scoped TS-workflow artifacts."""

from __future__ import annotations

import argparse
from pathlib import Path

from transition_state_workflow.backends.gaussian import (
    QST_ROUTE_TOKENS,
    endpoint_template_from_gjf,
    final_gaussian_atoms_from_log,
    gaussian_endpoint_route,
    parse_gaussian_input_template,
    prepare_gaussian_imaginary_mode_follow_data,
    write_gaussian_endpoint_opt_input,
)
from transition_state_workflow.core.imaginary_mode_follow import (
    resolve_make_opt_output_path,
    resolve_output_layout,
    write_endpoint_connectivity_summary,
    write_irc_connectivity_artifacts,
    write_json,
    write_prepare_artifacts,
)
from transition_state_workflow.gate.connectivity import (
    endpoint_connection_screen,
    irc_connection_screen,
)
from transition_state_workflow.util.cli import CliError, emit_json, run_cli


def command_prepare(args: argparse.Namespace) -> int:
    """Extract an imaginary mode and prepare node-scoped endpoint opt inputs."""

    layout = resolve_output_layout(
        workspace=args.workspace,
        node_id=args.node_id,
        output_dir=args.output_dir,
    )
    follow = prepare_gaussian_imaginary_mode_follow_data(args.freq_output, scale=args.scale)
    if follow.mode is None:
        summary = write_prepare_artifacts(
            layout,
            freq_output=args.freq_output,
            summary=follow.summary,
        )
        emit_json({"status": "not_validated", "summary": summary})
        return 2

    endpoint_inputs = None
    stripped_qst_tail = None
    if args.template_gjf:
        if follow.minus_atoms is None or follow.plus_atoms is None:
            raise ValueError("internal error: imaginary-mode endpoint geometries are unavailable")
        template, stripped_qst_tail = endpoint_template_from_gjf(args.template_gjf)
        route = args.route or gaussian_endpoint_route(str(template["route"]))
        endpoint_inputs = [
            write_gaussian_endpoint_opt_input(
                layout.inputs / "imaginary_minus_opt.gjf",
                follow.minus_atoms,
                template=template,
                route=route,
                chk="imaginary_minus_opt.chk",
                nproc=args.nproc,
                mem=args.mem,
                title=f"{args.title_prefix} minus displacement endpoint opt",
            ),
            write_gaussian_endpoint_opt_input(
                layout.inputs / "imaginary_plus_opt.gjf",
                follow.plus_atoms,
                template=template,
                route=route,
                chk="imaginary_plus_opt.chk",
                nproc=args.nproc,
                mem=args.mem,
                title=f"{args.title_prefix} plus displacement endpoint opt",
            ),
        ]

    summary = write_prepare_artifacts(
        layout,
        freq_output=args.freq_output,
        summary=follow.summary,
        ts_atoms=follow.atoms,
        minus_atoms=follow.minus_atoms,
        plus_atoms=follow.plus_atoms,
        scan_frames=follow.scan_frames,
        endpoint_opt_inputs=endpoint_inputs,
        template_qst_tail_stripped=stripped_qst_tail,
    )
    emit_json(
        {
            "status": "validated_ts_freq" if summary["is_ts_frequency_validated"] else "one_imaginary_frequency",
            "mode_index": follow.mode.index,
            "frequency_cm_1": float(follow.mode.frequency),
            "parsed": str(layout.parsed / "imaginary_mode_summary.json"),
            "summary": summary,
        }
    )
    return 0


def command_compare(args: argparse.Namespace) -> int:
    """Compare two endpoint optimization logs by simple bond-connectivity change."""

    layout = resolve_output_layout(
        workspace=args.workspace,
        node_id=args.node_id,
        output_dir=args.output_dir,
    )
    screen = endpoint_connection_screen(
        args.minus_log,
        args.plus_log,
        bond_scale=args.bond_scale,
        ts_log=args.ts_log,
    )
    summary_path = write_endpoint_connectivity_summary(layout, screen.summary)
    emit_json(
        {
            "status": "connection_screen_supported"
            if screen.summary["simple_connection_screen_supported"]
            else "connection_not_established",
            "diff_bonds": screen.summary["connectivity_diff_count"],
            "summary": str(summary_path),
        }
    )
    return 0 if screen.summary["simple_connection_screen_supported"] else 3


def command_irc_compare(args: argparse.Namespace) -> int:
    """Compare final geometries from forward/reverse Gaussian IRC outputs."""

    layout = resolve_output_layout(
        workspace=args.workspace,
        node_id=args.node_id,
        output_dir=args.output_dir,
    )
    screen = irc_connection_screen(
        args.forward_log,
        args.reverse_log,
        bond_scale=args.bond_scale,
    )
    summary_path = write_irc_connectivity_artifacts(
        layout,
        summary=screen.summary,
        forward_atoms=screen.forward_atoms,
        reverse_atoms=screen.reverse_atoms,
        forward_log=args.forward_log,
        reverse_log=args.reverse_log,
    )
    forward_status = screen.summary["forward"]
    reverse_status = screen.summary["reverse"]
    emit_json(
        {
            "status": "irc_connection_screen_supported"
            if screen.summary["irc_connection_screen_supported"]
            else "irc_connection_not_established",
            "forward_point": forward_status["last_accepted_point"],
            "reverse_point": reverse_status["last_accepted_point"],
            "diff_bonds": screen.summary["connectivity_diff_count"],
            "summary": str(summary_path),
        }
    )
    return 0 if screen.summary["irc_connection_screen_supported"] else 3


def command_make_opt(args: argparse.Namespace) -> int:
    """Build a Gaussian opt input from the final geometry in a Gaussian output."""

    atoms = final_gaussian_atoms_from_log(args.source_log)
    template = parse_gaussian_input_template(args.template_gjf)
    route = args.route or gaussian_endpoint_route(str(template["route"]))
    output_gjf = resolve_make_opt_output_path(
        workspace=args.workspace,
        node_id=args.node_id,
        output_gjf=args.output_gjf,
    )
    chk = args.chk or f"{output_gjf.stem}.chk"
    write_gaussian_endpoint_opt_input(
        output_gjf,
        atoms,
        template=template,
        route=route,
        chk=chk,
        nproc=args.nproc,
        mem=args.mem,
        title=args.title,
    )
    emit_json({"status": "wrote_opt_input", "atoms": len(atoms), "route": route, "output": str(output_gjf)})
    return 0


def add_layout_arguments(parser: argparse.ArgumentParser) -> None:
    """Add common node-scoped/legacy output arguments to a subparser."""

    parser.add_argument("--workspace", type=Path, help="TS-search workspace root for node-scoped output.")
    parser.add_argument("--node-id", help="Existing node id for node-scoped output.")
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        help="Legacy flat output directory. Prefer --workspace with --node-id.",
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser."""

    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare", help="Extract imaginary mode and prepare endpoint opt inputs.")
    prepare.add_argument("freq_output", type=Path)
    add_layout_arguments(prepare)
    prepare.add_argument("--scale", type=float, default=0.25, help="Max atom displacement in Angstrom.")
    prepare.add_argument("--template-gjf", type=Path, help="Gaussian input template for endpoint opt jobs.")
    prepare.add_argument("--route", help="Override endpoint opt route.")
    prepare.add_argument("--nproc", type=int)
    prepare.add_argument("--mem")
    prepare.add_argument("--title-prefix", default="Imaginary mode follow")
    prepare.set_defaults(func=command_prepare)

    compare = subparsers.add_parser("compare", help="Compare two optimized endpoint outputs by simple connectivity.")
    compare.add_argument("--minus-log", type=Path, required=True)
    compare.add_argument("--plus-log", type=Path, required=True)
    compare.add_argument("--ts-log", type=Path)
    add_layout_arguments(compare)
    compare.add_argument("--bond-scale", type=float, default=1.25)
    compare.set_defaults(func=command_compare)

    irc_compare = subparsers.add_parser("irc-compare", help="Compare forward/reverse Gaussian IRC final geometries.")
    irc_compare.add_argument("--forward-log", type=Path, required=True)
    irc_compare.add_argument("--reverse-log", type=Path, required=True)
    add_layout_arguments(irc_compare)
    irc_compare.add_argument("--bond-scale", type=float, default=1.25)
    irc_compare.set_defaults(func=command_irc_compare)

    make_opt = subparsers.add_parser("make-opt", help="Build a Gaussian opt input from final log geometry.")
    make_opt.add_argument("source_log", type=Path)
    make_opt.add_argument("--template-gjf", type=Path, required=True)
    make_opt.add_argument("-o", "--output-gjf", type=Path, required=True)
    make_opt.add_argument("--workspace", type=Path, help="TS-search workspace root for node-scoped output.")
    make_opt.add_argument("--node-id", help="Existing node id for node-scoped output.")
    make_opt.add_argument("--route", help="Override route for the new opt input.")
    make_opt.add_argument("--chk", help="Checkpoint filename for the new input.")
    make_opt.add_argument("--nproc", type=int)
    make_opt.add_argument("--mem")
    make_opt.add_argument("--title", default="Gaussian opt restart from final log geometry")
    make_opt.set_defaults(func=command_make_opt)
    return parser


def _run(argv: list[str] | None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except ValueError as exc:
        raise CliError(str(exc)) from exc


def main(argv: list[str] | None = None) -> int:
    return run_cli(_run, argv)


if __name__ == "__main__":
    raise SystemExit(main())
