"""Real test-owned systemd units with private networks and durable ownership."""
from __future__ import annotations
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time


def manager_env():
    root=f'/run/user/{os.getuid()}'
    return {**os.environ,'XDG_RUNTIME_DIR':root,'DBUS_SESSION_BUS_ADDRESS':'unix:path='+root+'/bus'}


def inspect(unit):
    result=subprocess.run(['/usr/bin/systemctl','--user','show',unit,'--property=LoadState,Description,InvocationID'],env=manager_env(),capture_output=True,text=True,timeout=10)
    return dict(line.split('=',1) for line in result.stdout.splitlines() if '=' in line)


def atomic(path,value):
    pending=path.with_suffix('.pending')
    pending.write_text(json.dumps(value)+'\n');pending.replace(path)


def prepare_units(run: Path, env: dict):
    directory=run/'units';directory.mkdir(exist_ok=True)
    binary=run/'bin';binary.mkdir(exist_ok=True)
    wrapper=binary/'systemd-run'
    wrapper.write_text('#!/bin/sh\nexec '+shlex.quote(env['RESEARCH_AGENT_PYTHON'])+' '+shlex.quote(str(run/'source/tools/test/units.py'))+' launch "$@"\n')
    wrapper.chmod(0o700)
    env['PATH']=str(binary)+os.pathsep+env['PATH']
    env['RESEARCH_AGENT_TEST_UNIT_ROOT']=str(directory)
    env['RESEARCH_AGENT_TEST_UNIT_DESCRIPTION']='ResearchAgent local test '+run.name
    owner=os.getpid()
    start=process_start(owner)
    guardian=subprocess.Popen([sys.executable,str(run/'source/tools/test/units.py'),'guard',str(run),str(owner),start],start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    atomic(run/'units-guardian.json',{'pid':guardian.pid,'start':process_start(guardian.pid)})


def launch(args):
    root=Path(os.environ['RESEARCH_AGENT_TEST_UNIT_ROOT'])
    description=os.environ['RESEARCH_AGENT_TEST_UNIT_DESCRIPTION']
    unit=next((arg.split('=',1)[1] for arg in args if arg.startswith('--unit=')),None)
    if not unit or not re.fullmatch(r'research-agent-[a-z0-9-]+\.service',unit):
        raise ValueError('Test services require an explicit unique research-agent unit name')
    if inspect(unit).get('LoadState')!='not-found': raise RuntimeError('Refusing an existing service unit')
    if '--' not in args: raise ValueError('Test systemd launch requires an explicit command boundary')
    boundary=args.index('--')
    record={'unit':unit,'description':description,'invocation':None,'status':'starting'}
    path=root/(unit+'.json')
    atomic(path,record)
    command=args[boundary+1:]
    arguments=args[:boundary]
    # These properties apply to the actual user-manager service; it cannot
    # escape the test namespace by asking the manager to start a new unit.
    writable=[str(root)]
    for argument in arguments:
        if argument.startswith('--property=ReadWritePaths='): writable.append(argument.split('=',2)[2])
    arguments=[argument for argument in arguments if not argument.startswith('--property=ReadWritePaths=')]
    arguments += ['--property=ReadWritePaths='+' '.join(writable),'--property=PrivateNetwork=yes','--property=PrivateUsers=yes','--property=Description='+description,
                  '--property=RuntimeMaxSec=300s','--property=TimeoutStopSec=5s',
                  '--property=StandardOutput=append:'+str(root/(unit+'.stdout.log')),
                  '--property=StandardError=append:'+str(root/(unit+'.stderr.log'))]
    arguments += ['--','/usr/bin/env','-i',*[f'{name}={value}' for name,value in os.environ.items()],*command]
    result=subprocess.run(['/usr/bin/systemd-run',*arguments],env=manager_env())
    observed=inspect(unit)
    record.update(status='started' if result.returncode==0 else 'failed',invocation=observed.get('InvocationID'))
    atomic(path,record)
    return result.returncode


def cleanup_units(run: Path):
    directory=run/'units'
    failed=[]
    count=0
    if directory.exists():
        for path in directory.glob('*.json'):
            record=json.loads(path.read_text());unit=record['unit'];observed=inspect(unit);count+=1
            if observed.get('LoadState')=='not-found': continue
            if observed.get('Description')!=record['description'] or (record.get('invocation') and observed.get('InvocationID')!=record['invocation']):
                failed.append(unit);continue
            subprocess.run(['/usr/bin/systemctl','--user','stop',unit],env=manager_env(),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=15)
            subprocess.run(['/usr/bin/systemctl','--user','reset-failed',unit],env=manager_env(),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10)
            deadline=time.monotonic()+5
            while inspect(unit).get('LoadState')!='not-found' and time.monotonic()<deadline: time.sleep(.05)
            if inspect(unit).get('LoadState')!='not-found': failed.append(unit)
    result={'status':'failed' if failed else 'passed','registered':count,'remaining':len(failed)}
    if (run/'report').is_dir(): atomic(run/'report/units.json',result)
    return result


def process_start(pid):
    try: raw=Path(f'/proc/{pid}/stat').read_text()
    except FileNotFoundError: return None
    values=raw[raw.rindex(')')+2:].split()
    return None if values[0]=='Z' else values[19]


def guard(run,owner,start):
    while process_start(owner)==start: time.sleep(.1)
    cleanup_units(run)


if __name__=='__main__':
    if sys.argv[1]=='launch': raise SystemExit(launch(sys.argv[2:]))
    if sys.argv[1]=='guard': guard(Path(sys.argv[2]),int(sys.argv[3]),sys.argv[4])
    else: raise SystemExit('Unknown private unit supervisor operation')
