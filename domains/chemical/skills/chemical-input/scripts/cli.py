"""Pure chemical input CLI contract; scientific imports belong to the Job."""
import argparse
from pathlib import Path


def parse_arguments(argv=None):
    parser = argparse.ArgumentParser(description="Prepare chemical inputs", allow_abbrev=False)
    parser.add_argument('--config', help='Absolute installation name-resolver TOML')
    parser.add_argument('--output', required=True)
    sub = parser.add_subparsers(dest='command', required=True)
    names = sub.add_parser('resolve', allow_abbrev=False); names.add_argument('--name', required=True); names.add_argument('--lookup-name')
    check = sub.add_parser('inspect', allow_abbrev=False); check.add_argument('--smiles', required=True)
    seed = sub.add_parser('seed', allow_abbrev=False); seed.add_argument('--smiles', required=True)
    seed.add_argument('--charge', type=int, required=True); seed.add_argument('--multiplicity', type=int, required=True)
    seed.add_argument('--output-dir', type=Path, required=True); seed.add_argument('--enumerate-stereo', action='store_true')
    mapping = sub.add_parser('reaction', allow_abbrev=False); mapping.add_argument('--smiles', required=True)
    mapping.add_argument('--transformation', type=Path, help='JSON declaring diels_alder or explicit bond/hydrogen changes')
    compare = sub.add_parser('compare', allow_abbrev=False)
    compare.add_argument('--target', type=Path, required=True)
    compare.add_argument('--actual', type=Path, required=True)
    compare.add_argument('--actual-format', choices=['structure', 'xyz'], default='structure')
    compare.add_argument('--charge', type=int, help='Explicit actual charge required for XYZ inference')
    return parser.parse_args(argv)
