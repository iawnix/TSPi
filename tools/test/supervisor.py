"""Linux process ownership, cancellation and persistent cleanup audit."""
from __future__ import annotations
import ctypes
import json
import os
import signal
import subprocess
import time
from pathlib import Path


def identity(pid: int) -> dict | None:
    try:
        raw = Path(f'/proc/{pid}/stat').read_text()
    except (FileNotFoundError, ProcessLookupError):
        return None
    fields = raw[raw.rindex(')') + 2:].split()
    return {'pid':pid, 'ppid':int(fields[1]), 'start':fields[19], 'state':fields[0]}


def alive(item: dict) -> bool:
    current = identity(item['pid'])
    return bool(current and current['start'] == item['start'] and current['state'] != 'Z')


def descendants(parent: int) -> list[dict]:
    processes = [identity(int(path.name)) for path in Path('/proc').iterdir() if path.name.isdecimal()]
    processes = [item for item in processes if item]
    selected = {parent}
    while True:
        children = {item['pid'] for item in processes if item['ppid'] in selected}
        added = children - selected
        if not added: break
        selected.update(added)
    return [item for item in processes if item['pid'] in selected and item['pid'] != parent]


def write_json(path: Path, value: object):
    temporary = path.with_suffix('.pending')
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    temporary.replace(path)


class Supervisor:
    def __init__(self, run: Path):
        self.libc = ctypes.CDLL(None, use_errno=True)
        previous_subreaper = ctypes.c_int()
        if self.libc.prctl(37, ctypes.byref(previous_subreaper), 0, 0, 0) != 0:
            raise OSError('Cannot read caller child-subreaper state')
        self.previous_subreaper = previous_subreaper.value
        if self.libc.prctl(36, 1, 0, 0, 0) != 0:
            raise OSError('Linux child subreaper unavailable')
        self.run = run
        self.items: dict[int, dict] = {}
        self.cancelled = False
        self.previous = {}
        for signum in (signal.SIGINT, signal.SIGTERM):
            self.previous[signum] = signal.signal(signum, self.cancel)
        self.persist()

    def cancel(self, signum, frame):
        self.cancelled = True

    def persist(self):
        write_json(self.run / 'services.json', {'owner':identity(os.getpid()),'processes':list(self.items.values())})

    def collect(self):
        for item in descendants(os.getpid()): self.items[item['pid']] = item
        self.persist()

    def execute(self, command: list[str], *, cwd: Path, env: dict, name: str, timeout: int) -> dict:
        started = time.monotonic()
        with (self.run / 'logs' / (name + '.log')).open('wb') as log:
            owner_pid=os.getpid()
            def parent_death():
                libc=ctypes.CDLL(None,use_errno=True)
                if libc.prctl(1,signal.SIGKILL,0,0,0)!=0: os._exit(125)
                if os.getppid()!=owner_pid: os._exit(125)
            child = subprocess.Popen(command, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,preexec_fn=parent_death)
            item = identity(child.pid)
            if item: self.items[child.pid] = item
            self.persist()
            expired = False
            while child.poll() is None:
                self.collect()
                if self.cancelled or time.monotonic() - started >= timeout:
                    expired = not self.cancelled
                    self.cleanup()
                    break
                time.sleep(0.1)
            code = child.wait()
            self.collect()
        return {'suite':name,'returncode':code,'seconds':round(time.monotonic()-started,3),
                'status':'cancelled' if self.cancelled else 'timeout' if expired else 'passed' if code == 0 else 'failed'}

    def cleanup(self) -> dict:
        self.collect()
        for sig, deadline in ((signal.SIGTERM,3),(signal.SIGKILL,2)):
            for item in list(self.items.values()):
                if alive(item):
                    try: os.kill(item['pid'],sig)
                    except ProcessLookupError: pass
            end = time.monotonic() + deadline
            while time.monotonic() < end:
                self.collect()
                if not any(alive(item) for item in self.items.values()): break
                time.sleep(0.05)
        # Reap adopted detached children as well as the suite leader.
        while True:
            try:
                if os.waitpid(-1,os.WNOHANG)[0] == 0: break
            except ChildProcessError: break
        remaining = [item for item in self.items.values() if alive(item)]
        for path in (self.run / 'sockets').glob('*'):
            if path.is_socket(): path.unlink()
        result = {'status':'failed' if remaining else 'passed','remaining':remaining,'registered':len(self.items)}
        write_json(self.run / 'report/cleanup.json',result)
        return result

    def close(self):
        try:
            return self.cleanup()
        finally:
            for signum, handler in self.previous.items(): signal.signal(signum,handler)
            # Do not make subsequent subprocess users inherit responsibility
            # for reaping unrelated orphaned grandchildren in this process.
            if self.libc.prctl(36, self.previous_subreaper, 0, 0, 0) != 0:
                raise OSError('Cannot restore caller child-subreaper state')


def reap(run: Path) -> dict:
    ledger = json.loads((run / 'services.json').read_text())
    if ledger.get('owner') and alive(ledger['owner']):
        return {'status':'active'}
    items = ledger['processes']
    for sig in (signal.SIGTERM,signal.SIGKILL):
        for item in items:
            if alive(item):
                try: os.kill(item['pid'],sig)
                except ProcessLookupError: pass
        deadline = time.monotonic()+2
        while any(alive(item) for item in items) and time.monotonic()<deadline: time.sleep(0.05)
    remaining = sum(alive(item) for item in items)
    return {'status':'failed' if remaining else 'passed','remaining':remaining}
