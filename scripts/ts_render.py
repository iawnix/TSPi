#!/usr/bin/env python3
"""Molecular render CLI for TSAgentSkill."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ts_runtime import ensure_runtime_python

ensure_runtime_python(ROOT)

from ts_render import EnvironmentChecker, MolVisualizer  # noqa: E402
from ts_render.config import CAMERA_PATHS, COLOR_SCHEMES, ENGINES, LAYOUTS, STYLES, parse_resolution  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(prog="ts_render")
    sub = parser.add_subparsers(dest="command", required=True)

    diagnostic = sub.add_parser("diagnostic", help="Check render runtime dependencies.")
    diagnostic.add_argument("--json", action="store_true")

    render = sub.add_parser("render", help="Render one molecular structure.")
    _add_common_render_args(render)
    render.add_argument("input")
    render.add_argument("-o", "--output", required=True)
    render.add_argument("--json", action="store_true")

    compare = sub.add_parser("compare", help="Render multiple structures side by side.")
    _add_common_render_args(compare, default_resolution="2048x1024")
    compare.add_argument("inputs", nargs="+")
    compare.add_argument("-o", "--output", required=True)
    compare.add_argument("--layout", choices=LAYOUTS, default="horizontal")
    compare.add_argument("--title", action="append", default=[])
    compare.add_argument("--json", action="store_true")

    animate = sub.add_parser("animate", help="Render a trajectory animation.")
    _add_common_render_args(animate, default_resolution="1920x1080")
    animate.add_argument("input")
    animate.add_argument("-o", "--output", required=True)
    animate.add_argument("--frames", type=int, default=100)
    animate.add_argument("--fps", type=int, default=24)
    animate.add_argument("--camera", choices=CAMERA_PATHS, default="orbit")
    animate.add_argument("--json", action="store_true")

    mechanism = sub.add_parser("mechanism", help="Render a reaction mechanism panel.")
    _add_common_render_args(mechanism, default_resolution="2048x1024")
    mechanism.add_argument("inputs", nargs="+")
    mechanism.add_argument("-o", "--output", required=True)
    mechanism.add_argument("--layout", choices=LAYOUTS, default="horizontal")
    mechanism.add_argument("--label", action="append", default=[])
    mechanism.add_argument("--no-arrow", action="store_true")
    mechanism.add_argument("--json", action="store_true")

    args = parser.parse_args()
    if args.command == "diagnostic":
        payload = EnvironmentChecker(ROOT).run_diagnostic()
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            _print_diagnostic(payload)
        return 0

    try:
        resolution = parse_resolution(args.resolution)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    visualizer = MolVisualizer(
        engine=args.engine,
        style=args.style,
        color_scheme=args.color_scheme,
        background=args.background,
        resolution=resolution,
    )

    if args.command == "render":
        result = visualizer.render_molecule(args.input, args.output)
    elif args.command == "compare":
        result = visualizer.compare_structures(args.inputs, args.output, titles=args.title, layout=args.layout)
    elif args.command == "animate":
        result = visualizer.animate_trajectory(args.input, args.output, frames=args.frames, fps=args.fps, camera_path=args.camera)
    elif args.command == "mechanism":
        labels = args.label or _default_mechanism_labels(len(args.inputs))
        result = visualizer.render_reaction_mechanism(args.inputs, labels, args.output, layout=args.layout, show_arrow=not args.no_arrow)
    else:
        raise AssertionError(args.command)

    if args.json:
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    elif result.ok:
        print(result.output_path)
    else:
        print(result.stderr or "; ".join(result.diagnostics), file=sys.stderr)
    return 0 if result.ok else 1


def _add_common_render_args(parser: argparse.ArgumentParser, default_resolution: str = "1024x768") -> None:
    parser.add_argument("--style", choices=STYLES, default="ball_and_stick")
    parser.add_argument("--engine", choices=ENGINES, default="xyzrender")
    parser.add_argument("--color-scheme", choices=COLOR_SCHEMES, default="cpk")
    parser.add_argument("--background", default="white")
    parser.add_argument("--resolution", default=default_resolution)


def _print_diagnostic(payload: dict) -> None:
    print(f"python: {payload['python']['executable']}")
    print(f"runtime_env: {payload['runtime'].get('env_prefix') or 'not configured'}")
    for key in ["xyzrender"]:
        item = payload[key]
        status = "ok" if item.get("available") else "missing"
        print(f"{key}: {status} {item.get('path') or ''}".rstrip())


def _default_mechanism_labels(count: int) -> list[str]:
    if count == 3:
        return ["Reactant", "Transition state", "Product"]
    return [f"Structure {index + 1}" for index in range(count)]


if __name__ == "__main__":
    raise SystemExit(main())
