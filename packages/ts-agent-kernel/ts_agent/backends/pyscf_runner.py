"""Command-line entrypoint for the bound PySCF/CF22D runtime."""

from __future__ import annotations

import argparse
import sys

from ts_agent.pyscf.runner import build_config, run_pyscf


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one TSPi PySCF/CF22D workflow")
    parser.add_argument("--xyz", required=True)
    parser.add_argument("--task", choices=("sp", "opt", "ts", "freq", "thermo", "opt_freq", "ts_freq"), required=True)
    parser.add_argument("--output-dir", default=".")
    parser.add_argument("--basis", default="def2-tzvp")
    parser.add_argument("--charge", type=int, default=0)
    parser.add_argument("--spin", type=int, default=0)
    parser.add_argument("--unit", default="angstrom")
    parser.add_argument("--verbose", type=int, default=4)
    parser.add_argument("--xc", default="CF22D")
    parser.add_argument("--grid-level", type=int, default=6)
    parser.add_argument("--conv-tol", type=float, default=1.0e-10)
    parser.add_argument("--max-cycle", type=int, default=400)
    parser.add_argument("--max-steps", type=int, default=100)
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--memory-mb", type=int, default=4000)
    parser.add_argument("--imaginary-threshold-cm", type=float, default=-20.0)
    parser.add_argument("--temperature", type=float, default=298.15)
    parser.add_argument("--pressure", type=float, default=101325.0)
    hessian_group = parser.add_mutually_exclusive_group()
    hessian_group.add_argument("--use-initial-hessian", dest="use_initial_hessian", action="store_true")
    hessian_group.add_argument("--no-use-initial-hessian", dest="use_initial_hessian", action="store_false")
    parser.set_defaults(use_initial_hessian=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        run_pyscf(build_config(args))
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_parser", "main"]
