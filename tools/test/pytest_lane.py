"""File-level pytest sharding within the runner's shared CPU budget."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import xml.etree.ElementTree as ET


def run(files, extra, *, workers, name, overlay=None):
    run_root=Path(os.environ['CORAGENT_TEST_RUN_ROOT'])
    files=list(files)
    random.Random(int(os.environ['CORAGENT_TEST_SEED'])).shuffle(files)
    count=min(workers,len(files))
    if count < 1: raise ValueError('No test files selected')
    children=[]
    for index in range(count):
        paths=files[index::count]
        shard=f'{name}-{index}'
        command=[sys.executable,'-m','pytest']
        if overlay:
            program=('import importlib,pathlib,sys;'
                     'module=importlib.import_module("research_agent");'
                     f'assert pathlib.Path(module.__file__).resolve().is_relative_to(pathlib.Path({str(overlay)!r}));'
                     'import pytest;sys.exit(pytest.main(sys.argv[1:]))')
            command=[str(overlay/'bin/python'),'-c',program]
        command += [*paths,'--basetemp',str((run_root/'tmp').resolve()/('s'+hashlib.sha256(name.encode()).hexdigest()[:4]+'-'+str(index))),'--junitxml',str(run_root/'report'/f'{shard}.xml'),
                    '-o',f'cache_dir={run_root}/cache/{shard}',*extra]
        env=dict(os.environ)
        if overlay:
            env.pop('PYTHONPATH',None)
            env['CORAGENT_PYTHON']=str(overlay/'bin/python')
        log=(run_root/'logs'/f'{shard}.log').open('wb')
        child=subprocess.Popen(command,env=env,stdout=log,stderr=subprocess.STDOUT)
        children.append((child,log,shard))
    failed=False
    document=ET.Element('testsuites')
    for child,log,shard in children:
        code=child.wait()
        log.close()
        failed |= code != 0
        path=run_root/'report'/f'{shard}.xml'
        if path.is_file():
            parsed=ET.parse(path).getroot()
            document.extend(list(parsed) if parsed.tag=='testsuites' else [parsed])
        else: failed=True
    ET.ElementTree(document).write(run_root/'report'/f'{name}.xml',encoding='utf-8',xml_declaration=True)
    return int(failed)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--name',required=True)
    parser.add_argument('--workers',type=int,required=True)
    parser.add_argument('--files',nargs='+',required=True)
    values=sys.argv[1:]
    extra=values[values.index('--')+1:] if '--' in values else []
    if '--' in values: values=values[:values.index('--')]
    args=parser.parse_args(values)
    return run(args.files,extra,workers=args.workers,name=args.name)

if __name__=='__main__': raise SystemExit(main())
