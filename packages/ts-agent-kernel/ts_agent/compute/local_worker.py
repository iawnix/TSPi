"""Worker process used by :mod:`ts_agent.compute.local_lifecycle`."""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
from pathlib import Path
from typing import Any

from ts_agent.io import now_iso, read_json, write_json


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ts-local-worker")
    parser.add_argument("--config", required=True)
    args = parser.parse_args(argv)
    config = read_json(Path(args.config))
    if not isinstance(config, dict):
        raise SystemExit("local worker configuration must be an object")
    return run(config)


def run(config: dict[str, Any]) -> int:
    status_path = Path(str(config["status_path"]))
    command = [str(item) for item in config["command"]]
    environment = {str(key): str(value) for key, value in config.get("environment", {}).items()}
    child: subprocess.Popen[bytes] | None = None
    stop_requested = False

    write_json(
        Path(str(config["receipt_path"])),
        {
            "schema_version": "ts-local-receipt/1",
            "intent_id": str(config["intent_id"]),
            "job_id": f"local-{config['intent_id']}",
            "pid": os.getpid(),
            "process_start": _process_start_token(os.getpid()),
            "command": command,
            "expected_artifacts": [str(item) for item in config.get("expected_artifacts", [])],
            "submitted_at": now_iso(),
        },
    )

    def stop(_signum: int, _frame: Any) -> None:
        nonlocal stop_requested
        stop_requested = True
        if child is not None and child.poll() is None:
            try:
                child.terminate()
            except ProcessLookupError:
                pass

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    _write_status(status_path, "running", None, None)
    stdin = None
    stdout = None
    stderr = None
    stdin_path = config.get("stdin_path")
    try:
        if stdin_path:
            source = Path(str(stdin_path))
            if source.is_symlink() or not source.is_file():
                raise OSError("local worker stdin must be a regular file")
            stdin = source.open("rb")
        stdout = Path(str(config["stdout_path"])).open("ab")
        stderr = Path(str(config["stderr_path"])).open("ab")
        child = subprocess.Popen(
            command,
            cwd=str(config["run_dir"]),
            env={**os.environ, **environment},
            stdin=stdin if stdin is not None else subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            close_fds=True,
        )
        if stop_requested:
            child.terminate()
        exit_status = child.wait()
    except OSError as exc:
        if stderr is not None:
            stderr.write((f"local worker failed to start command: {exc}\n").encode("utf-8", errors="replace"))
            stderr.flush()
        exit_status = 127
    finally:
        if stdout is not None:
            stdout.close()
        if stderr is not None:
            stderr.close()
        if stdin is not None:
            stdin.close()
    if stop_requested:
        state, program_status = "stopped", "stopped"
    elif exit_status == 0:
        state, program_status = "completed", "completed"
    else:
        state, program_status = "failed", "failed"
    _write_status(status_path, state, program_status, exit_status)
    return 0 if state == "completed" else 1


def _write_status(path: Path, state: str, program_status: str | None, exit_status: int | None) -> None:
    write_json(
        path,
        {
            "schema_version": "ts-local-worker-status/1",
            "state": state,
            "program_status": program_status or "not_run",
            "exit_status": exit_status,
            "pid": os.getpid(),
            "observed_at": now_iso(),
        },
    )


def _process_start_token(pid: int) -> str | None:
    try:
        fields = Path(f"/proc/{pid}/stat").read_text(encoding="ascii").split()
        return fields[21]
    except (OSError, IndexError, ValueError):
        return None


if __name__ == "__main__":
    raise SystemExit(main())
