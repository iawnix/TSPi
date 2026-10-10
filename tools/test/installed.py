"""Build once, install an isolated wheel and verify real module origins."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from scripts._wheel import build_wheel,inspect_wheel
from tools.test.environment import key,locked
from tools.test.pytest_lane import run as run_pytest
from tools.test.supervisor import write_json


def install_wheel(wheel: Path, overlay: Path):
    env=dict(os.environ)
    env.pop('PYTHONPATH',None)
    subprocess.run([sys.executable,'-m','venv','--copies','--system-site-packages',str(overlay)],env=env,check=True)
    python=overlay/'bin/python'
    subprocess.run([str(python),'-m','pip','install','--no-index','--no-deps','--disable-pip-version-check',str(wheel)],env=env,check=True)
    program=('import importlib,pathlib,sys,json;'
             'names=["research_agent","research_agent.research","research_agent.jobs","research_agent.artifacts","research_agent.application","research_agent.foundation"];'
             'origins={name:importlib.import_module(name).__file__ for name in names};'
             f'prefix=pathlib.Path({str(overlay)!r});'
             'assert all(pathlib.Path(path).resolve().is_relative_to(prefix) for path in origins.values());'
             'import jsonschema,packaging;'
             f'base=pathlib.Path({sys.prefix!r});'
             'assert pathlib.Path(jsonschema.__file__).resolve().is_relative_to(base);'
             'assert pathlib.Path(packaging.__file__).resolve().is_relative_to(base)')
    subprocess.run([str(python),'-c',program],cwd=overlay,env=env,check=True)
    return python


def wheel_validation(files, extra, workers):
    test_root=Path(os.environ['CORAGENT_TEST_ENV_ROOT'])
    run_root=Path(os.environ['CORAGENT_TEST_RUN_ROOT'])
    identity=key(ROOT,['backend/pyproject.toml','backend/src/**/*','package.json','scripts/_wheel.py','tools/test/installed.py'],sys.version+sys.prefix)
    cache=test_root/'builds'/identity
    with locked(test_root,'wheel-'+identity):
        receipt=cache/'wheel.json'
        if receipt.is_file():
            descriptor=json.loads(receipt.read_text())
            wheel=cache/descriptor['filename']
            if inspect_wheel(wheel)['sha256'] != descriptor['sha256']: raise RuntimeError('Cached wheel checksum mismatch')
        else:
            if cache.exists(): shutil.rmtree(cache)
            cache.mkdir()
            descriptor=build_wheel(ROOT,cache,python=sys.executable)
            wheel=cache/descriptor['filename']
            write_json(receipt,descriptor)
            wheel.chmod(0o400)
    overlay=run_root/'install/wheel'
    install_wheel(wheel,overlay)
    write_json(run_root/'report/wheel.json',{'artifact':descriptor,'environment':str(overlay),'source':str(ROOT)})
    return run_pytest(files,extra,workers=workers,name='source',overlay=overlay)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--workers',type=int,required=True)
    parser.add_argument('--files',nargs='+',required=True)
    values=sys.argv[1:]
    extra=values[values.index('--')+1:] if '--' in values else []
    if '--' in values: values=values[:values.index('--')]
    args=parser.parse_args(values)
    return wheel_validation(args.files,extra,args.workers)

if __name__=='__main__': raise SystemExit(main())
