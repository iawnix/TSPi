"""SSH backed execution platforms.

The remote adapter implements the same lifecycle as the local process adapter.
It stages a job directory with rsync, submits one wrapper script to PBS/Torque,
and brings declared outputs back during collect.
"""
from __future__ import annotations

from abc import abstractmethod
import hashlib
import math
import os
from .outputs import collect_outputs
import json
import re
import shlex
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from dataclasses import replace
from pathlib import Path
from typing import Any

from .models import JobReceipt, JobSpec, JobState, JobStatus
from .platform import ExecutionPlatform
from .config_contract import SUBMISSION_FIELDS, execution_timeout, validate_submission
from .process_environment import job_process_environment
from .environment import _capture


class RemoteExecutionPlatform(ExecutionPlatform):
    """Base class for SSH, Slurm, PBS/Torque, and container adapters."""

    name = "remote"

    @abstractmethod
    def stage_inputs(self, spec: JobSpec) -> dict[str, Any]:
        ...

    @abstractmethod
    def fetch_outputs(self, receipt: JobReceipt) -> dict[str, Any]:
        ...


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TorqueSSHPlatform(RemoteExecutionPlatform):
    """Execute jobs on a PBS/Torque host over SSH and rsync."""

    name = "remote"

    def __init__(self, config: dict[str, Any], *, platform_name: str = "remote") -> None:
        self.config = dict(config)
        self.name = platform_name
        self.host = self._required_string("ssh_host")
        self.remote_root = self._required_string("remote_root").rstrip("/")
        self.scheduler = str(self.config.get("scheduler", "torque")).lower()
        if self.scheduler not in {"torque", "pbs"}:
            raise ValueError(f"unsupported remote scheduler: {self.scheduler}")
        self.ssh_config = self.config.get("ssh_config")
        self.connect_timeout = int(self.config.get("connect_timeout_seconds", 15))
        self.command_timeout = int(self.config.get("command_timeout_seconds", 60))
        self.transfer_timeout = int(self.config.get("transfer_timeout_seconds", 3600))
        commands = self.config.get("commands", {})
        self.commands = {
            "qsub": str(commands.get("qsub", "qsub")),
            "qstat": str(commands.get("qstat", "qstat")),
            "qdel": str(commands.get("qdel", "qdel")),
        }
        self.diagnostic_command = commands.get("checkjob")
        self.allowed_queues = tuple(str(item) for item in self.config.get("allowed_queues", ()))

    def _required_string(self, key: str) -> str:
        value = self.config.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"remote environment is missing {key}")
        return value.strip()

    def _ssh_base(self) -> list[str]:
        command = ["ssh", "-o", f"ConnectTimeout={self.connect_timeout}", "-o", "BatchMode=yes"]
        if self.ssh_config:
            command.extend(["-F", str(self.ssh_config)])
        command.append(self.host)
        return command

    def _run_ssh(self, script: str, *, check: bool = True) -> subprocess.CompletedProcess[str]:
        result = _capture([*self._ssh_base(), f"sh -lc {shlex.quote(script)}"], timeout=self.command_timeout)
        if check:
            result.check_returncode()
        return result

    def _rsync(self, source: Path, destination: str, *, pull: bool = False) -> None:
        transport = self._ssh_base()[:-1]
        command = ["rsync", "-a", "--protect-args", "-e", shlex.join(transport)]
        if pull:
            # Compute output must not overwrite the controller's authoritative
            # spec, receipts, status or dispatch inputs during collection.
            for path in ('spec.json', 'receipt.json', 'status.json', 'input_manifest.json',
                         'supervisor.json', 'remote.json', 'cancel.request', '.research-agent', '.scratch'):
                command.append('--exclude=/' + path)
            command.extend([f"{self.host}:{destination}/", str(source) + "/"])
        else:
            target = f"{self.host}:{destination}" + ("/" if source.is_dir() else "")
            command.extend([str(source) + ("/" if source.is_dir() else ""), target])
        _capture(command, timeout=self.transfer_timeout).check_returncode()

    def _remote_dir(self, spec: JobSpec) -> str:
        job_id = spec.job_id or f"job_{uuid.uuid4().hex}"
        if not re.fullmatch(r"job_[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}", job_id):
            raise ValueError("remote job id has an invalid format")
        scope = hashlib.sha256(str(spec.cwd.resolve()).encode()).hexdigest()[:24]
        return f"{self.remote_root}/{job_id}-{scope}"

    def probe(self, spec: JobSpec) -> dict[str, Any]:
        missing = [str(path) for path in spec.inputs if not path.exists()]
        commands = [*self.commands.values(), "rsync"]
        if execution_timeout(spec.timeout_seconds, spec.metadata.get("resources", {})) is not None:
            commands.append("timeout")
        checks = " && ".join(f"command -v {shlex.quote(value)} >/dev/null" for value in commands)
        script = f"test -d {shlex.quote(self.remote_root)} && test -w {shlex.quote(self.remote_root)} && {checks}"
        try:
            result = self._run_ssh(script)
            available = result.returncode == 0
            error = None if available else (result.stderr.strip() or "remote capability probe failed")
        except (OSError, subprocess.SubprocessError) as exc:
            available, error = False, str(exc)
        return {
            "platform": self.name, "available": available, "ssh_host": self.host,
            "scheduler": self.scheduler, "remote_root": self.remote_root,
            "cwd_exists": spec.cwd.is_dir(), "inputs_present": not missing,
            "missing_inputs": missing, "error": error,
        }

    def stage_inputs(self, spec: JobSpec) -> dict[str, Any]:
        remote_dir = self._remote_dir(spec)
        self._run_ssh(f"umask 077; mkdir -p {shlex.quote(remote_dir)}/logs {shlex.quote(remote_dir)}/.research-agent")
        self._rsync(spec.cwd, remote_dir)
        for path in spec.inputs:
            if not path.resolve().is_relative_to(spec.cwd.resolve()):
                self._rsync(path, f"{remote_dir}/{path.name}")
        return {"remote_dir": remote_dir}

    def _wrapper(self, spec, remote_dir):
        variables, scratch = job_process_environment(remote_dir, spec.metadata, spec.env)
        timeout = execution_timeout(spec.timeout_seconds, spec.metadata.get('resources', {}))
        argv = list(spec.command)
        if timeout is not None:
            record_exit = ('"$@"; code=$?; printf "%s\\n" "$code" > .research-agent/command.exit; exit "$code"')
            argv = ['timeout', '--signal=TERM', '--kill-after=5', str(timeout),
                    '/bin/sh', '-c', record_exit, 'research-agent-command', *argv]
        stdin = '/dev/null'
        if spec.stdin:
            path = spec.stdin.resolve()
            if path.is_relative_to(spec.cwd.resolve()):
                stdin = remote_dir + '/' + str(path.relative_to(spec.cwd.resolve()))
            elif path in [item.resolve() for item in spec.inputs]:
                stdin = remote_dir + '/' + path.name
            else:
                raise ValueError('remote stdin must be a staged Job input')
        script = ('set +e\numask 077\n'
                  + 'mkdir -p -- ' + shlex.quote(scratch) + ' || exit 125\n'
                  + 'cd ' + shlex.quote(remote_dir) + ' || exit 125\n'
                  + 'rm -f .research-agent/command.exit\n'
                  + shlex.join(argv) + ' < ' + shlex.quote(stdin) + ' > logs/stdout.log 2> logs/stderr.log\n'
                  + 'code=$?\n')
        # A program may itself exit 124/137. Its own exit receipt distinguishes
        # that failure from termination of the timeout process group.
        if timeout is not None:
            script += ('if { [ "$code" = 124 ] || [ "$code" = 137 ]; } && [ ! -f .research-agent/command.exit ]; then '
                       'printf "timed_out\\n" > status.state.tmp; mv status.state.tmp status.state; fi\n')
        script += 'printf "%s\\n" "$code" > status.exit.tmp; mv status.exit.tmp status.exit\nexit "$code"\n'
        # Scheduler/login variables are not inherited by the scientific process.
        # HOME is supplied by the remote account, never by the submitting Host.
        wrapper = '#!/bin/sh\nexec /usr/bin/env -i HOME="$HOME" '
        wrapper += shlex.join([f'{key}={value}' for key, value in variables.items()])
        wrapper += ' /bin/sh -c ' + shlex.quote(script) + '\n'
        return wrapper, scratch, timeout

    def _qsub_arguments(self, spec):
        # Notifications and intentional repeats belong to the managed workflow.
        args = [self.commands['qsub'], '-q', spec.metadata['queue'], '-m', 'n', '-r', 'n',
                '-o', 'logs/scheduler.stdout', '-e', 'logs/scheduler.stderr']
        resources = spec.metadata.get('resources', {})
        if self.scheduler == 'pbs':
            select = resources.get('select')
            if not select and ('cpus' in resources or 'memory_mb' in resources):
                select = '1'
                if 'cpus' in resources: select += ':ncpus=' + str(resources['cpus'])
                if 'memory_mb' in resources: select += ':mem=' + str(resources['memory_mb']) + 'mb'
            if select: args += ['-l', 'select=' + select]
        else:
            if 'cpus' in resources: args += ['-l', 'nodes=1:ppn=' + str(resources['cpus'])]
            if 'memory_mb' in resources: args += ['-l', 'mem=' + str(resources['memory_mb']) + 'mb']
        timeout = execution_timeout(spec.timeout_seconds, resources)
        if timeout is not None:
            seconds = math.ceil(timeout)
            args += ['-l', f'walltime={seconds//3600:02}:{seconds//60%60:02}:{seconds%60:02}']
        return args

    def start(self, spec: JobSpec) -> JobReceipt:
        validate_submission({key: value for key, value in spec.metadata.items() if key in SUBMISSION_FIELDS},
                            kind='remote', scheduler=self.scheduler, allowed_queues=(self.allowed_queues,))
        spec = replace(spec, job_id=spec.job_id or f"job_{uuid.uuid4().hex}")
        if (spec.cwd / 'receipt.json').exists() or (spec.cwd / 'spec.json').exists():
            raise ValueError('job directory already contains an execution; reconcile instead of resubmitting')
        remote_dir = self._remote_dir(spec)
        wrapper, scratch, timeout = self._wrapper(spec, remote_dir)
        probe = self.probe(spec)
        if not probe['available']:
            raise RuntimeError(f"remote platform unavailable: {probe.get('error') or 'probe failed'}")
        if not probe['cwd_exists']:
            raise FileNotFoundError(f"job cwd does not exist: {spec.cwd}")
        if not probe['inputs_present']:
            raise FileNotFoundError(f"job inputs missing: {probe['missing_inputs']}")
        metadata = {**spec.metadata, 'remote_dir': remote_dir, 'scratch_path': scratch, 'execution_timeout_seconds': timeout}
        self._write(spec.cwd / 'spec.json', {
            'command': list(spec.command), 'cwd': str(spec.cwd), 'remote_dir': remote_dir,
            'outputs': [output.__dict__ for output in spec.outputs],
            'timeout_seconds': spec.timeout_seconds, 'metadata': metadata,
            'workspace_id': spec.workspace_id,
        })
        self.stage_inputs(spec)
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', delete=False) as handle:
            handle.write(wrapper)
            local_wrapper = Path(handle.name)
        try:
            self._rsync(local_wrapper, remote_dir + '/.research-agent/run.sh')
        finally:
            local_wrapper.unlink(missing_ok=True)
        qsub = shlex.join(self._qsub_arguments(spec))
        result = self._run_ssh(f"cd {shlex.quote(remote_dir)} && chmod 700 .research-agent/run.sh && {qsub} .research-agent/run.sh > scheduler.id && cat scheduler.id")
        scheduler_id = result.stdout.strip().splitlines()[-1].strip() if result.stdout.strip() else ''
        if not re.fullmatch(r'[A-Za-z0-9_.\[\]-]+', scheduler_id):
            raise RuntimeError('qsub returned no valid scheduler id; reconcile before retrying')
        receipt = JobReceipt(spec.job_id, self.name, _now(), spec.command, str(spec.cwd), None,
                             {**metadata, 'scheduler_id': scheduler_id}, spec.workspace_id)
        self._write(spec.cwd / 'receipt.json', receipt.__dict__)
        self._write(spec.cwd / 'remote.json', {'scheduler_id': scheduler_id, 'remote_dir': remote_dir})
        return receipt

    def recover_receipt(self, job_id: str, cwd: Path) -> JobReceipt | None:
        """Recover a qsub response lost after remote acceptance, without resubmitting."""
        spec = json.loads((cwd / "spec.json").read_text())
        # Old submitted specs predate scoped directories; recover only their
        # original location, never resubmit or rewrite that historical identity.
        remote_dir = spec.get("remote_dir", f"{self.remote_root}/{job_id}")
        result = self._run_ssh(f"cat {shlex.quote(remote_dir + '/scheduler.id')}", check=False)
        if result.returncode or not result.stdout.strip(): return None
        scheduler_id = result.stdout.strip().splitlines()[-1]
        if not re.fullmatch(r"[A-Za-z0-9_.\[\]-]+", scheduler_id):
            raise ValueError("invalid recovered scheduler identity")
        receipt = JobReceipt(job_id, self.name, _now(), tuple(spec["command"]), str(cwd), None,
            {**spec.get("metadata", {}), "scheduler_id":scheduler_id, "remote_dir":remote_dir,
             "recovered":True, "submitted_at_unknown":True},
            spec.get("workspace_id"))
        self._write(cwd / "receipt.json", receipt.__dict__)
        return receipt

    def _scheduler_details(self, receipt):
        scheduler_id = str(receipt.metadata["scheduler_id"])
        result = self._run_ssh(f"{shlex.quote(self.commands['qstat'])} -f {shlex.quote(scheduler_id)}", check=False)
        details = {"scheduler_id":scheduler_id, "observed_at":_now(), "source":"qstat -f"}
        if result.returncode:
            details["query_error"] = result.stderr.strip()[:2000] or "scheduler record unavailable"
            details["record_missing"] = (result.returncode != 255 and
                                         bool(re.search(r'\bUnknown Job Id\b', result.stderr, re.IGNORECASE)))
            return None, details
        fields = dict(re.findall(r"(?m)^\s*([A-Za-z_.]+)\s*=\s*(.*?)\s*$", result.stdout))
        state = fields.get("job_state")
        details.update(scheduler_state=state, queue=fields.get("queue"), scheduler_comment=fields.get("comment"))
        try:
            details["wait_seconds"] = max(0, int((datetime.now(timezone.utc) - datetime.fromisoformat(receipt.submitted_at)).total_seconds())) if state in {"Q", "W", "H"} else None
        except (ValueError, TypeError):
            details["wait_seconds"] = None
        if fields.get("exit_status") is not None: details["exit_status"] = int(fields["exit_status"])
        if state in {"Q", "W", "H"} and self.diagnostic_command:
            try:
                diagnosis = self._run_ssh(f"{shlex.quote(self.diagnostic_command)} {shlex.quote(scheduler_id.split('.')[0])}", check=False)
                details["queue_diagnosis"] = (diagnosis.stdout if diagnosis.returncode == 0 else diagnosis.stderr).strip()[:8000]
                details["diagnosis_source"] = "checkjob"
            except (OSError, subprocess.SubprocessError) as error:
                # Optional diagnosis must not erase authoritative scheduler state.
                details["diagnosis_error"] = str(error)[:2000]
        return state, details

    def status(self, receipt: JobReceipt) -> JobStatus:
        local_status = Path(receipt.cwd) / "status.json"
        if local_status.is_file():
            try:
                saved = json.loads(local_status.read_text(encoding="utf-8"))
                if saved.get("job_id") == receipt.job_id and saved.get("state") in {item.value for item in JobState}:
                    restored = JobStatus(receipt.job_id, JobState(saved["state"]), self.name, exit_code=saved.get("exit_code"), finished_at=saved.get("finished_at"), error=saved.get("error"), diagnostics=saved.get("diagnostics", {}))
                    if restored.state in {JobState.SUCCEEDED, JobState.FAILED, JobState.TIMED_OUT, JobState.CANCELLED, JobState.COLLECTED}:
                        return restored
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                pass
        scheduler_id = str(receipt.metadata.get("scheduler_id", ""))
        remote_dir = str(receipt.metadata.get("remote_dir", ""))
        if not scheduler_id or not remote_dir:
            return JobStatus(receipt.job_id, JobState.UNKNOWN, self.name, error="remote receipt is incomplete")
        try:
            result = self._run_ssh(
                f"test -f {shlex.quote(remote_dir + '/status.exit')} && {{ "
                f"cat {shlex.quote(remote_dir + '/status.state')} 2>/dev/null; cat {shlex.quote(remote_dir + '/status.exit')}; }}",
                check=False,
            )
            if result.returncode != 0:
                scheduler_state, diagnostics = self._scheduler_details(receipt)
                if self._cancellation_acknowledged(receipt):
                    diagnostics['cancellation_requested'] = True
                    if scheduler_state in {'C', 'F'} or diagnostics.get('record_missing'):
                        terminal = JobStatus(receipt.job_id, JobState.CANCELLED, self.name,
                                             exit_code=diagnostics.get('exit_status'), finished_at=_now(),
                                             diagnostics=diagnostics)
                        self._persist(receipt, terminal)
                        return terminal
                if scheduler_state in {"C", "F"} and diagnostics.get("exit_status") is not None:
                    code = diagnostics["exit_status"]
                    terminal = JobStatus(receipt.job_id, JobState.SUCCEEDED if code == 0 else JobState.FAILED,
                        self.name, exit_code=code, finished_at=_now(), diagnostics=diagnostics,
                        error="Job exit receipt absent; exit status recovered from scheduler (check working directory and scheduler logs)")
                    self._persist(receipt, terminal)
                    return terminal
                mapped = {"Q":JobState.QUEUED, "W":JobState.QUEUED, "H":JobState.HELD,
                          "R":JobState.RUNNING, "E":JobState.RUNNING, "T":JobState.SUBMITTED}.get(scheduler_state, JobState.UNKNOWN)
                return JobStatus(receipt.job_id, mapped, self.name, diagnostics=diagnostics,
                    error=(diagnostics.get("query_error") or "scheduler outcome unknown; exit receipt absent") if mapped == JobState.UNKNOWN else None)
            code = int(result.stdout.strip().splitlines()[-1])
            state = (JobState.TIMED_OUT if result.stdout.strip().splitlines()[0] == "timed_out"
                     else JobState.SUCCEEDED if code == 0 else JobState.FAILED)
            terminal = JobStatus(receipt.job_id, state, self.name, exit_code=code, finished_at=_now())
            self._persist(receipt, terminal)
            return terminal
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            return JobStatus(receipt.job_id, JobState.UNKNOWN, self.name, error=str(exc))

    def collect(self, receipt: JobReceipt) -> dict[str, Any]:
        status = self.status(receipt)
        if status.state in {JobState.RUNNING, JobState.UNKNOWN, JobState.QUEUED, JobState.HELD, JobState.SUBMITTED}:
            raise RuntimeError(f"job {receipt.job_id} is not complete: {status.state}")
        root = Path(receipt.cwd)
        remote_dir = str(receipt.metadata["remote_dir"])
        self._rsync(root, remote_dir, pull=True)
        spec_path = root / "spec.json"
        declared = json.loads(spec_path.read_text(encoding="utf-8")).get("outputs", []) if spec_path.is_file() else []
        outputs, validation = collect_outputs(root, declared)
        return {
            "job_id": receipt.job_id, "status": status.__dict__, "outputs": outputs, "output_validation": validation,
            "stdout": str(root / "logs" / "stdout.log"), "stderr": str(root / "logs" / "stderr.log"),
        }

    def fetch_outputs(self, receipt: JobReceipt) -> dict[str, Any]:
        return self.collect(receipt)

    def cancel(self, receipt: JobReceipt) -> JobStatus:
        current = self.status(receipt)
        if current.state in {JobState.SUCCEEDED,JobState.FAILED,JobState.CANCELLED,JobState.TIMED_OUT}: return current
        if self._cancellation_acknowledged(receipt):
            return current
        scheduler_id = str(receipt.metadata.get("scheduler_id", ""))
        if scheduler_id:
            result = self._run_ssh(f"{shlex.quote(self.commands['qdel'])} {shlex.quote(scheduler_id)}", check=False)
            if result.returncode: return JobStatus(receipt.job_id, JobState.UNKNOWN, self.name, error="scheduler did not confirm cancellation")
        else:
            return JobStatus(receipt.job_id, JobState.UNKNOWN, self.name, error="scheduler identity missing")
        # qdel acknowledges a request, not process termination. Preserve that
        # fact across restarts and wait for a terminal/missing scheduler record.
        self._write(Path(receipt.cwd) / 'cancel.request', {
            'schema_version': 'remote-cancellation/1', 'scheduler_id': scheduler_id,
            'acknowledged_at': _now(),
        })
        return self.status(receipt)

    @staticmethod
    def _cancellation_acknowledged(receipt):
        try:
            value = json.loads((Path(receipt.cwd) / 'cancel.request').read_text())
            return (value.get('schema_version') == 'remote-cancellation/1' and
                    value.get('scheduler_id') == receipt.metadata.get('scheduler_id'))
        except (OSError, ValueError, AttributeError):
            return False

    @staticmethod
    def _persist(receipt: JobReceipt, status: JobStatus) -> None:
        TorqueSSHPlatform._write(Path(receipt.cwd) / 'status.json', {
            'job_id': status.job_id, 'state': status.state.value,
            'platform': status.platform, 'exit_code': status.exit_code,
            'started_at': status.started_at, 'finished_at': status.finished_at,
            'error': status.error, 'diagnostics': dict(status.diagnostics),
        })

    @staticmethod
    def _write(path: Path, value: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile('w', dir=path.parent, prefix='.' + path.name, delete=False) as stream:
            temporary = Path(stream.name)
            try:
                json.dump(value, stream, indent=2, default=str)
                stream.flush()
                os.fsync(stream.fileno())
                os.replace(temporary, path)
            finally:
                temporary.unlink(missing_ok=True)

    @staticmethod
    def receipt_from_disk(path: str | Path) -> JobReceipt:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        return JobReceipt(
            job_id=str(value["job_id"]), platform=str(value["platform"]),
            submitted_at=str(value["submitted_at"]), command=tuple(value["command"]),
            cwd=str(value["cwd"]), pid=value.get("pid"), metadata=value.get("metadata", {}),
            workspace_id=value.get("workspace_id"),
        )
