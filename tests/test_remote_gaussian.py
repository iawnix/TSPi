"""Remote Gaussian: node-scoped run paths, ssh quoting, monitor wrappers."""

from __future__ import annotations

import json
import shlex
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from conftest import (
    SKILL_ROOT,
    REMOTE_GAUSSIAN_CLI,
    REMOTE_STATUS_CLI,
    REMOTE_TAIL_CLI,
    REMOTE_FETCH_CLI,
    initialize_workspace,
    run_cli,
)

from transition_state_workflow.util.cli import CliError  # noqa: E402

from transition_state_workflow.tool import run_remote_gaussian as remote_gaussian  # noqa: E402
from transition_state_workflow.tool import remote_gaussian_monitor  # noqa: E402
from transition_state_workflow.util import remote_exec  # noqa: E402


def test_run_remote_gaussian_uses_node_outputs_as_run_cwd_for_node_inputs(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    initialize_workspace(root)
    input_path = root / "nodes" / "n010_candidate" / "inputs" / "candidate.gjf"
    input_path.write_text("%chk=candidate.chk\n#p opt freq\n\n0 1\nH 0 0 0\n\n", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(REMOTE_GAUSSIAN_CLI),
            str(input_path),
            "--login-host",
            "login.example",
            "--compute-host",
            "compute-0-30",
            "--remote-dir",
            "/remote/tssearch_unit",
            "--no-run",
            "--no-download",
            "--dry-run",
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    stdout = result.stdout
    assert "RUN_DIR=/remote/tssearch_unit/nodes/n010_candidate/outputs" in stdout
    assert "INPUT=../inputs/candidate.gjf" in stdout
    assert "OUTPUT=candidate.out" in stdout
    assert "GAUSS_SCRDIR=/remote/tssearch_unit/nodes/n010_candidate/scratch/gaussian" in stdout
    assert "login.example:/remote/tssearch_unit/nodes/n010_candidate/inputs/candidate.gjf" in stdout
    assert '"$G16" < "$INPUT" > "$OUTPUT" 2> g16_driver.out' in stdout
    assert '"$G16" "$INPUT" "$OUTPUT"' not in stdout
    assert "output_exists=false" in stdout
    assert "expected Gaussian output missing or empty under outputs/" in stdout
def test_run_remote_gaussian_can_stage_stdout_in_scratch_before_copyback(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    initialize_workspace(root)
    input_path = root / "nodes" / "n010_candidate" / "inputs" / "candidate.gjf"
    input_path.write_text("%chk=candidate.chk\n#p opt freq\n\n0 1\nH 0 0 0\n\n", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(REMOTE_GAUSSIAN_CLI),
            str(input_path),
            "--login-host",
            "login.example",
            "--compute-host",
            "compute-0-30",
            "--remote-dir",
            "/remote/tssearch_unit",
            "--scratch-stdout",
            "--no-run",
            "--no-download",
            "--dry-run",
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    stdout = result.stdout
    assert "SCRATCH_STDOUT=true" in stdout
    assert 'echo "scratch_stdout=$SCRATCH_STDOUT"' in stdout
    assert 'STDOUT_SCRATCH_DIR="$GAUSS_SCRDIR/stdout"' in stdout
    assert '"$G16" < "$INPUT" > "$SCRATCH_OUTPUT" 2> "$SCRATCH_DRIVER"' in stdout
    assert 'mv -f "$OUTPUT.tmp" "$OUTPUT"' in stdout
    assert "candidate.out.tmp" not in stdout
def test_remote_dir_with_space_is_quoted_in_mkdir_and_scp(tmp_path: Path) -> None:
    # Regression: remote mkdir/chmod once passed unquoted paths through ssh, so a
    # remote dir with a space or shell metacharacter would split into extra args
    # or be interpreted by the remote shell. Every remote path must be quoted.
    root = tmp_path / "tssearch_unit"
    initialize_workspace(root)
    input_path = root / "nodes" / "n010_candidate" / "inputs" / "candidate.gjf"
    input_path.write_text("%chk=candidate.chk\n#p opt freq\n\n0 1\nH 0 0 0\n\n", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(REMOTE_GAUSSIAN_CLI),
            str(input_path),
            "--login-host",
            "login.example",
            "--compute-host",
            "compute-0-30",
            "--remote-dir",
            "/remote/has space",
            "--no-run",
            "--no-download",
            "--dry-run",
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    stdout = result.stdout
    # The bare unquoted directory must never appear as an argv token that the
    # remote shell could split; it must be shlex-quoted everywhere.
    assert "'/remote/has space" in stdout
    # mkdir runs as a single bash -lc snippet, not as raw ssh argv tokens.
    assert "mkdir -p" in stdout


def test_nested_compute_ssh_quotes_shell_metacharacters_as_compute_command() -> None:
    args = SimpleNamespace(
        ssh_config=Path("/tmp/ssh config"),
        login_host="login.example",
        compute_host="compute-0-30",
        dry_run=True,
    )
    remote_command = (
        "cd /remote/tssearch unit/nodes/n010/outputs && "
        "nohup bash ./run_gaussian_on_compute.sh > runner.nohup 2>&1 < /dev/null & "
        "echo $!"
    )

    argv = remote_gaussian.nested_compute_ssh_argv(args, remote_command)

    assert argv[:4] == ["ssh", "-F", "/tmp/ssh config", "login.example"]
    assert len(argv) == 5
    login_shell_command = argv[-1]
    login_argv = shlex.split(login_shell_command)
    assert login_argv[:3] == ["ssh", "compute-0-30", "--"]
    assert len(login_argv) == 4
    assert login_argv[3].startswith("bash -lc ")
    assert shlex.quote(remote_command) in login_argv[3]
    assert "&&" in login_shell_command
    assert "2>&1" in login_shell_command
    assert "$!" in login_shell_command
    assert login_shell_command != remote_command
def test_remote_exec_uses_subprocess_without_shell() -> None:
    source = (SKILL_ROOT / "src" / "transition_state_workflow" / "remote" / "exec.py").read_text(
        encoding="utf-8"
    )
    forbidden = ["os." + "system", "shell" + "=" + "True"]
    for pattern in forbidden:
        assert pattern not in source
    assert "subprocess.run" in source
def test_skill_python_code_avoids_os_system_and_shell_true() -> None:
    python_files = [
        *sorted((SKILL_ROOT / "src").rglob("*.py")),
        *sorted((SKILL_ROOT / "scripts").glob("*.py")),
    ]
    offenders: list[str] = []
    forbidden = ["os." + "system", "shell" + "=" + "True"]
    for path in python_files:
        text = path.read_text(encoding="utf-8")
        if any(pattern in text for pattern in forbidden):
            offenders.append(str(path.relative_to(SKILL_ROOT)))
    assert offenders == []
def test_gaussian_profile_safe_runner_uses_redirection_into_outputs() -> None:
    text = (SKILL_ROOT / "templates" / "gaussian_profile_safe_runner.sh").read_text(encoding="utf-8")
    assert '"$G16" < "$INPUT" > "$OUTPUT" 2> g16_driver.out' in text
    assert '"$G16" "$INPUT" "$OUTPUT"' not in text
    assert "expected Gaussian output missing or empty under outputs/" in text
def test_gaussian_displacement_endpoint_runner_uses_outputs_redirection_and_metadata() -> None:
    text = (SKILL_ROOT / "templates" / "gaussian_displacement_endpoint_parallel_runner.sh").read_text(
        encoding="utf-8"
    )
    assert 'local run_dir="${NODE_DIR}/outputs"' in text
    assert '"$G16" < "$input" > "$output" 2> "$driver"' in text
    assert '"$G16" "$input" "$output"' not in text
    assert 'local metadata="run_metadata.${name}.txt"' in text
    assert "expected Gaussian output missing or empty under outputs/" in text
    assert "[[ -s \"$output\" ]]" in text
def test_remote_gaussian_monitor_builds_node_scoped_status_tail_and_fetch_commands() -> None:
    layout = remote_gaussian_monitor.RemoteNodeLayout(
        remote_root="/remote/tssearch_unit",
        node_id="n010_candidate",
        remote_outputs_dir="/remote/tssearch_unit/nodes/n010_candidate/outputs",
    )

    status = remote_gaussian_monitor.status_command(layout)
    assert "RUN_DIR=/remote/tssearch_unit/nodes/n010_candidate/outputs" in status
    assert "run_metadata.*.txt" in status
    assert "submit_receipt remote_pid" in status
    assert "kill -0" in status

    tail = remote_gaussian_monitor.tail_command(layout, filename="auto", lines=25)
    assert "LINES=25" in tail
    assert "find . -maxdepth 1 -type f -name '*.out'" in tail
    assert "tail_file=$TARGET" in tail

    fetch = remote_gaussian_monitor.fetch_list_command(layout, list(remote_gaussian_monitor.DEFAULT_FETCH_PATTERNS))
    assert "cd \"$RUN_DIR\"" in fetch
    assert "-name '*.out'" in fetch
    assert "-name 'run_metadata*.txt'" in fetch
    assert "-printf '%f\\n'" in fetch
def test_remote_status_tail_fetch_wrappers_expose_help() -> None:
    for script in (REMOTE_STATUS_CLI, REMOTE_TAIL_CLI, REMOTE_FETCH_CLI):
        result = subprocess.run(
            [sys.executable, str(script), "--help"],
            check=True,
            text=True,
            capture_output=True,
        )
        assert "--root" in result.stdout
        assert "--node" in result.stdout
        assert "--login-host" in result.stdout
def test_submit_background_writes_receipt_and_verifies_startup(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = SimpleNamespace(
        ssh_config=None,
        login_host="login.example",
        compute_host="compute-0-30",
        dry_run=False,
    )
    layout = remote_gaussian.GaussianRunLayout(
        remote_run_dir="/remote/tssearch_unit/nodes/n010_candidate/outputs",
        remote_input_dir="/remote/tssearch_unit/nodes/n010_candidate/inputs",
        remote_scratch_dir="/remote/tssearch_unit/nodes/n010_candidate/scratch/gaussian",
        remote_input_ref="../inputs/candidate.gjf",
        output_name="candidate.out",
        local_download_dir=Path("/tmp/unused"),
    )
    calls: list[list[str]] = []

    def fake_run(
        argv: list[str],
        *,
        check: bool,
        text: bool,
        capture_output: bool,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        assert check is True
        assert text is True
        assert capture_output is True
        if len(calls) == 1:
            command = argv[-1]
            assert shlex.split(command)[:3] == ["ssh", "compute-0-30", "--"]
            assert shlex.split(command)[3].startswith("bash -lc ")
            assert "rm -f runner.nohup run_metadata.txt" in command
            assert "submit_receipt.txt" in command
            assert "nohup bash ./run_gaussian_on_compute.sh > runner.nohup" in command
            return subprocess.CompletedProcess(argv, 0, stdout="23932\n", stderr="submit stderr\n")
        command = argv[-1]
        assert shlex.split(command)[:3] == ["ssh", "compute-0-30", "--"]
        assert shlex.split(command)[3].startswith("bash -lc ")
        assert "submit_receipt.txt" in command
        assert "runner.nohup" in command
        assert "run_metadata.txt" in command
        assert "remote_pid" in command
        assert "kill -0" in command
        return subprocess.CompletedProcess(argv, 0, stdout="verified\n", stderr="")

    monkeypatch.setattr(remote_exec.subprocess, "run", fake_run)

    assert remote_gaussian.submit_background(args, layout, "run_gaussian_on_compute.sh") == 0
    assert len(calls) == 2
    captured = capsys.readouterr()
    assert "poll:  ssh login.example " in captured.out
    assert "ssh compute-0-30 --" in captured.out
    assert "bash -lc" in captured.out
    assert ("ssh compute-" + "0-30 " + '"') not in captured.out
def test_submit_background_failure_prints_submit_and_verify_streams(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = SimpleNamespace(
        ssh_config=None,
        login_host="login.example",
        compute_host="compute-0-30",
        dry_run=False,
    )
    layout = remote_gaussian.GaussianRunLayout(
        remote_run_dir="/remote/tssearch_unit/nodes/n010_candidate/outputs",
        remote_input_dir="/remote/tssearch_unit/nodes/n010_candidate/inputs",
        remote_scratch_dir="/remote/tssearch_unit/nodes/n010_candidate/scratch/gaussian",
        remote_input_ref="../inputs/candidate.gjf",
        output_name="candidate.out",
        local_download_dir=Path("/tmp/unused"),
    )
    calls: list[list[str]] = []

    def fake_run(
        argv: list[str],
        *,
        check: bool,
        text: bool,
        capture_output: bool,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        assert check is True
        assert text is True
        assert capture_output is True
        if len(calls) == 1:
            return subprocess.CompletedProcess(argv, 0, stdout="23932\n", stderr="submit stderr\n")
        raise subprocess.CalledProcessError(
            87,
            argv,
            output="verify stdout\n",
            stderr="verify stderr\n",
        )

    monkeypatch.setattr(remote_exec.subprocess, "run", fake_run)

    with pytest.raises(CliError, match="could not verify runner.nohup or run_metadata.txt"):
        remote_gaussian.submit_background(args, layout, "run_gaussian_on_compute.sh")

    captured = capsys.readouterr()
    assert "--- background startup verification stdout ---" in captured.err
    assert "verify stderr" in captured.err
    assert "--- background submit stderr ---" in captured.err
    assert "submit stderr" in captured.err
    assert len(calls) == 2
def test_run_remote_gaussian_rejects_flat_legacy_inputs(tmp_path: Path) -> None:
    input_path = tmp_path / "flat.gjf"
    input_path.write_text("%chk=flat.chk\n#p opt freq\n\n0 1\nH 0 0 0\n\n", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(REMOTE_GAUSSIAN_CLI),
            str(input_path),
            "--login-host",
            "login.example",
            "--compute-host",
            "compute-0-30",
            "--remote-dir",
            "/remote/flat",
            "--no-run",
            "--no-download",
            "--dry-run",
        ],
        text=True,
        capture_output=True,
    )

    assert result.returncode != 0
    assert "nodes/<node_id>/inputs" in result.stderr
