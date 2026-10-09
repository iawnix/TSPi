"""Render supplied coordinates; images do not establish scientific validity."""
import hashlib
import importlib.metadata
import json
from pathlib import Path
import sys

from render_cli import parse_arguments


def main():
    args = parse_arguments()
    source = Path(args.xyz).resolve(strict=True)
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=False)
    from xyzrender.cli import main as render
    for extension in ('svg', 'png'):
        sys.argv = ['xyzrender', str(source), '--config', args.style, '--canvas-size', str(args.size),
                    '--charge', str(args.charge), '--multiplicity', str(args.multiplicity),
                    '--output', str(output / ('geometry.' + extension))]
        render()
    (output/'render.json').write_text(json.dumps({
        'schema_version': 'molecular-render/1',
        'input_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
        'renderer': {'name': 'xyzrender', 'version': importlib.metadata.version('xyzrender')},
        'style': args.style, 'size': args.size, 'charge': args.charge, 'multiplicity': args.multiplicity,
        'files': ['geometry.svg', 'geometry.png'],
    }, indent=2) + '\n')


if __name__ == '__main__':
    main()
