"""Pure argument contract for rendering a supplied XYZ geometry."""
import argparse


def parse_arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--xyz', required=True)
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--style', choices=('default', 'flat', 'paton', 'skeletal', 'tube'), default='default')
    parser.add_argument('--size', type=int, default=800, help='SVG canvas size; PNG dimensions depend on renderer scaling')
    parser.add_argument('--charge', type=int, default=0)
    parser.add_argument('--multiplicity', type=int, default=1)
    args = parser.parse_args(argv)
    if not 64 <= args.size <= 4096 or args.multiplicity < 1:
        parser.error('size must be 64..4096 canvas units and multiplicity must be positive')
    return args
