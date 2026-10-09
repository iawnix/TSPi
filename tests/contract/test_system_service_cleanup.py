"""A killed runner must not leave a user-manager service behind."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

from tests.support.repo import REPO_ROOT
from tools.test.units import cleanup_units, inspect


def test_unit_guardian_removes_service_after_owner_is_killed(tmp_path):
    run=tmp_path/'owner'
    for path in ('logs','report','source/tools/test'): (run/path).mkdir(parents=True)
    (run/'source/tools/test/units.py').symlink_to(REPO_ROOT/'tools/test/units.py')
    unit='research-agent-test-guardian-'+uuid.uuid4().hex+'.service'
    ready=run/'ready'
    program=('import os,time;from pathlib import Path;from tools.test.units import prepare_units,launch;'
             f'run=Path({str(run)!r});env=dict(os.environ);prepare_units(run,env);os.environ.update(env);'
             f'code=launch(["--user","--collect","--quiet","--unit={unit}","--",'
             f'{sys.executable!r},"-c","import time;time.sleep(60)"]);assert code==0;'
             f'Path({str(ready)!r}).touch();time.sleep(60)')
    env=dict(os.environ,PYTHONPATH=str(REPO_ROOT))
    owner=subprocess.Popen([sys.executable,'-c',program],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        deadline=time.monotonic()+10
        while not ready.exists() and time.monotonic()<deadline:
            assert owner.poll() is None
            time.sleep(.02)
        assert ready.exists()
        assert inspect(unit)['LoadState']=='loaded'
        owner.kill();owner.wait()
        deadline=time.monotonic()+10
        while (inspect(unit).get('LoadState')!='not-found' or not (run/'report/units.json').exists()) and time.monotonic()<deadline: time.sleep(.05)
        assert inspect(unit)['LoadState']=='not-found'
        report=json.loads((run/'report/units.json').read_text())
        assert report['status']=='passed'
        assert report['registered']==1
    finally:
        if owner.poll() is None: owner.kill();owner.wait()
        assert cleanup_units(run)['status']=='passed'
