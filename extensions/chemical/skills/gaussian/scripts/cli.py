"""Pure argument contract shared by request preparation and execution."""
import argparse
import re

def parse_arguments(argv=None):
    p = argparse.ArgumentParser(description="Gaussian explicit input or XYZ opt/SP", allow_abbrev=False)
    source = p.add_mutually_exclusive_group(required=True)
    source.add_argument('--xyz')
    source.add_argument('--input-gjf', help='Run an explicit Gaussian input, including TS/Freq/IRC/QST/scan routes')
    p.add_argument('--task', choices=['opt','sp','opt-sp'])
    p.add_argument('--validation', choices=['none','opt','sp','frequency','minimum','saddle','irc'], default='none')
    p.add_argument('--executable', required=True)
    p.add_argument('--output-dir', required=True)
    p.add_argument('--method', default='M062X')
    p.add_argument('--basis', default='6-31G**')
    p.add_argument('--charge', type=int, default=0)
    p.add_argument('--multiplicity', type=int, default=1, help='spin multiplicity 2S+1')
    p.add_argument('--threads', type=int, default=1)
    p.add_argument('--memory-mb', type=int, default=2000)
    a=p.parse_args(argv)
    if a.input_gjf and a.task: p.error('--task is only for the XYZ shortcut')
    if a.xyz and not a.task: p.error('--xyz requires --task')
    if a.xyz and a.validation != 'none': p.error('--validation requires --input-gjf; XYZ uses --task validation')
    if a.multiplicity < 1 or a.threads < 1 or a.memory_mb < 1: p.error("invalid multiplicity/resources")
    if not all(re.fullmatch(r"[A-Za-z0-9+*(),._-]+", v) for v in [a.method,a.basis]):
        p.error("method/basis must be single Gaussian route tokens")
    return a
