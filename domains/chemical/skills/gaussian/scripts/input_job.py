"""Run an explicit Gaussian input without prescribing a research sequence."""
import hashlib
import re
import shutil
import subprocess
from pathlib import Path, PurePosixPath

from gaussian_io import parse_log, parse_irc_log, write_irc_parse_artifacts, write_xyz
from science import digest, write_json, finite_energy, new_result, finish


def local_reference(value):
    path = PurePosixPath(value.strip())
    if path.is_absolute() or '..' in path.parts or not path.parts or '\\' in value:
        raise ValueError('Gaussian file references must be relative staged paths')
    return str(path)


def inspect_input(path, method, basis, charge, multiplicity, threads, memory_mb):
    text = Path(path).read_text()
    sections = re.split(r'(?im)^\s*--Link1--\s*$', text)
    references, checkpoints, routes = set(), set(), []
    for section in sections:
        preceding_checkpoints = set(checkpoints)
        route_match = re.search(r'(?ms)^\s*(#[^\n]*(?:\n[^\n]+)*?)\n\s*\n', section)
        if not route_match:
            raise ValueError('Gaussian input needs a route section followed by a blank line')
        route = route_match.group(1).strip(); routes.append(route)
        coordinate = r'(?im)^\s*(?:[A-Z][a-z]?|\d+)\s+(?:[-+]?\d+(?:\.\d*)?(?:[EeDd][-+]?\d+)?\s+){2}[-+]?\d+(?:\.\d*)?(?:[EeDd][-+]?\d+)?\s*$'
        title = section[route_match.end():].split('\n\n', 1)[0]
        if re.search(coordinate, route) or re.search(coordinate, title):
            raise ValueError('Gaussian coordinate record in route/title section; restore blank section boundaries')
        if f'{method}/{basis}'.lower() not in re.sub(r'\s+', '', route).lower():
            raise ValueError('every Gaussian link must explicitly match the requested method/basis')
        cpus = re.findall(r'(?im)^\s*%nproc(?:shared)?\s*=\s*(\d+)\s*$', section)
        if len(cpus) != 1 or int(cpus[0]) != threads:
            raise ValueError('every Gaussian link must declare the requested %nprocshared')
        memory = re.findall(r'(?im)^\s*%mem\s*=\s*(\d+)\s*(MB|GB)\s*$', section)
        if len(memory) != 1 or int(memory[0][0]) * (1024 if memory[0][1].upper() == 'GB' else 1) != memory_mb:
            raise ValueError('every Gaussian link must declare the requested memory in MB or GB')
        headers = re.findall(r'(?m)^\s*(-?\d+)\s+(\d+)\s*$', section[route_match.end():])
        if not headers and not re.search(r'geom\s*=\s*\(?allcheck', route, re.I):
            raise ValueError('missing charge/multiplicity header')
        if any((int(c), int(m)) != (charge, multiplicity) for c, m in headers):
            raise ValueError('input charge/multiplicity differs from request')
        for key, value in re.findall(r'(?im)^\s*%(\w+)\s*=\s*(.*?)\s*$', section):
            key = key.lower()
            if key in {'chk', 'oldchk'}:
                ref = local_reference(value)
                if key == 'oldchk' and ref not in checkpoints: references.add(ref)
                if key == 'chk': checkpoints.add(ref)
                if key == 'chk' and re.search(r'(?:geom|guess)\s*=\s*\(?(?:allcheck|check|read)', route, re.I) and ref not in preceding_checkpoints and not re.search(r'(?im)^\s*%oldchk\s*=', section):
                    references.add(ref)
            elif key not in {'mem', 'nproc', 'nprocshared', 'nosave'}:
                raise ValueError(f'unsupported Link 0 directive %{key}; use staged chk/oldchk, mem and nprocshared')
        for ref in re.findall(r'(?m)^\s*@([^\s]+)\s*$', section): references.add(local_reference(ref))
        if re.search(r'\b(external|include)\s*=', route, re.I):
            raise ValueError('external executable and route include directives are unsupported')
    return {'routes': routes, 'references': sorted(references), 'checkpoints': sorted(checkpoints)}


def run_input(args):
    source = Path(args.input_gjf).resolve()
    checked = inspect_input(source, args.method, args.basis, args.charge, args.multiplicity, args.threads, args.memory_mb)
    out = Path(args.output_dir).resolve(); out.mkdir(parents=True, exist_ok=True)
    if any(out.iterdir()): raise ValueError('output directory must be empty')
    shutil.copyfile(source, out/'input.gjf')
    for name in checked['references']:
        file = source.parent/name
        if not file.is_file(): raise ValueError(f'missing staged Gaussian dependency: {name}')
        target = out/name; target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(file, target)
    result = new_result(args, args.method, args.basis, source)
    result.update(normal_termination=False, validation_requested=args.validation, input=checked)
    result.update(execution_status='not_started', parsing={'status': 'not_run'},
                  check_status='not_assessed')
    error = None
    stage = 'execution'
    try:
        executable = shutil.which(args.executable)
        if not executable: raise ValueError('configured Gaussian executable unavailable after activation')
        with (out/'input.gjf').open('rb') as inp, (out/'gaussian.out').open('wb') as log:
            process = subprocess.run([executable], cwd=out, stdin=inp, stdout=log, stderr=subprocess.STDOUT)
        result['program_returncode'] = process.returncode
        result['execution_status'] = 'succeeded' if process.returncode == 0 else 'failed'
        stage = 'parsing'
        parsed = parse_log(out/'gaussian.out', expected_route=checked['routes'][-1])
        write_json(out/'parsed.json', parsed)
        result['parsing']['status'] = 'completed'
        summary = parsed['summary']; result['normal_termination'] = summary['normal_termination'] and not summary['error_termination']
        if process.returncode or not result['normal_termination']:
            result['execution_status'] = 'failed'
            stage = 'execution'
            raise ValueError('Gaussian execution did not finish normally')
        stage = 'checks'
        if not summary['route_expectation'].get('matched'):
            raise ValueError('Gaussian route readback differs from the supplied input')
        energy = finite_energy(summary['electronic_energy_hartree'])
        result['steps'].append({'task': args.validation, 'energy_hartree': energy, 'summary': summary})
        if parsed['atoms']: write_xyz(out/'geometry.xyz', parsed['atoms'], 'Gaussian final geometry')
        if args.validation in {'opt', 'saddle'} and not (summary['stationary_point_found'] and summary['final_convergence_satisfied']):
            raise ValueError('missing converged stationary point evidence')
        if args.validation in {'frequency', 'minimum', 'saddle'}:
            if not summary['frequency_count']: raise ValueError('missing final frequency evidence')
            expected = {'minimum': 0, 'saddle': 1}.get(args.validation)
            if expected is not None and summary['imaginary_frequency_count'] != expected:
                raise ValueError(f'expected {expected} imaginary frequencies')
        if args.validation == 'irc':
            stage = 'parsing'
            irc = parse_irc_log(out/'gaussian.out'); write_irc_parse_artifacts(irc, out, 'gaussian', 'gaussian.out')
            stage = 'checks'
            result['irc'] = irc['summary']
            if not irc['points'] or not irc['atoms']: raise ValueError('IRC path/endpoint evidence missing')
        # Numeric checks do not establish mode direction, basin identity or a mechanism.
        result['limitations'] = ['Inspect mode vectors, route readback and endpoint identities before scientific claims. Normal termination alone is not validation.']
        result['check_status'] = 'satisfied'
        return_code = 0
    except Exception as exc:
        error = exc
        result['failure_stage'] = stage
        if stage == 'parsing':
            result['parsing'] = {'status': 'failed', 'exception_type': type(exc).__name__}
        elif stage == 'checks':
            result['check_status'] = 'not_satisfied'
        else:
            result['execution_status'] = 'failed'
        return_code = 1
    finish(out, result, __file__, error)
    return return_code
