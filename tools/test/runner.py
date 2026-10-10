#!/usr/bin/env python3
"""One private, isolated and auditable test entrypoint."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import tempfile
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from tools.test import environment
from tools.test.manifest import audit,load_manifest,suite_paths
from tools.test.supervisor import Supervisor,alive,reap,write_json

DEFAULT_ROOT = ROOT / 'local_debug'
DETERMINISTIC = ['static','fast','node-fast','integration','native-pi','package','source','system-services']


def source_files(root: Path) -> list[Path]:
    result = subprocess.run(['git','ls-files','--cached','--others','--exclude-standard','-z'],cwd=root,capture_output=True,check=True)
    paths = [Path(os.fsdecode(value)) for value in result.stdout.split(b'\0') if value]
    if any(path.parts[0] == 'local_debug' for path in paths):
        raise RuntimeError('Private local_debug is tracked; refusing source capture')
    return sorted({path for path in paths if (root / path).is_file() and not any(part in {'node_modules','__pycache__','.pytest_cache'} for part in path.parts)})


def digest_source(root: Path, files: list[Path]) -> str:
    digest = hashlib.sha256()
    for relative in files:
        digest.update(str(relative).encode()+b'\0')
        digest.update((root / relative).read_bytes())
    return digest.hexdigest()


def changes(base: str | None) -> list[str]:
    command = ['git','diff','--name-only','-z',base or 'HEAD']
    changed = subprocess.check_output(command,cwd=ROOT).split(b'\0')
    changed += subprocess.check_output(['git','ls-files','--others','--exclude-standard','-z'],cwd=ROOT).split(b'\0')
    return sorted({os.fsdecode(path) for path in changed if path})


def select(args) -> tuple[list[str],list[dict]]:
    if args.command=='phone': return ['phone'],[{'reason':'explicit local Phone contract validation'}]
    if args.command in DETERMINISTIC: return [args.command],[{'reason':'explicit suite'}]
    if args.command=='verify': return DETERMINISTIC.copy(),[{'reason':'full deterministic validation'}]
    if args.command=='release': return ['release'],[{'reason':'accept the specified complete package bytes'}]
    if args.files:
        chosen=[]
        for name in DETERMINISTIC:
            if name == 'source': continue
            owned={str(Path(path).relative_to(ROOT)) for path in suite_paths(name)}
            if any(path in owned or any(value.startswith(path.rstrip('/')+'/') for value in owned) for path in args.files): chosen.append(name)
        if not chosen: raise ValueError('No suite owns the requested files')
        return ['static',*chosen],[{'reason':'explicit files','files':args.files}]
    scopes = args.scope.split(',') if args.scope else []
    paths = changes(args.base) if args.changed else []
    selected={'static','fast','node-fast'}
    reasons=[]
    rules=[
        (('docs/','README','LICENSE'),[], 'documentation'),
        (('backend/src/research_agent/research/','research'),['integration','native-pi'],'research behavior'),
        (('backend/src/research_agent/jobs/','backend/src/research_agent/artifacts/','jobs','artifacts'),['integration','native-pi'],'scientific lifecycle'),
        (('apps/agent/pi/','apps/agent/tools/','pi','tools'),['integration','native-pi','source'],'Pi and tool boundary'),
        (('apps/agent/','packages/link/','services/relay/','host','transport','terminal'),['integration','native-pi','source'],'product integration'),
        (('skills/','domains/','prompts/','skills'),['integration','native-pi'],'resources and execution declarations'),
    ]
    if not paths and not scopes:
        return DETERMINISTIC.copy(),[{'reason':'no bounded change scope; full validation'}]
    for path in paths+scopes:
        matches=[(suites,reason) for prefixes,suites,reason in rules if path.startswith(prefixes)]
        if matches:
            suites,reason=matches[0]
            selected.update(suites)
        else:
            selected.update(DETERMINISTIC)
            reason='unknown/shared/build/test infrastructure change expands to all deterministic suites'
        reasons.append({'path':path,'reason':reason})
    return [name for name in DETERMINISTIC if name in selected],reasons


def create_run(root: Path, plan: list[str], reasons: list[dict], replay: Path | None = None) -> tuple[Path,dict]:
    capture_started=time.monotonic()
    run_id=time.strftime('%m%d%H%M%S')+'-'+uuid.uuid4().hex[:6]
    run=root / 'runs' / run_id
    for name in ('source','install','workspaces','logs','report','cache','config','config/home','data'):
        (run/name).mkdir(parents=True,exist_ok=True)
    (root/'t').mkdir(exist_ok=True)
    temporary_root=Path(tempfile.mkdtemp(prefix='',dir=root/'t'))
    (run/'tmp').symlink_to(temporary_root,target_is_directory=True)
    (root/'s').mkdir(exist_ok=True)
    while True:
        socket_root=root/'s'/uuid.uuid4().hex[:4]
        try:
            socket_root.mkdir()
            break
        except FileExistsError:
            continue
    if len(str(socket_root).encode())+64>107: raise ValueError('Test root is too long for Pi backend Unix sockets')
    (run/'sockets').symlink_to(socket_root,target_is_directory=True)
    source_root=replay / 'source' if replay else ROOT
    if replay:
        files=[path.relative_to(source_root) for path in source_root.rglob('*') if path.is_file() and not {'node_modules','.git'}.intersection(path.parts)]
    else: files=source_files(ROOT)
    digest=digest_source(source_root,files)
    for relative in files:
        source=source_root/relative
        if source.is_symlink() and not source.resolve().is_relative_to(source_root):
            raise RuntimeError('Source snapshot contains an external symlink')
        target=run/'source'/relative
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(source,target)
    if digest_source(source_root,files) != digest: raise RuntimeError('Source changed during capture; retry after edits settle')
    snapshot=run/'source'
    if digest_source(snapshot,files)!=digest: raise RuntimeError('Captured source bytes do not match the recorded source digest')
    for command in (['git','init','--quiet'],['git','add','--all','--force'],['git','-c','user.name=Local Test','-c','user.email=local@test.invalid','-c','commit.gpgsign=false','commit','--quiet','-m','Isolated test snapshot']):
        subprocess.run(command,cwd=snapshot,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    dirty=bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT))
    record={'dirty':dirty,'schema_version':'coragent-test-run/1','run_id':run_id,'socket_root':str(socket_root),'temporary_root':str(temporary_root),'source_sha256':digest,'commit':commit,
            'plan':plan,'selection':reasons,'seed':args_seed(),'created':time.time(),'capture_seconds':round(time.monotonic()-capture_started,3),'status':'running',
            'replay_of':replay.name if replay else None,'external':'not-authorized','results':[]}
    write_json(run/'run.json',record)
    return run,record


def args_seed() -> int:
    return int.from_bytes(os.urandom(4),'big')


def child_environment(root: Path, run: Path, dependencies: dict[str,Path]) -> dict[str,str]:
    # Do not inherit provider credentials, user plugins, Python paths or agents.
    env={name:os.environ[name] for name in ('PATH','LANG','LC_ALL','TERM','CI','GITHUB_ACTIONS','CORAGENT_TEST_CONDA') if name in os.environ}
    env.update({'HOME':str(run/'config/home'),'CORAGENT_HOST_ENV_ROOT':str(run/'install/host-envs'),'PYTHONNOUSERSITE':'1','PYTHONDONTWRITEBYTECODE':'1','PYTHONPATH':str(run/'source/backend/src')+os.pathsep+str(run/'source'),
        'TMPDIR':str((run/'tmp').resolve()),'XDG_CONFIG_HOME':str(run/'config'),'XDG_CACHE_HOME':str(run/'cache'),
        'XDG_DATA_HOME':str(run/'data'),'XDG_RUNTIME_DIR':str((run/'sockets').resolve()),
        'CORAGENT_TEST_SOCKET_ROOT':str((run/'sockets').resolve()),
        'CORAGENT_TEST_ENV_ROOT':str(root),'CORAGENT_TEST_ROOT':str((run/'tmp').resolve()),
        'CORAGENT_TEST_RUN_ROOT':str(run),'CORAGENT_TEST_DEPENDENCIES':json.dumps([str(path) for path in dependencies.values() if (path/'.prepared.json').is_file()]),'CORAGENT_PYTHON':str(dependencies['python']/'bin/python'),
        'CORAGENT_TEST_PI_RUNTIME_ROOT':str(dependencies['pi']),'CORAGENT_PI_RUNTIME_ROOT':str(dependencies['pi']),
        'PI_CODING_AGENT_DIR':str(run/'config/pi'),'PI_AGENT_DIR':str(run/'config/pi'),
        'npm_config_cache':str(root/'cache/npm'),'npm_config_offline':'true','PIP_CACHE_DIR':str(root/'cache/pip'),
        'CONDA_PKGS_DIRS':str(root/'cache/conda'),'OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1'})
    env['PATH']=str(dependencies['python']/'bin')+os.pathsep+str(dependencies['node']/'node_modules/.bin')+os.pathsep+env.get('PATH','/usr/bin:/bin')
    return env


def command_for(name: str, run: Path, dependencies: dict[str,Path], extra: list[str], files: list[str], workers: int) -> list[str]:
    source=run/'source'
    selected=load_manifest(source)['suites'][name]
    python=str(dependencies['python']/'bin/python')
    node=shutil.which('node')
    paths=suite_paths(name,source)
    if files: paths=[path for path in paths if any(str(Path(path).relative_to(source)) == value or str(Path(path).relative_to(source)).startswith(value.rstrip('/')+'/') for value in files)]
    kind=selected['kind']
    if kind=='flutter': return [python,str(source/'tools/test/phone.py'),*extra]
    if kind in ('pytest','systemd'):
        return [python,str(source/'tools/test/pytest_lane.py'),'--name',name,'--workers',str(workers),'--files',*paths,'--',*extra]
    if kind in ('node','node-native'):
        imports=['--import',str(dependencies['pi']/'packages/coding-agent/src/experimental/source-resolver.ts')] if kind=='node-native' else []
        return [node,*imports,'--test',f'--test-concurrency={min(workers,2) if kind=="node-native" else workers}','--test-reporter=tap',*extra,*paths]
    if kind=='pytest-managed':
        return [python,str(source/'tools/test/installed.py'),'--workers',str(workers),'--files',*paths,'--',*extra]
    if kind=='package-check': return [python,str(source/'scripts/check_package.py'),*extra]
    if kind=='static': return [python,str(source/'tools/test/static.py')]
    if kind=='release':
        artifact=json.loads((run/'run.json').read_text())['artifact']
        return [python,str(source/'tools/test/release.py'),str(run/'install/artifact'/artifact['filename']),*(['--allow-dirty'] if artifact['allow_dirty'] else [])]
    raise ValueError(f'Unsupported deterministic suite {name}')


def root_for(run: Path) -> Path:
    return run.parents[1]


def inspect_case_results(run: Path, result: dict) -> None:
    path=run/'report'/f'{result["suite"]}.xml'
    if path.is_file():
        cases=list(ET.parse(path).iter('testcase'))
        skipped=sum(case.find('skipped') is not None for case in cases)
        result['cases']=len(cases)
        result['skipped']=skipped
        if skipped and result['status']=='passed': result['status']='incomplete'
    elif result['suite'] in ('node-fast','native-pi'):
        text=(run/'logs'/f'{result["suite"]}.log').read_text(errors='replace')
        import re
        for key in ('tests','pass','fail','skipped'):
            match=re.search(r'^# '+key+r' (\d+)$',text,re.M)
            if match: result[key]=int(match.group(1))
        if result.get('skipped',0) and result['status']=='passed': result['status']='incomplete'


def execute(args, root: Path, replay: Path | None = None) -> int:
    plan,reasons=select(args)
    if replay:
        previous=json.loads((replay/'run.json').read_text())
        plan=[result['suite'] for result in previous['results'] if not args.failed or result['status']!='passed']
        if not plan: raise ValueError('Replay selection is empty')
        reasons=[{'reason':'replay original snapshot and dependencies'}]
    audit()
    run,record=create_run(root,plan,reasons,replay)
    audit(run/'source')
    if 'phone' in plan:
        from tools.test.phone import capture_phone
        capture_phone(args, root, run, record, replay)
    if args.command=='release':
        if not args.artifact or not args.artifact.is_file(): raise ValueError('release requires --artifact pointing at the complete package archive')
        artifact=args.artifact.resolve()
        directory=run/'install/artifact'
        directory.mkdir()
        for item in (artifact,artifact.parent/'coragent-package-release.json'): shutil.copy2(item,directory/item.name)
        record['artifact']={'filename':artifact.name,'sha256':hashlib.sha256(artifact.read_bytes()).hexdigest(),'allow_dirty':args.allow_dirty}
        write_json(run/'run.json',record)
    dependencies={name:Path(value) for name,value in previous['dependencies'].items()} if replay else environment.dependency_paths(run/'source',root)
    record['dependencies']={name:str(path) for name,path in dependencies.items()}
    if replay: record['seed']=previous['seed']
    required={dependency for name in plan for dependency in load_manifest(run/'source')['suites'][name].get('requires',[])}
    missing=[name for name in required if not (dependencies[name]/'.prepared.json').is_file()]
    if missing:
        record.update(status='blocked',missing_dependencies=missing)
        write_json(run/'run.json',record)
        print(json.dumps({'run':run.name,'status':'blocked','missing_dependencies':missing}))
        return 2
    if 'python' in required and not environment.probe(dependencies['python']/'bin/python'):
        raise RuntimeError('The selected managed Python failed its dependency probe')
    if 'pi' in required:
        verification=subprocess.run([sys.executable,str(run/'source/scripts/prepare_pi_source.py'),'--verify',str(dependencies['pi'])],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        if verification.returncode: raise RuntimeError('The selected Pi source failed pin and patch verification')
    record['toolchain']={'node':subprocess.check_output(['node','--version'],text=True).strip(),'python':subprocess.check_output([str(dependencies['python']/'bin/python'),'--version'],text=True).strip() if 'python' in required else None,'platform':sys.platform}
    write_json(run/'run.json',record)
    os.symlink(dependencies['node']/'node_modules',run/'source/node_modules',target_is_directory=True)
    env=child_environment(root,run,dependencies)
    if 'phone' in plan:
        env.update({'CORAGENT_SOURCE':str(run/'source'),
                    'CORAGENT_TEST_FLUTTER_ROOT':record['phone']['flutter'],
                    'PUB_CACHE':record['phone']['pub_cache'],
                    'CI':'true','FLUTTER_SUPPRESS_ANALYTICS':'true','DART_SUPPRESS_ANALYTICS':'true'})
    env['CORAGENT_TEST_SEED']=str(record['seed'])
    env['PYTHONHASHSEED']=str(record['seed'])
    write_json(root/'registry'/f'lease-{run.name}.json',{'run':str(run),'dependencies':record['dependencies']})
    supervisor=Supervisor(run)
    try:
        for name in plan:
            command=command_for(name,run,dependencies,args.extra,args.files,args.workers)
            # Linux namespaces cover every descendant, including bash commands.
            if name=='system-services':
                from tools.test.units import prepare_units
                prepare_units(run,env)
                command=['unshare','--user','--map-current-user','--keep-caps','--net','--mount',sys.executable,str(run/'source/tools/test/offline.py'),*command]
            else:
                command=['unshare','--user','--map-root-user','--net','--pid','--fork','--kill-child=KILL','--mount-proc',sys.executable,str(run/'source/tools/test/offline.py'),*command]
            result=supervisor.execute(command,cwd=run/'source',env=env,name=name,timeout=args.timeout or load_manifest(run/'source')['suites'][name].get('timeout',600))
            inspect_case_results(run,result)
            record['results'].append(result)
            write_json(run/'run.json',record)
            print(json.dumps({key:result[key] for key in ('suite','status','seconds')}),flush=True)
            if supervisor.cancelled: break
    finally:
        from tools.test.units import cleanup_units
        units=cleanup_units(run)
        record['cleanup']=supervisor.close()
        record['cleanup']['units']=units
        if units['status']!='passed': record['cleanup']['status']='failed'
        if record['cleanup']['status']=='passed': shutil.rmtree(Path(record['socket_root']))
        record['finished']=time.time()
        record['status']='passed' if len(record['results'])==len(plan) and all(item['status']=='passed' for item in record['results']) and record['cleanup']['status']=='passed' else 'failed'
        record['source_current']=digest_source(ROOT,source_files(ROOT))==record['source_sha256'] if not replay else False
        if 'phone' in plan and not replay:
            phone_source=Path(record['phone']['source'])
            record['phone_source_current']=digest_source(phone_source,source_files(phone_source))==record['phone']['sha256']
            record['source_current'] &= record['phone_source_current']
        if not record['source_current'] and not replay and record['status']=='passed': record['status']='stale'
        write_json(run/'run.json',record)
        write_json(run/'report/result.json',record)
        evidence=root/'evidence'/run.name
        evidence.mkdir()
        shutil.copy2(run/'report/result.json',evidence/'result.json')
        (root/'registry'/f'lease-{run.name}.json').unlink()
    print(json.dumps({'run':run.name,'status':record['status'],'cleanup':record['cleanup']['status']}))
    return 0 if record['status']=='passed' else 1


def doctor(root: Path) -> int:
    dependencies=environment.dependency_paths(ROOT,root)
    report={'inventory':audit(),'dependencies':{name:(path/'.prepared.json').is_file() for name,path in dependencies.items()},
            'network_isolation':subprocess.run(['unshare','--user','--map-root-user','--net','--pid','--fork','--kill-child=KILL','--mount-proc','true'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0}
    report['interrupted_runs']=[]
    for run in (root/'runs').iterdir():
        if (run/'services.json').is_file():
            ledger=json.loads((run/'services.json').read_text())
            if not ledger.get('owner') or not alive(ledger['owner']):
                status=reap(run)
                from tools.test.units import cleanup_units
                units=cleanup_units(run)
                if units['status']!='passed': status['status']='failed'
                record_path=run/'run.json'
                if record_path.is_file():
                    record=json.loads(record_path.read_text())
                    if record.get('status')=='running':
                        record.update(status='interrupted',cleanup=status)
                        sockets=Path(record['socket_root'])
                        if status['status']=='passed' and sockets.exists(): shutil.rmtree(sockets)
                        write_json(record_path,record)
                        report['interrupted_runs'].append({'run':run.name,**status})
                lease=root/'registry'/f'lease-{run.name}.json'
                if status['status']=='passed' and lease.exists(): lease.unlink()
    print(json.dumps(report,sort_keys=True))
    return 0 if all(report['dependencies'].values()) and report['network_isolation'] else 2


def gc(root: Path, apply: bool) -> int:
    candidates=[]
    now=time.time()
    retained=[]
    for run in (root/'runs').iterdir():
        ledger=json.loads((run/'services.json').read_text()) if (run/'services.json').is_file() else {}
        record=json.loads((run/'run.json').read_text()) if (run/'run.json').is_file() else {}
        active=(ledger.get('owner') and alive(ledger['owner'])) or any(alive(item) for item in ledger.get('processes',[]))
        retention=14 if record.get('status')=='passed' else 30
        protected=active or (run/'KEEP').exists() or 'artifact' in record or now-run.stat().st_mtime < retention*86400
        if protected: retained.append(run)
        else: candidates.append(run)
    dependencies=set(environment.dependency_paths(ROOT,root).values())
    wheel_hashes=set()
    for run in retained:
        record=json.loads((run/'run.json').read_text()) if (run/'run.json').is_file() else {}
        dependencies.update(Path(path) for path in record.get('dependencies',{}).values())
        wheel_record=run/'report/wheel.json'
        if wheel_record.is_file(): wheel_hashes.add(json.loads(wheel_record.read_text())['artifact']['sha256'])
    for path in (root/'registry').glob('lease-*.json'):
        lease=json.loads(path.read_text())
        dependencies.update(Path(value) for value in lease.get('dependencies',{}).values())
    for category in ('python','host','node','pi'):
        directory=root/'deps'/category
        healthy=sorted((path for path in directory.iterdir() if (path/'.prepared.json').is_file()),key=lambda p:p.stat().st_mtime,reverse=True) if directory.exists() else []
        dependencies.update(healthy[:3])
        candidates.extend(path for path in healthy if path not in dependencies and not (path/'KEEP').exists())
    for build in (root/'builds').iterdir():
        receipt=build/'wheel.json'
        if receipt.is_file() and json.loads(receipt.read_text())['sha256'] not in wheel_hashes and now-build.stat().st_mtime > 14*86400:
            candidates.append(build)
    plan={'created':now,'paths':[str(path.relative_to(root)) for path in candidates]}
    write_json(root/'registry/gc-plan.json',plan)
    if apply:
        for path in candidates:
            if path.parent==root/'runs':
                for name in ('tmp','sockets'):
                    link=path/name
                    if link.is_symlink() and link.exists(): shutil.rmtree(link.resolve())
            shutil.rmtree(path)
    print(json.dumps({'eligible_paths':len(candidates),'applied':apply}))
    return 0


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['list','doctor','prepare','plan','check','verify','release','replay','gc',*load_manifest()['suites']])
    parser.add_argument('--env-root',type=Path,default=Path(os.environ.get('CORAGENT_TEST_ENV_ROOT',DEFAULT_ROOT)))
    parser.add_argument('--changed',action='store_true')
    parser.add_argument('--base')
    parser.add_argument('--scope')
    parser.add_argument('--files',nargs='+',default=[])
    parser.add_argument('--workers',type=int,default=max(1,min(8,(os.cpu_count() or 2)//2)))
    parser.add_argument('--timeout',type=int)
    parser.add_argument('--run')
    parser.add_argument('--phone-source',type=Path)
    parser.add_argument('--flutter-root',type=Path)
    parser.add_argument('--pub-cache',type=Path)
    parser.add_argument('--failed',action='store_true')
    parser.add_argument('--artifact',type=Path)
    parser.add_argument('--allow-dirty',action='store_true')
    parser.add_argument('--dry-run',action='store_true')
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--components',default='python,host,node,pi')
    parser.add_argument('--job-profiles',default='structure,wrapper',help='Public Conda profiles to cache during prepare; comma-separated.')
    values=list(sys.argv[1:] if argv is None else argv)
    extra=values[values.index('--')+1:] if '--' in values else []
    if '--' in values: values=values[:values.index('--')]
    args=parser.parse_args(values)
    args.extra=extra
    root=args.env_root.resolve()
    environment.configure_paths(root)
    try:
        if args.command=='list':
            for name,item in load_manifest()['suites'].items(): print(name+': '+item['description'])
            return 0
        if args.command=='prepare':
            components=args.components.split(',')
            expected=environment.dependency_paths(ROOT,root)
            hits={name:(expected[name]/'.prepared.json').is_file() for name in components}
            started=time.monotonic()
            environment.prepare(ROOT,root,components)
            from tools.test.scientific import prepare as prepare_scientific
            prepare_scientific(ROOT,root,[name for name in args.job_profiles.split(',') if name])
            metric={'status':'prepared','components':components,'cache_hits':hits,'seconds':round(time.monotonic()-started,3)}
            write_json(root/'registry'/('prepare-'+uuid.uuid4().hex[:10]+'.json'),metric)
            print(json.dumps(metric))
            return 0
        if args.command=='doctor': return doctor(root)
        if args.command=='plan':
            plan,reasons=select(args)
            print(json.dumps({'suites':plan,'reasons':reasons},indent=2))
            return 0
        if args.command=='gc': return gc(root,args.apply)
        if args.command in load_manifest()['suites'] and load_manifest()['suites'][args.command].get('external'):
            raise ValueError('External test data and destination require separate explicit authorization; private run content cannot be sent')
        replay=root/'runs'/args.run if args.command=='replay' and args.run else None
        if args.command=='replay' and not replay: raise ValueError('replay requires --run')
        return execute(args,root,replay)
    except (OSError,ValueError,RuntimeError,subprocess.CalledProcessError) as error:
        # Logs and tool output remain private; surface only exception class.
        print(json.dumps({'status':'infrastructure-error','category':type(error).__name__}))
        with (root/'registry/last-error.log').open('w') as log:
            import traceback
            traceback.print_exc(file=log)
        return 2

if __name__=='__main__': raise SystemExit(main())
