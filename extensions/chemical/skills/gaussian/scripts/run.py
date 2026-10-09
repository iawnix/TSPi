"""Explicit Gaussian optimization/SP with method and convergence validation."""
import argparse
from pathlib import Path
import re
import shutil
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / '_shared'))
from science import prepare, read_xyz, digest, finite_energy, finish, write_json
from gaussian_io import write_gjf, parse_log, write_xyz
from cli import parse_arguments


def validate(summary, task, method, basis):
    compact = re.sub(r'\s+', '', str(summary.get('gaussian_route') or '')).lower()
    if f'{method}/{basis}'.lower() not in compact:
        raise ValueError('Gaussian output route does not match requested method/basis')
    if not summary['normal_termination'] or summary['error_termination']:
        raise ValueError('Gaussian did not terminate normally')
    if task == 'opt' and not (summary['stationary_point_found'] and summary['final_convergence_satisfied']):
        raise ValueError('Gaussian optimization lacks converged stationary point evidence')
    return finite_energy(summary['electronic_energy_hartree'])


def main():
    a = parse_arguments(); out = None
    try:
        if a.multiplicity < 1 or a.threads < 1 or a.memory_mb < 1: raise ValueError('invalid multiplicity/resources')
        if not all(re.fullmatch(r'[A-Za-z0-9+*(),._-]+', v) for v in [a.method,a.basis]):
            raise ValueError('method/basis must be single Gaussian route tokens')
        if a.input_gjf:
            from input_job import run_input
            return run_input(a)
        out, atoms, result=prepare(a,a.method,a.basis)
        executable=shutil.which(a.executable)
        if not executable: raise ValueError('configured Gaussian executable unavailable after activation')
        geometry=out/'input.xyz'
        for task in (['opt','sp'] if a.task=='opt-sp' else [a.task]):
            step=out/task; step.mkdir()
            shutil.copyfile(geometry,step/'input.xyz')
            route=f'#p {a.method}/{a.basis} '+('Opt=Tight' if task=='opt' else 'SP')+' SCF=Tight Int=UltraFine'
            write_gjf(step/'input.gjf','Skill calculation',read_xyz(geometry),route,a.charge,a.multiplicity,a.threads,f'{a.memory_mb}MB','wavefunction.chk',[])
            with (step/'input.gjf').open('rb') as source, (step/'gaussian.out').open('wb') as log:
                run=subprocess.run([executable],cwd=step,stdin=source,stdout=log,stderr=subprocess.STDOUT)
            if run.returncode: raise RuntimeError(f'Gaussian {task} exited {run.returncode}')
            parsed=parse_log(step/'gaussian.out',expected_route=route)
            write_json(step/'parsed.json',parsed)
            energy=validate(parsed['summary'],task,a.method,a.basis)
            if task=='opt':
                if [x[0] for x in parsed['atoms']] != [x[0] for x in atoms]:
                    raise ValueError('optimized geometry missing or atom order changed')
                geometry=step/'geometry.xyz'; write_xyz(geometry,parsed['atoms'],'Optimized geometry; angstrom')
            result['steps'].append({'task':task,'input_sha256':digest(step/'input.xyz'),
                'energy_hartree':energy,'geometry_sha256':digest(geometry),'summary':parsed['summary']})
        shutil.copyfile(geometry,out/'geometry.xyz'); finish(out,result,__file__)
        return 0
    except Exception as exc:
        if out is not None: finish(out,result,__file__,exc)
        print(f'{type(exc).__name__}: {exc}',file=sys.stderr); return 1


if __name__=='__main__': raise SystemExit(main())
