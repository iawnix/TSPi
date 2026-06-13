#!/usr/bin/env python3
"""Follow Gaussian imaginary modes with node-scoped TS-workflow artifacts."""

from __future__ import annotations

import argparse
from pathlib import Path

from transition_state_workflow.chem.gaussian_log import (
    displaced_atoms,
    endpoint_route,
    final_geometry,
    frequency_summary,
    parse_charge_multiplicity,
    parse_gjf_template,
    parse_irc_status,
    parse_modes,
    read_lines,
    terminated_normally,
    write_gjf,
)
from transition_state_workflow.chem.geometry import append_xyz_frame, bond_labels, bond_set, write_xyz
from transition_state_workflow.util.cli import CliError, emit_json, run_cli
from transition_state_workflow.util.json_io import write_json_object
from transition_state_workflow.util.node_layout import NodeLayout, resolve_node_layout


QST_ROUTE_TOKENS = ("qst2", "qst3")


def write_json(path: Path, payload: dict[str, object]) -> None:
    """Write stable JSON atomically (delegates to the shared util writer)."""

    write_json_object(path, payload)


def resolve_output_layout(args: argparse.Namespace) -> NodeLayout:
    """Resolve either a first-class node layout or a legacy output directory."""

    has_node_scope = bool(args.workspace or args.node_id)
    if has_node_scope:
        if not args.workspace or not args.node_id:
            raise ValueError("--workspace and --node-id must be provided together")
        if args.output_dir:
            raise ValueError("use either --workspace/--node-id or --output-dir, not both")
        return resolve_node_layout(args.workspace, args.node_id)
    if not args.output_dir:
        raise ValueError("provide --workspace/--node-id for node-scoped output or legacy --output-dir")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    # Legacy loose mode: every artifact lands in the single output directory.
    out = args.output_dir
    return NodeLayout(root=out, node_dir=out, inputs=out, outputs=out, parsed=out, scratch=out)


def endpoint_template_from_gjf(path: Path) -> tuple[dict[str, object], bool]:
    """Return a template safe for single-geometry endpoint Opt input generation."""

    template = parse_gjf_template(path)
    route = str(template.get("route", "")).lower()
    if any(token in route for token in QST_ROUTE_TOKENS):
        template = {**template, "tail": []}
        return template, True
    return template, False


def command_prepare(args: argparse.Namespace) -> int:
    """Extract an imaginary mode and prepare node-scoped endpoint opt inputs."""

    layout = resolve_output_layout(args)
    lines = read_lines(args.freq_output)
    atoms = final_geometry(lines)
    charge, multiplicity = parse_charge_multiplicity(lines)
    modes = parse_modes(lines, len(atoms))
    imaginary = [mode for mode in modes if mode.frequency < 0.0]

    summary: dict[str, object] = {
        "freq_output": str(args.freq_output),
        "natoms": len(atoms),
        "charge": charge,
        "multiplicity": multiplicity,
        "frequency_count": len(modes),
        "imaginary_frequency_count": len(imaginary),
        "imaginary_frequencies_cm-1": [mode.frequency for mode in imaginary],
        "normal_termination": terminated_normally(lines),
        "stationary_point_found": any("Stationary point found" in line for line in lines),
        "is_ts_frequency_validated": False,
        "artifact_layout": {
            "inputs": str(layout.inputs),
            "outputs": str(layout.outputs),
            "parsed": str(layout.parsed),
        },
    }
    if len(imaginary) != 1:
        write_json(layout.parsed / "imaginary_mode_summary.json", summary)
        emit_json({"status": "not_validated", "summary": summary})
        return 2

    mode = imaginary[0]
    summary["is_ts_frequency_validated"] = bool(summary["normal_termination"] and summary["stationary_point_found"])
    summary["claim_status_suggestion"] = "tsfreq_validated" if summary["is_ts_frequency_validated"] else "ambiguous"
    summary["imaginary_mode_index"] = mode.index
    summary["imaginary_mode_frequency_cm-1"] = mode.frequency
    summary["mode_scale_angstrom_max_atom_displacement"] = args.scale

    write_xyz(layout.outputs / "ts_final.xyz", atoms, f"Final TS geometry from {args.freq_output.name}")
    minus_atoms = displaced_atoms(atoms, mode, -args.scale)
    plus_atoms = displaced_atoms(atoms, mode, args.scale)
    write_xyz(layout.outputs / "imaginary_minus.xyz", minus_atoms, f"Displaced - along mode {mode.index}")
    write_xyz(layout.outputs / "imaginary_plus.xyz", plus_atoms, f"Displaced + along mode {mode.index}")

    frames: list[str] = []
    for multiplier in (-1.0, -0.5, 0.0, 0.5, 1.0):
        frame_atoms = displaced_atoms(atoms, mode, multiplier * args.scale)
        append_xyz_frame(
            frames,
            frame_atoms,
            f"mode {mode.index}, frequency {mode.frequency:.4f} cm-1, scale {multiplier * args.scale:.4f}",
        )
    (layout.outputs / "imaginary_mode_scan.xyz").write_text("\n".join(frames) + "\n", encoding="utf-8")

    if args.template_gjf:
        template, stripped_qst_tail = endpoint_template_from_gjf(args.template_gjf)
        route = args.route or endpoint_route(str(template["route"]))
        write_gjf(
            layout.inputs / "imaginary_minus_opt.gjf",
            minus_atoms,
            template,
            route,
            "imaginary_minus_opt.chk",
            args.nproc,
            args.mem,
            f"{args.title_prefix} minus displacement endpoint opt",
        )
        write_gjf(
            layout.inputs / "imaginary_plus_opt.gjf",
            plus_atoms,
            template,
            route,
            "imaginary_plus_opt.chk",
            args.nproc,
            args.mem,
            f"{args.title_prefix} plus displacement endpoint opt",
        )
        run_script = layout.outputs / "run_endpoint_opts.sh"
        run_script.write_text(
            "\n".join(
                [
                    "#!/usr/bin/env bash",
                    "set -euo pipefail",
                    'g16_bin="${G16_BIN:-g16}"',
                    '"$g16_bin" < ../inputs/imaginary_minus_opt.gjf > imaginary_minus_opt.out 2> imaginary_minus_opt.g16_driver.out',
                    '"$g16_bin" < ../inputs/imaginary_plus_opt.gjf > imaginary_plus_opt.out 2> imaginary_plus_opt.g16_driver.out',
                    "",
                ]
            ),
            encoding="utf-8",
        )
        run_script.chmod(0o755)
        summary["endpoint_opt_inputs"] = [
            str(layout.inputs / "imaginary_minus_opt.gjf"),
            str(layout.inputs / "imaginary_plus_opt.gjf"),
        ]
        summary["endpoint_run_script"] = str(run_script)
        summary["template_qst_tail_stripped"] = stripped_qst_tail

    write_json(layout.parsed / "imaginary_mode_summary.json", summary)
    emit_json(
        {
            "status": "validated_ts_freq" if summary["is_ts_frequency_validated"] else "one_imaginary_frequency",
            "mode_index": mode.index,
            "frequency_cm_1": float(mode.frequency),
            "parsed": str(layout.parsed / "imaginary_mode_summary.json"),
            "summary": summary,
        }
    )
    return 0


def command_compare(args: argparse.Namespace) -> int:
    """Compare two endpoint optimization logs by simple bond-connectivity change."""

    layout = resolve_output_layout(args)
    minus_lines = read_lines(args.minus_log)
    plus_lines = read_lines(args.plus_log)
    minus_atoms = final_geometry(minus_lines)
    plus_atoms = final_geometry(plus_lines)
    minus_bonds = bond_set(minus_atoms, args.bond_scale)
    plus_bonds = bond_set(plus_atoms, args.bond_scale)
    broken_minus_to_plus = minus_bonds - plus_bonds
    formed_minus_to_plus = plus_bonds - minus_bonds
    summary: dict[str, object] = {
        "minus_log": str(args.minus_log),
        "plus_log": str(args.plus_log),
        "minus_normal_termination": terminated_normally(minus_lines),
        "plus_normal_termination": terminated_normally(plus_lines),
        "minus_frequency_summary": frequency_summary(minus_lines),
        "plus_frequency_summary": frequency_summary(plus_lines),
        "minus_bond_count": len(minus_bonds),
        "plus_bond_count": len(plus_bonds),
        "bond_scale": args.bond_scale,
        "formed_from_minus_to_plus": bond_labels(formed_minus_to_plus, plus_atoms),
        "broken_from_minus_to_plus": bond_labels(broken_minus_to_plus, minus_atoms),
        "connectivity_diff_count": len(formed_minus_to_plus) + len(broken_minus_to_plus),
    }
    summary["simple_connection_screen_supported"] = bool(
        summary["minus_normal_termination"]
        and summary["plus_normal_termination"]
        and (
            not summary["minus_frequency_summary"]["has_frequency_analysis"]
            or summary["minus_frequency_summary"]["imaginary_frequency_count"] == 0
        )
        and (
            not summary["plus_frequency_summary"]["has_frequency_analysis"]
            or summary["plus_frequency_summary"]["imaginary_frequency_count"] == 0
        )
        and summary["connectivity_diff_count"]
    )
    if args.ts_log:
        ts_atoms = final_geometry(read_lines(args.ts_log))
        ts_bonds = bond_set(ts_atoms, args.bond_scale)
        summary["ts_bond_count"] = len(ts_bonds)
        summary["minus_vs_ts_diff_count"] = len(minus_bonds ^ ts_bonds)
        summary["plus_vs_ts_diff_count"] = len(plus_bonds ^ ts_bonds)

    write_json(layout.parsed / "endpoint_connectivity_summary.json", summary)
    emit_json(
        {
            "status": "connection_screen_supported"
            if summary["simple_connection_screen_supported"]
            else "connection_not_established",
            "diff_bonds": summary["connectivity_diff_count"],
            "summary": str(layout.parsed / "endpoint_connectivity_summary.json"),
        }
    )
    return 0 if summary["simple_connection_screen_supported"] else 3


def command_irc_compare(args: argparse.Namespace) -> int:
    """Compare final geometries from forward/reverse Gaussian IRC outputs."""

    layout = resolve_output_layout(args)
    forward_lines = read_lines(args.forward_log)
    reverse_lines = read_lines(args.reverse_log)
    forward_atoms = final_geometry(forward_lines)
    reverse_atoms = final_geometry(reverse_lines)
    forward_bonds = bond_set(forward_atoms, args.bond_scale)
    reverse_bonds = bond_set(reverse_atoms, args.bond_scale)
    formed_reverse_to_forward = forward_bonds - reverse_bonds
    broken_reverse_to_forward = reverse_bonds - forward_bonds

    forward_status = parse_irc_status(forward_lines)
    reverse_status = parse_irc_status(reverse_lines)
    both_reached_minima = bool(
        forward_status["normal_termination"]
        and reverse_status["normal_termination"]
        and forward_status["pes_minimum_detected"]
        and reverse_status["pes_minimum_detected"]
    )
    summary: dict[str, object] = {
        "forward_log": str(args.forward_log),
        "reverse_log": str(args.reverse_log),
        "forward": forward_status,
        "reverse": reverse_status,
        "forward_bond_count": len(forward_bonds),
        "reverse_bond_count": len(reverse_bonds),
        "bond_scale": args.bond_scale,
        "formed_from_reverse_to_forward": bond_labels(formed_reverse_to_forward, forward_atoms),
        "broken_from_reverse_to_forward": bond_labels(broken_reverse_to_forward, reverse_atoms),
        "connectivity_diff_count": len(formed_reverse_to_forward) + len(broken_reverse_to_forward),
    }
    summary["irc_connection_screen_supported"] = bool(both_reached_minima and summary["connectivity_diff_count"])

    write_xyz(layout.outputs / "forward_endpoint.xyz", forward_atoms, f"Final geometry from {args.forward_log.name}")
    write_xyz(layout.outputs / "reverse_endpoint.xyz", reverse_atoms, f"Final geometry from {args.reverse_log.name}")
    write_json(layout.parsed / "irc_connectivity_summary.json", summary)
    emit_json(
        {
            "status": "irc_connection_screen_supported"
            if summary["irc_connection_screen_supported"]
            else "irc_connection_not_established",
            "forward_point": forward_status["last_accepted_point"],
            "reverse_point": reverse_status["last_accepted_point"],
            "diff_bonds": summary["connectivity_diff_count"],
            "summary": str(layout.parsed / "irc_connectivity_summary.json"),
        }
    )
    return 0 if summary["irc_connection_screen_supported"] else 3


def command_make_opt(args: argparse.Namespace) -> int:
    """Build a Gaussian opt input from the final geometry in a Gaussian output."""

    lines = read_lines(args.source_log)
    atoms = final_geometry(lines)
    template = parse_gjf_template(args.template_gjf)
    route = args.route or endpoint_route(str(template["route"]))
    output_gjf = args.output_gjf
    if args.workspace or args.node_id:
        if not args.workspace or not args.node_id:
            raise ValueError("--workspace and --node-id must be provided together")
        layout = resolve_node_layout(args.workspace, args.node_id)
        output_gjf = layout.inputs / args.output_gjf.name
    else:
        output_gjf.parent.mkdir(parents=True, exist_ok=True)
    chk = args.chk or f"{output_gjf.stem}.chk"
    write_gjf(output_gjf, atoms, template, route, chk, args.nproc, args.mem, args.title)
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
        # ``ValueError`` is the contract used by the layout resolver and a few
        # input checks. ``run_cli`` renders the CliError as a one-line JSON
        # envelope on stderr.
        raise CliError(str(exc)) from exc


def main(argv: list[str] | None = None) -> int:
    return run_cli(_run, argv)


if __name__ == "__main__":
    raise SystemExit(main())
