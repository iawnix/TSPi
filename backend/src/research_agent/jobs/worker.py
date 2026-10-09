"""Stdlib Job supervisor, launched in a separate unit by the application runtime."""
from pathlib import Path
import json
import os
import signal
import subprocess
import sys
import time
import pwd
from datetime import datetime, timezone

if __package__:
    from .config_contract import execution_timeout
    from .process_environment import job_process_environment, minimum_environment
else:
    from config_contract import execution_timeout
    from process_environment import job_process_environment, minimum_environment


def now():
    return datetime.now(timezone.utc).isoformat()


def write(path, value):
    temporary=path.with_suffix('.tmp')
    with temporary.open('w') as stream:
        json.dump(value,stream);stream.flush();os.fsync(stream.fileno())
    temporary.replace(path)


def identity(pid):
    try:
        fields=Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()
        return fields[19]
    except (OSError,IndexError): return None


def supervisor_environment():
    """Control-plane credentials and interpreter settings never reach a Job."""
    return minimum_environment(pwd.getpwuid(os.getuid()).pw_dir)


def job_environment(root, payload):
    env, path = job_process_environment(root, payload['receipt']['metadata'], payload['env'],
                                        home=pwd.getpwuid(os.getuid()).pw_dir)
    scratch = Path(path)
    scratch.mkdir(parents=True, exist_ok=True, mode=0o700)
    return env, scratch


def main():
    payload=json.loads(Path(sys.argv[1]).read_text()) if len(sys.argv) == 2 else json.load(sys.stdin)
    root=Path(payload['cwd']); receipt=payload['receipt']
    receipt['pid']=os.getpid()
    receipt['metadata']={**receipt['metadata'],'supervisor_start':identity(os.getpid()),'supervised':True}
    status={'job_id':receipt['job_id'],'platform':receipt['platform'],'started_at':now()}
    proc=None
    stopping=False
    def stop(*_):
        nonlocal stopping
        stopping=True
    signal.signal(signal.SIGTERM,stop)
    signal.signal(signal.SIGINT,stop)
    try:
        env, scratch = job_environment(root, payload)
        receipt['metadata']['scratch_path'] = str(scratch)
        timeout = execution_timeout(payload.get('timeout'), receipt['metadata'].get('resources', {}))
        with (root/'logs/stdout.log').open('wb') as out, (root/'logs/stderr.log').open('wb') as err:
            source=open(payload['stdin'],'rb') if payload.get('stdin') else subprocess.DEVNULL
            try:
                proc=subprocess.Popen(payload['command'],cwd=root,env=env,stdin=source,stdout=out,stderr=err,start_new_session=True)
            finally:
                if source != subprocess.DEVNULL:source.close()
            write(root/'receipt.json',receipt)
            deadline=time.monotonic()+timeout if timeout is not None else None
            reason=None
            while proc.poll() is None:
                if stopping or (root/'cancel.request').exists():reason='cancelled'
                elif deadline is not None and time.monotonic()>=deadline:reason='timed_out'
                if reason:
                    try:os.killpg(proc.pid,signal.SIGTERM)
                    except ProcessLookupError:pass
                    try:proc.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        try:os.killpg(proc.pid,signal.SIGKILL)
                        except ProcessLookupError:pass
                        proc.wait()
                    break
                time.sleep(.05)
            # Kill any surviving children within this Job's process group.
            try:os.killpg(proc.pid,signal.SIGKILL)
            except ProcessLookupError:pass
            status.update(state=reason or ('succeeded' if proc.returncode==0 else 'failed'),exit_code=proc.returncode)
    except Exception as exc:
        if proc is not None and proc.poll() is None:
            try:os.killpg(proc.pid,signal.SIGKILL)
            except ProcessLookupError:pass
            proc.wait()
        write(root/'receipt.json',receipt)
        status.update(state='failed',exit_code=None,error=f'{type(exc).__name__}: {exc}')
    finally:
        status['finished_at']=now();write(root/'status.json',status)


if __name__=='__main__':main()
