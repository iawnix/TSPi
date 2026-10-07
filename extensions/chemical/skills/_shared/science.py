"""File and validation helpers for scientific Skill scripts; no host dependency."""
from pathlib import Path
import hashlib
import json
import math
import shutil


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n')
    temporary.replace(path)


def read_xyz(path):
    lines = Path(path).read_text().splitlines()
    count = int(lines[0])
    if count < 1 or len(lines) < count + 2 or any(x.strip() for x in lines[count+2:]):
        raise ValueError('expected exactly one complete XYZ structure')
    atoms = []
    for line in lines[2:count+2]:
        parts = line.split()
        if len(parts) != 4 or not parts[0].isalpha():
            raise ValueError('invalid XYZ atom')
        xyz = tuple(float(x) for x in parts[1:])
        if not all(math.isfinite(x) for x in xyz):
            raise ValueError('non-finite XYZ coordinates')
        atoms.append((parts[0], *xyz))
    return atoms


def finite_energy(value):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValueError('missing or non-finite electronic energy')
    return value


def prepare(args, method, basis=None):
    source = Path(args.xyz).resolve()
    atoms = read_xyz(source)
    out = Path(args.output_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    if any(out.iterdir()):
        raise ValueError('output directory must be empty; use a new attempt directory')
    shutil.copyfile(source, out / 'input.xyz')
    result = {'schema_version': 'science-result/1', 'method': method, 'basis': basis,
              'charge': args.charge, 'spin': args.spin, 'input_sha256': digest(source),
              'geometry_unit': 'angstrom', 'energy_unit': 'hartree', 'steps': [], 'validated': False}
    return out, atoms, result


def provenance(script):
    root = Path(script).resolve().parent
    shared = Path(__file__).resolve().parent
    return {str(p.relative_to(base)): digest(p) for base in [root.parent.parent] for folder in [root, shared]
            for p in sorted(folder.rglob('*.py'))}


def finish(out, result, script, error=None):
    result['validated'] = error is None
    result['scripts'] = provenance(script)
    if error is not None:
        result['error'] = {'type': type(error).__name__, 'message': str(error)}
    write_json(out / 'result.json', result)
