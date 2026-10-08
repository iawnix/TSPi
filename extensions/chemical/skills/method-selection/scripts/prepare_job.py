"""Prepare a generic job request from installation bindings; never execute it."""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import sys
import importlib.util
import contextlib
import io
from job_runtime import config_contract
from job_runtime.config_contract import load_job_config, python_command, binding_digest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / '_shared'))
from execution_bindings import resolve_backend


def prepare(config, environment, backend, skill, xyz, arguments, python=None, work_id=None, input_gjf=None, dependencies=(), collect=()):
    settings = load_job_config(config)
    target = settings['environments'][environment]
    binding = target['backends'][backend]
    python_binding, command, submission = resolve_backend(settings, environment, backend, contract=config_contract)
    root=Path(__file__).resolve().parents[2]
    script=root/skill/'scripts'/'run.py'
    if not script.is_file(): raise ValueError('Skill has no installed scripts/run.py')
    # Stage only the selected Skill and its plain helper library, with intact imports.
    if input_gjf and (backend != 'gaussian' or xyz): raise ValueError('--input-gjf is Gaussian-only and replaces --xyz')
    source = Path(input_gjf or xyz).resolve()
    if not source.is_file(): raise ValueError(f'input file does not exist: {source}')
    input_name = 'input.gjf' if input_gjf else 'input.xyz'
    inputs=[{'source':str(root/skill/'scripts'),'destination':f'skills/{skill}/scripts'},
            {'source':str(root/'_shared'),'destination':'skills/_shared'},
            {'source':str(source),'destination':input_name}]
    dependency_hashes = {}
    extra_outputs = []
    for name in collect:
        if not name or Path(name).is_absolute() or '..' in Path(name).parts:
            raise ValueError('collected file must be relative to results')
        extra_outputs.append({'path':f'results/{name}', 'required':True, 'min_bytes':1})
    for dependency in dependencies:
        src, sep, dest = dependency.partition('=')
        if not sep or not dest or Path(dest).is_absolute() or '..' in Path(dest).parts or dest in {input_name, 'results', 'skills'} or dest.startswith(('results/', 'skills/')):
            raise ValueError('dependency must be source=relative-destination outside results/skills')
        if dest in dependency_hashes: raise ValueError('duplicate dependency destination')
        file = Path(src).resolve(); dependency_hashes[dest] = hashlib.sha256(file.read_bytes()).hexdigest()
        inputs.append({'source':str(file), 'destination':dest})
    if python is not None:
        raise ValueError('Configure a Conda python binding in job.toml; --python overrides are retired')
    python_argv = python_command(python_binding)
    reserved = {'--xyz', '--input-gjf', '--output-dir', '--executable', '--help', '-h'}
    if any(arg.split('=', 1)[0] in reserved for arg in arguments):
        raise ValueError('runner input/output/executable arguments are owned by the preparation helper')
    runner_args=['--input-gjf' if input_gjf else '--xyz',input_name,'--output-dir','results',*arguments]
    if backend != 'pyscf': runner_args.extend(['--executable',command[0]])
    # Load only the Skill's pure CLI contract, without importing scientific
    # dependencies or launching the configured target interpreter.
    module_spec = importlib.util.spec_from_file_location(f'{skill}_cli', script.with_name('cli.py'))
    cli = importlib.util.module_from_spec(module_spec); module_spec.loader.exec_module(cli)
    diagnostic = io.StringIO()
    try:
        with contextlib.redirect_stderr(diagnostic): cli.parse_arguments(runner_args)
    except SystemExit as exc:
        raise ValueError('runner_arguments_invalid: ' + diagnostic.getvalue().strip()) from exc
    argv=[*python_argv,f'skills/{skill}/scripts/run.py',*runner_args]
    activation=binding.get('activation_script')
    if activation:
        argv=['bash','-c','set -e\nsource '+shlex.quote(activation)+'\nexec "$@"','skill',*argv]
    resources={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest()
               for folder in [script.parent,root/'_shared'] for p in sorted(folder.rglob('*.py'))}
    identity = binding_digest({'environment':environment, 'backend':backend, 'skill':skill, 'arguments':arguments,
        'input_format':input_name, 'collect':sorted(set(collect)), 'resources':resources,
        'input_sha256':hashlib.sha256(source.read_bytes()).hexdigest(), 'dependencies':dependency_hashes, 'configuration':binding_digest(settings)})[7:]
    from job_runtime.inputs import content_digest
    for item in inputs:
        item['sha256'] = content_digest(Path(item['source']))
    work_id = work_id or 'work_' + identity[:48]
    return {'request_id':'skill_'+hashlib.sha256(work_id.encode()).hexdigest()[:48], 'work_id':work_id,'command':argv,'platform':environment,'inputs':inputs,
            'environment':binding.get('environment',{}),
            'outputs':[{'path':'results/result.json','required':True,'min_bytes':2,'media_type':'application/json'},
                       {'path':'results/geometry.xyz','required':not bool(input_gjf),'min_bytes':1,'media_type':'chemical/x-xyz'},
                       *([{'path':'results/gaussian.out','required':True,'min_bytes':1,'media_type':'text/plain'},
                          {'path':'results/parsed.json','required':True,'min_bytes':2,'media_type':'application/json'}] if input_gjf else []), *extra_outputs],
            'metadata':{**submission, 'skill':skill,'resources_sha256':resources, 'python_binding':python_binding, 'configuration_sha256':binding_digest(settings)}}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',required=True);p.add_argument('--environment',required=True)
    p.add_argument('--backend',choices=['pyscf','xtb','gaussian'],required=True)
    p.add_argument('--skill',choices=['cf22d','xtb','gaussian'],required=True)
    p.add_argument('--python',help=argparse.SUPPRESS)
    p.add_argument('--output',help="Save the complete request; print its job_start file reference")
    p.add_argument('--root',help="Research workspace owning the prepared reference (otherwise inferred from output path)")
    p.add_argument('--work-id',help="Explicit identity for an intentional recalculation")
    source=p.add_mutually_exclusive_group(required=True);source.add_argument('--xyz');source.add_argument('--input-gjf')
    p.add_argument('--dependency',action='append',default=[],help='Stage source=relative-destination (e.g. checkpoint)')
    p.add_argument('--collect',action='append',default=[],help='Required file relative to results, e.g. ts.chk')
    p.add_argument('arguments',nargs=argparse.REMAINDER)
    a=p.parse_args()
    if {'pyscf':'cf22d','xtb':'xtb','gaussian':'gaussian'}[a.backend] != a.skill:
        p.error('backend and Skill disagree')
    args=a.arguments[1:] if a.arguments[:1]==['--'] else a.arguments
    request = prepare(a.config,a.environment,a.backend,a.skill,a.xyz,args,a.python,a.work_id,a.input_gjf,a.dependency,a.collect)
    encoded = (json.dumps(request,indent=2)+'\n').encode()
    if a.output:
        path = Path(a.output).resolve(); path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(encoded)
        workspace = Path(a.root).expanduser().resolve() if a.root else next(
            (parent for parent in path.parents if (parent/'workspace_manifest.json').is_file()), None)
        if workspace is not None:
            from research_state.references import prepare_job
            print(json.dumps(prepare_job(workspace, {'request_file':str(path)})))
        else:
            # Standalone input preparation remains usable outside a research
            # workspace; managed references require a canonical workspace.
            print(json.dumps({'request_file':str(path),'request_sha256':hashlib.sha256(encoded).hexdigest()}))
    else:
        print(encoded.decode(),end='')


if __name__=='__main__':main()
