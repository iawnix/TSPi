"""Runner regressions: ownership, timeout cleanup and fail-closed networking."""
import json
import os
from pathlib import Path
import subprocess
import sys

from tools.test.runner import changes
from tools.test.supervisor import Supervisor, alive, identity
from tests.support.repo import REPO_ROOT


def run_layout(tmp_path):
    for name in ('logs','report','sockets'): (tmp_path/name).mkdir()
    return tmp_path


def test_process_exiting_during_proc_read_is_absent(monkeypatch):
    def vanished(path, *args, **kwargs):
        raise ProcessLookupError('process exited during procfs read')
    monkeypatch.setattr(Path, 'read_text', vanished)
    assert identity(12345) is None
    assert not alive({'pid': 12345, 'start': '1'})


def test_timeout_stops_detached_descendants_and_preserves_first_log(tmp_path):
    run=run_layout(tmp_path)
    supervisor=Supervisor(run)
    program=('import subprocess,sys,time;'
             'subprocess.Popen([sys.executable,"-c","import time;time.sleep(60)"],start_new_session=True);'
             'print("synthetic-first-failure",flush=True);time.sleep(60)')
    try:
        result=supervisor.execute([sys.executable,'-c',program],cwd=tmp_path,env=dict(os.environ),name='timeout',timeout=1)
        assert result['status']=='timeout'
    finally:
        cleanup=supervisor.close()
    assert cleanup['status']=='passed'
    ledger=json.loads((run/'services.json').read_text())
    assert len(ledger['processes'])>=2
    assert not any(alive(item) for item in ledger['processes'])
    assert 'synthetic-first-failure' in (run/'logs/timeout.log').read_text()


def test_reused_pid_identity_cannot_be_signalled():
    owner=identity(os.getpid())
    assert alive(owner)
    assert not alive({**owner,'start':'different-start-time'})


def test_network_namespace_permits_loopback_but_has_no_external_route(tmp_path):
    program=('import socket;'
             's=socket.socket();s.bind(("127.0.0.1",0));s.listen();'
             'c=socket.create_connection(s.getsockname(),timeout=1);a,_=s.accept();'
             'c.close();a.close();s.close();'
             'x=socket.socket();x.settimeout(1);'
             'code=x.connect_ex(("192.0.2.1",443));assert code!=0')
    result=subprocess.run(['unshare','--user','--map-root-user','--net','--mount',sys.executable,
                           str(REPO_ROOT/'tools/test/offline.py'),sys.executable,'-c',program],
                          stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    assert result.returncode==0


def test_killed_supervisor_cannot_leave_a_detached_namespace_child(tmp_path):
    import signal
    import time
    from tools.test.supervisor import descendants
    run=run_layout(tmp_path)
    ready=tmp_path/'ready'
    payload=('import subprocess,sys,time;from pathlib import Path;'
             'subprocess.Popen([sys.executable,"-c","import time;time.sleep(60)"],start_new_session=True);'
             f'Path({str(ready)!r}).write_text("ready");time.sleep(60)')
    command=['unshare','--user','--map-root-user','--net','--pid','--fork','--kill-child=KILL','--mount-proc',
             sys.executable,str(REPO_ROOT/'tools/test/offline.py'),sys.executable,'-c',payload]
    program=('from pathlib import Path;import os;from tools.test.supervisor import Supervisor;'
             f's=Supervisor(Path({str(run)!r}));'
             f's.execute({command!r},cwd=Path({str(run)!r}),env=dict(os.environ),name="killed",timeout=60)')
    env=dict(os.environ,PYTHONPATH=str(REPO_ROOT))
    owner=subprocess.Popen([sys.executable,'-c',program],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    captured=[]
    try:
        deadline=time.monotonic()+5
        while not ready.exists() and time.monotonic()<deadline:
            assert owner.poll() is None
            time.sleep(0.02)
        assert ready.exists()
        captured=descendants(owner.pid)
        assert len(captured)>=3
        owner.kill();owner.wait()
        deadline=time.monotonic()+5
        while any(alive(item) for item in captured) and time.monotonic()<deadline: time.sleep(0.02)
        assert not any(alive(item) for item in captured)
    finally:
        if owner.poll() is None: owner.kill();owner.wait()
        for item in captured:
            if alive(item): os.kill(item['pid'],signal.SIGKILL)


def test_shared_dependency_mounts_are_read_only():
    import errno
    paths=json.loads(os.environ['CORAGENT_TEST_DEPENDENCIES'])
    assert paths
    for directory in paths:
        destination=Path(directory)/f'.mutation-probe-{os.getpid()}'
        try:
            destination.write_text('synthetic')
        except OSError as error:
            assert error.errno==errno.EROFS
        else:
            destination.unlink()
            raise AssertionError('Shared dependency environment was writable')
