"""File and validation helpers for scientific Skill scripts; no host dependency."""
from pathlib import Path
import hashlib
import json
import math
import shutil
import sys
from xyz import read_xyz, validate_electronic_state


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n')
    temporary.replace(path)


def finite_energy(value):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValueError('missing or non-finite electronic energy')
    return value


def prepare(args, method, basis=None):
    source = Path(args.xyz).resolve()
    atoms = read_xyz(source)
    validate_electronic_state(atoms, args.charge, args.multiplicity)
    out = Path(args.output_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    if any(out.iterdir()):
        raise ValueError('output directory must be empty; use a new attempt directory')
    shutil.copyfile(source, out / 'input.xyz')
    result = new_result(args, method, basis, source)
    return out, atoms, result


def new_result(args, method, basis, source):
    return {'schema_version': 'science-result/2', 'method': method, 'basis': basis,
            'charge': args.charge, 'multiplicity': args.multiplicity, 'input_sha256': digest(source),
            'geometry_unit': 'angstrom', 'energy_unit': 'hartree', 'steps': [],
            'checks_passed': False, 'scientific_validation': 'not_assessed'}


def provenance(script):
    root = Path(script).resolve().parent
    shared = Path(__file__).resolve().parent
    return {str(p.relative_to(base)): digest(p) for base in [root.parent.parent] for folder in [root, shared]
            for p in sorted(folder.rglob('*.py'))}


def finish(out, result, script, error=None):
    result['checks_passed'] = error is None
    result['scripts'] = provenance(script)
    receipt = Path(sys.prefix) / 'research-agent-environment.json'
    result['runtime'] = {'python': sys.executable, 'prefix': sys.prefix, 'version': sys.version,
                         'environment_receipt': json.loads(receipt.read_text()) if receipt.is_file() else None}
    if error is not None:
        result['error'] = {'type': type(error).__name__, 'message': str(error)}
    write_json(out / 'result.json', result)
