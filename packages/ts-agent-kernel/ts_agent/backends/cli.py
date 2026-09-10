"""Backend command-line entrypoints."""

from __future__ import annotations

import argparse

from .gaussian import parse_result_main, prepare_input_main


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ts_backend")
    sub = parser.add_subparsers(dest="backend", required=True)
    gaussian = sub.add_parser("gaussian", help="Gaussian backend helpers.")
    gaussian.add_argument("gaussian_args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.backend == "gaussian":
        return _gaussian_main(args.gaussian_args)
    raise AssertionError(args.backend)


def _gaussian_main(argv: list[str]) -> int:
    if not argv or argv[0] in {"-h", "--help"}:
        parser = argparse.ArgumentParser(prog="ts_backend gaussian")
        parser.add_argument("command", choices=["prepare", "parse"])
        parser.print_help()
        return 0
    command, rest = argv[0], argv[1:]
    if command == "prepare":
        return prepare_input_main(rest)
    if command == "parse":
        return parse_result_main(rest)
    print(f"unknown Gaussian command: {command}", flush=True)
    return 2
