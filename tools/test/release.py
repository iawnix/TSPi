"""Validate the supplied complete package bytes through the real installer."""
from __future__ import annotations
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from scripts.install_package import install_package
from scripts._wheel import release_wheel
from tools.test.supervisor import write_json


def main():
    artifact=Path(sys.argv[1]).resolve()
    manifest=artifact.parent/'coragent-package-release.json'
    run=Path(os.environ['CORAGENT_TEST_RUN_ROOT'])
    install=run/'install/release'
    before=hashlib.sha256(artifact.read_bytes()).hexdigest()
    environment=dict(os.environ,CONDA_OFFLINE='true')
    # This is the real installer, with its real locked Python environment and
    # bundled wheel. No fixture installer or source-PYTHONPATH substitution.
    original=dict(os.environ)
    os.environ.update(environment)
    try:
        result=install_package(manifest,artifact,install,conda=os.environ.get('CORAGENT_TEST_CONDA'),allow_dirty='--allow-dirty' in sys.argv)
    finally:
        os.environ.clear();os.environ.update(original)
    package=Path(result['package_root'])/'agent'
    if not package.resolve().is_relative_to(install): raise RuntimeError('Installed package escapes its run')
    wheel,descriptor=release_wheel(package)
    runtime=json.loads(Path(result['runtime']['manifest_path']).read_text())
    python=Path(runtime['python_executable'])
    external=run/'workspaces/external-cwd'
    external.mkdir()
    clean=dict(environment)
    clean.pop('PYTHONPATH',None)
    code=('import research_agent,pathlib;'
          f'assert pathlib.Path(research_agent.__file__).resolve().is_relative_to(pathlib.Path({str(python.parent.parent)!r}))')
    subprocess.run([str(python),'-c',code],cwd=external,env=clean,check=True)
    subprocess.run([str(result['launchers']['coragent']),'--version'],cwd=external,env=clean,check=True)
    subprocess.run([str(result['launchers']['coragent']),'--help'],cwd=external,env=clean,check=True)
    # Seed only the verified third-party cache. The installed preparation and
    # binding code must validate and wire it; source code cannot repair the
    # first-party payload under test.
    pin=json.loads((package/'config/pi-source.json').read_text())
    pi_root=install/'runtimes/pi'/pin['commit']
    pi_root.mkdir(parents=True)
    subprocess.run(['cp','--reflink=auto','-a',str(Path(environment['CORAGENT_TEST_PI_RUNTIME_ROOT']))+'/.',str(pi_root)],check=True)
    subprocess.run([str(python),str(package/'scripts/prepare_pi_source.py'),'--install',str(install)],cwd=external,env=clean,check=True)
    binding=('import sys;from pathlib import Path;'
             f"sys.path.insert(0,{str(package / 'scripts')!r});"
             'from install_wizard import bind_pi_runtime_node_modules;'
             f'bind_pi_runtime_node_modules(Path({str(install)!r}),Path({str(pi_root)!r}))')
    subprocess.run([str(python),'-c',binding],cwd=external,env=clean,check=True)
    clean.update({'CORAGENT_TEST_INSTALLED_ROOT':str(install),
                  'CORAGENT_TEST_PACKAGE_ROOT':str(package),'CORAGENT_PACKAGE_ROOT':str(package),
                  'CORAGENT_TEST_PI_RUNTIME_ROOT':str(pi_root),'CORAGENT_PI_RUNTIME_ROOT':str(pi_root),
                  'CORAGENT_PYTHON':str(python),'CORAGENT_RUNTIME_MANIFEST':str(result['runtime']['manifest_path']),
                  'CORAGENT_INSTALL_ROOT':str(install)})
    native_report=run/'report/installed-native.tap'
    with native_report.open('w') as log:
        native=subprocess.run(['node','--import',str(pi_root/'packages/coding-agent/src/experimental/source-resolver.ts'),
                               '--test','--test-concurrency=1','--test-reporter=tap',
                               str(ROOT/'tests/node/native/pi-session-worker-startup.test.mjs'),
                               str(ROOT/'tests/node/native/worker-research-flow.test.mjs'),
                               str(ROOT/'tests/node/native/worker-task-continuation.test.mjs')],
                              cwd=external,env=clean,stdout=log,stderr=subprocess.STDOUT)
    native_text=native_report.read_text()
    counts={name:int(match.group(1)) for name in ('tests','pass','fail','skipped')
            if (match:=re.search(r'^# '+name+r' (\d+)$',native_text,re.M))}
    write_json(run/'report/installed-native.json',{'returncode':native.returncode,'counts':counts})
    if native.returncode or counts.get('tests',0)<3 or counts.get('skipped',0):
        raise RuntimeError('Installed native Worker acceptance failed; see private installed-native report')
    if hashlib.sha256(artifact.read_bytes()).hexdigest()!=before: raise RuntimeError('Release bytes changed during acceptance')
    report={'artifact_sha256':before,'wheel':descriptor,'installer':'passed','external_cwd':'passed',
            'native_worker':'passed','seven_tools':'passed','task_continuation':'passed','native_counts':counts,'phone':'not-run','live_model':'not-authorized','remote_platform':'not-authorized'}
    # Always use the installed uninstaller; the source checkout must not repair
    # omissions in the installation under test.
    uninstaller=package/'scripts/uninstall.py'
    subprocess.run([str(python),str(uninstaller),'--install-root',str(install),'--service-scope','none',
                    '--purge-all','--non-interactive','--yes','--json'],cwd=external,env=clean,check=True)
    if install.exists(): raise RuntimeError('Uninstall left the installation root behind')
    report['uninstall']='passed'
    write_json(run/'report/release.json',report)
    return 0

if __name__=='__main__': raise SystemExit(main())
