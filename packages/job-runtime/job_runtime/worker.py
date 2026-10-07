"""Detached local Job supervisor. Uses only stdlib and survives Host restarts."""
from pathlib import Path
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone


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


def main():
    payload=json.load(sys.stdin)
    root=Path(payload['cwd']); receipt=payload['receipt']
    receipt['pid']=os.getpid()
    receipt['metadata']={**receipt['metadata'],'supervisor_start':identity(os.getpid()),'supervised':True}
    status={'job_id':receipt['job_id'],'platform':'local','started_at':now()}
    proc=None
    stopping=False
    def stop(*_):
        nonlocal stopping
        stopping=True
    signal.signal(signal.SIGTERM,stop)
    signal.signal(signal.SIGINT,stop)
    try:
        env=os.environ.copy();env.update(payload['env'])
        with (root/'logs/stdout.log').open('wb') as out, (root/'logs/stderr.log').open('wb') as err:
            source=open(payload['stdin'],'rb') if payload.get('stdin') else subprocess.DEVNULL
            try:
                proc=subprocess.Popen(payload['command'],cwd=root,env=env,stdin=source,stdout=out,stderr=err,start_new_session=True)
            finally:
                if source != subprocess.DEVNULL:source.close()
            write(root/'receipt.json',receipt)
            deadline=time.monotonic()+payload['timeout'] if payload.get('timeout') else None
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
        write(root/'receipt.json',receipt)
        status.update(state='failed',exit_code=None,error=f'{type(exc).__name__}: {exc}')
    finally:
        status['finished_at']=now();write(root/'status.json',status)


if __name__=='__main__':main()
