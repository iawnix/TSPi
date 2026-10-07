"""Prepare a generic job request from installation bindings; never execute it."""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import tomllib
import uuid


def prepare(config, environment, backend, skill, xyz, arguments, python=None):
    settings = tomllib.loads(Path(config).read_text())
    target = settings['environments'][environment]
    binding = target['backends'][backend]
    command = binding['command']
    command = [command] if isinstance(command, str) else command
    if not command or any(not isinstance(x,str) or not x for x in command):
        raise ValueError('backend command must be a non-empty argv')
    if backend != 'pyscf' and len(command) != 1:
        raise ValueError('xTB/Gaussian executable binding must contain one executable')
    root=Path(__file__).resolve().parents[2]
    script=root/skill/'scripts'/'run.py'
    if not script.is_file(): raise ValueError('Skill has no installed scripts/run.py')
    # Stage only the selected Skill and its plain helper library, with intact imports.
    inputs=[{'source':str(root/skill/'scripts'),'destination':f'skills/{skill}/scripts'},
            {'source':str(root/'_shared'),'destination':'skills/_shared'},
            {'source':str(Path(xyz).resolve()),'destination':'input.xyz'}]
    interpreter = python or target.get('python')
    if backend == 'pyscf':
        python_argv = command
    elif interpreter:
        python_argv = [interpreter]
    elif target['kind'] == 'local':
        import sys
        python_argv = [sys.executable]
    else:
        raise ValueError('remote Skill scripts require an explicit --python or environment.python binding (Python >=3.10)')
    argv=[*python_argv,f'skills/{skill}/scripts/run.py','--xyz','input.xyz','--output-dir','results',*arguments]
    if backend != 'pyscf': argv.extend(['--executable',command[0]])
    activation=binding.get('activation_script')
    if activation:
        argv=['bash','-c','set -e\nsource '+shlex.quote(activation)+'\nexec "$@"','skill',*argv]
    resources={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest()
               for folder in [script.parent,root/'_shared'] for p in sorted(folder.rglob('*.py'))}
    return {'requestId':'skill_'+uuid.uuid4().hex,'command':argv,'platform':environment,'inputs':inputs,
            'environment':binding.get('environment',{}),
            'outputs':[{'path':'results/result.json','required':True,'minBytes':2,'mediaType':'application/json'},
                       {'path':'results/geometry.xyz','required':True,'minBytes':1,'mediaType':'chemical/x-xyz'}],
            'metadata':{'skill':skill,'resources_sha256':resources}}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',required=True);p.add_argument('--environment',required=True)
    p.add_argument('--backend',choices=['pyscf','xtb','gaussian'],required=True)
    p.add_argument('--skill',choices=['cf22d','xtb','gaussian'],required=True)
    p.add_argument('--python',help='target Python >=3.10 for xTB/Gaussian script wrapper')
    p.add_argument('--xyz',required=True);p.add_argument('arguments',nargs=argparse.REMAINDER)
    a=p.parse_args()
    if {'pyscf':'cf22d','xtb':'xtb','gaussian':'gaussian'}[a.backend] != a.skill:
        p.error('backend and Skill disagree')
    args=a.arguments[1:] if a.arguments[:1]==['--'] else a.arguments
    print(json.dumps(prepare(a.config,a.environment,a.backend,a.skill,a.xyz,args,a.python),indent=2))


if __name__=='__main__':main()
