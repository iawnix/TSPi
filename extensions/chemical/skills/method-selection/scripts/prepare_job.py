"""Prepare a generic job request from installation bindings; never execute it."""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import sys
from job_runtime import config_contract
from job_runtime.config_contract import load_job_config, python_command, binding_digest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / '_shared'))
from execution_bindings import resolve_backend


def prepare(config, environment, backend, skill, xyz, arguments, python=None, work_id=None):
    settings = load_job_config(config)
    target = settings['environments'][environment]
    binding = target['backends'][backend]
    python_binding, command, submission = resolve_backend(settings, environment, backend, contract=config_contract)
    root=Path(__file__).resolve().parents[2]
    script=root/skill/'scripts'/'run.py'
    if not script.is_file(): raise ValueError('Skill has no installed scripts/run.py')
    # Stage only the selected Skill and its plain helper library, with intact imports.
    inputs=[{'source':str(root/skill/'scripts'),'destination':f'skills/{skill}/scripts'},
            {'source':str(root/'_shared'),'destination':'skills/_shared'},
            {'source':str(Path(xyz).resolve()),'destination':'input.xyz'}]
    if python is not None:
        raise ValueError('Configure a Conda python binding in job.toml; --python overrides are retired')
    python_argv = python_command(python_binding)
    argv=[*python_argv,f'skills/{skill}/scripts/run.py','--xyz','input.xyz','--output-dir','results',*arguments]
    if backend != 'pyscf': argv.extend(['--executable',command[0]])
    activation=binding.get('activation_script')
    if activation:
        argv=['bash','-c','set -e\nsource '+shlex.quote(activation)+'\nexec "$@"','skill',*argv]
    resources={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest()
               for folder in [script.parent,root/'_shared'] for p in sorted(folder.rglob('*.py'))}
    identity = binding_digest({'environment':environment, 'backend':backend, 'arguments':arguments,
        'input_sha256':hashlib.sha256(Path(xyz).read_bytes()).hexdigest(), 'configuration':binding_digest(settings)})[7:]
    work_id = work_id or 'work_' + identity[:48]
    return {'requestId':'skill_'+hashlib.sha256(work_id.encode()).hexdigest()[:48], 'workId':work_id,'command':argv,'platform':environment,'inputs':inputs,
            'environment':binding.get('environment',{}),
            'outputs':[{'path':'results/result.json','required':True,'minBytes':2,'mediaType':'application/json'},
                       {'path':'results/geometry.xyz','required':True,'minBytes':1,'mediaType':'chemical/x-xyz'}],
            'metadata':{**submission, 'skill':skill,'resources_sha256':resources, 'python_binding':python_binding, 'configuration_sha256':binding_digest(settings)}}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',required=True);p.add_argument('--environment',required=True)
    p.add_argument('--backend',choices=['pyscf','xtb','gaussian'],required=True)
    p.add_argument('--skill',choices=['cf22d','xtb','gaussian'],required=True)
    p.add_argument('--python',help=argparse.SUPPRESS)
    p.add_argument('--output',help="Save the complete request; print its job_start file reference")
    p.add_argument('--work-id',help="Explicit identity for an intentional recalculation")
    p.add_argument('--xyz',required=True);p.add_argument('arguments',nargs=argparse.REMAINDER)
    a=p.parse_args()
    if {'pyscf':'cf22d','xtb':'xtb','gaussian':'gaussian'}[a.backend] != a.skill:
        p.error('backend and Skill disagree')
    args=a.arguments[1:] if a.arguments[:1]==['--'] else a.arguments
    request = prepare(a.config,a.environment,a.backend,a.skill,a.xyz,args,a.python,a.work_id)
    encoded = (json.dumps(request,indent=2)+'\n').encode()
    if a.output:
        path = Path(a.output).resolve(); path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(encoded)
        print(json.dumps({'requestFile':str(path),'requestSha256':hashlib.sha256(encoded).hexdigest()}))
    else:
        print(encoded.decode(),end='')


if __name__=='__main__':main()
