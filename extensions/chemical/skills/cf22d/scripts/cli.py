"""Pure argument contract shared by request preparation and execution."""
import argparse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one TSPi PySCF/CF22D workflow", allow_abbrev=False)
    parser.add_argument("--xyz", required=True)
    parser.add_argument("--task", choices=("sp", "opt", "ts", "freq", "thermo", "opt_freq", "ts_freq", "opt-sp"), required=True)
    parser.add_argument("--output-dir", default=".")
    parser.add_argument("--basis", default="def2-tzvp")
    parser.add_argument("--charge", type=int, default=0)
    parser.add_argument("--spin", type=int, default=0)
    parser.add_argument("--unit", choices=("angstrom",), default="angstrom")
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


def parse_arguments(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.xc.upper() != "CF22D": parser.error("CF22D Skill only permits xc=CF22D")
    if args.spin < 0 or args.threads < 1 or args.memory_mb < 1: parser.error("invalid spin/resources")
    return args
