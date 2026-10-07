"""Run and validate GFN2-xTB opt/SP using the restored xTB parser."""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / '_shared'))
from science import prepare, read_xyz, digest, finite_energy, finish, write_json
from parser import parse_xtb_artifacts


def validate(summary, task):
    if str(summary.get('method', '')).upper().replace('-', '') != 'GFN2XTB':
        raise ValueError('output does not identify GFN2-xTB')
    if not summary['execution_completed'] or not summary['scc_converged'] or summary['missing_artifacts']:
        raise ValueError('xTB did not terminate with converged SCC and required outputs')
    if task == 'opt' and not summary['optimization_converged']:
        raise ValueError('xTB optimization did not converge')
    return finite_energy(summary['total_energy_hartree'])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--xyz', required=True)
    p.add_argument('--task', choices=['opt', 'sp', 'opt-sp'], required=True)
    p.add_argument('--executable', required=True, help='configured xTB executable, resolved after activation')
    p.add_argument('--output-dir', required=True)
    p.add_argument('--charge', type=int, default=0)
    p.add_argument('--spin', type=int, default=0, help='number of unpaired electrons')
    p.add_argument('--opt-level', default='tight', choices=['normal','tight','verytight'])
    a = p.parse_args()
    out = None
    try:
        if a.spin < 0: raise ValueError('spin must be nonnegative')
        out, atoms, result = prepare(a, 'GFN2-xTB')
        executable = shutil.which(a.executable)
        if not executable: raise ValueError('configured xTB executable unavailable after activation')
        geometry = out / 'input.xyz'
        for task in (['opt','sp'] if a.task == 'opt-sp' else [a.task]):
            step = out / task; step.mkdir()
            shutil.copyfile(geometry, step / 'input.xyz')
            command = [executable, 'input.xyz', '--gfn', '2', '--chrg', str(a.charge), '--uhf', str(a.spin)]
            command += ['--opt', a.opt_level] if task == 'opt' else ['--sp']
            write_json(step / 'command.json', command)
            with (step/'xtb.out').open('w') as log:
                run = subprocess.run(command, cwd=step, stdout=log, stderr=subprocess.STDOUT)
            if run.returncode: raise RuntimeError(f'xTB {task} exited {run.returncode}')
            parsed = parse_xtb_artifacts(task, {p.name:p for p in step.iterdir() if p.is_file()})
            write_json(step/'parsed.json', parsed)
            energy = validate(parsed['summary'], task)
            if task == 'opt':
                geometry = step/'xtbopt.xyz'
                if [x[0] for x in read_xyz(geometry)] != [x[0] for x in atoms]:
                    raise ValueError('optimized geometry atom order changed')
            result['steps'].append({'task':task, 'input_sha256':digest(step/'input.xyz'),
                'energy_hartree':energy, 'geometry_sha256':digest(geometry), 'summary':parsed['summary']})
        shutil.copyfile(geometry, out/'geometry.xyz')
        finish(out, result, __file__)
        return 0
    except Exception as exc:
        if out is not None: finish(out, result, __file__, exc)
        print(f'{type(exc).__name__}: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__': raise SystemExit(main())
