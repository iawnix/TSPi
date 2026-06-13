"""Unit tests for the unified CLI core (util.cli)."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "src"))

from transition_state_workflow.util.cli import (  # noqa: E402
    CliError,
    EXIT_ERROR,
    EXIT_OK,
    configure_cli_logging,
    emit_captured_streams,
    emit_json,
    emit_stderr,
    emit_stdout,
    log,
    relay_stderr,
    relay_stdout,
    run_cli,
    warn,
)


def test_emit_json_writes_canonical_ascii_to_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    emit_json({"b": 1, "a": "x"})
    captured = capsys.readouterr()
    # ASCII, sorted keys, newline-terminated.
    assert captured.out.endswith("\n")
    payload = json.loads(captured.out)
    assert payload == {"a": "x", "b": 1}
    # sort_keys is on so "a" precedes "b" textually.
    assert captured.out.index('"a"') < captured.out.index('"b"')


def test_emit_json_with_pretty_false_is_one_line(capsys: pytest.CaptureFixture[str]) -> None:
    emit_json({"a": 1, "b": 2}, pretty=False)
    captured = capsys.readouterr()
    assert "\n" in captured.out  # the trailing newline
    assert captured.out.count("\n") == 1
    assert "\n" not in captured.out.rstrip()


def test_emit_stdout_and_stderr_write_through_cli_boundary(
    capsys: pytest.CaptureFixture[str],
) -> None:
    emit_stdout("plain stdout")
    emit_stderr("plain stderr")
    captured = capsys.readouterr()
    assert captured.out == "plain stdout\n"
    assert captured.err == "plain stderr\n"


def test_relay_streams_preserve_existing_newlines(
    capsys: pytest.CaptureFixture[str],
) -> None:
    relay_stdout("out a\nout b\n")
    relay_stderr("err a\nerr b\n")
    captured = capsys.readouterr()
    assert captured.out == "out a\nout b\n"
    assert captured.err == "err a\nerr b\n"


def test_run_cli_returns_main_exit_code_on_success() -> None:
    def main(argv: list[str] | None) -> int:
        return 0

    assert run_cli(main, []) == EXIT_OK


def test_run_cli_translates_cli_error_to_envelope_on_stderr(
    capsys: pytest.CaptureFixture[str],
) -> None:
    def main(argv: list[str] | None) -> int:
        raise CliError("config went sideways")

    rc = run_cli(main, [])
    captured = capsys.readouterr()
    assert rc == EXIT_ERROR
    assert captured.out == ""  # stdout untouched
    envelope = json.loads(captured.err)
    assert envelope == {"ok": False, "error": "config went sideways"}


def test_run_cli_respects_custom_exit_code_on_cli_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    def main(argv: list[str] | None) -> int:
        raise CliError("partial result", exit_code=3)

    assert run_cli(main, []) == 3


def test_run_cli_envelope_is_one_line_even_when_emit_json_is_pretty(
    capsys: pytest.CaptureFixture[str],
) -> None:
    def main(argv: list[str] | None) -> int:
        emit_json({"k": "v"})  # pretty=True writes multi-line stdout
        raise CliError("after partial output")

    run_cli(main, [])
    captured = capsys.readouterr()
    # Pretty stdout has more than one line, but stderr envelope is one line.
    assert captured.out.count("\n") > 1
    assert captured.err.count("\n") == 1


def test_cli_error_defaults_to_exit_error_constant() -> None:
    err = CliError("boom")
    assert err.exit_code == EXIT_ERROR


def test_log_writes_to_stderr_without_configure(
    capsys: pytest.CaptureFixture[str],
) -> None:
    log("hello there")
    captured = capsys.readouterr()
    assert "hello there" in captured.err
    assert captured.out == ""


def test_warn_writes_to_stderr_with_warning_prefix(
    capsys: pytest.CaptureFixture[str],
) -> None:
    warn("something off")
    captured = capsys.readouterr()
    assert "warning: something off" in captured.err
    assert captured.out == ""


def test_emit_captured_streams_writes_labeled_blocks_to_stderr(
    capsys: pytest.CaptureFixture[str],
) -> None:
    emit_captured_streams("remote command", "stdout text\n", "stderr text\n")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "--- remote command stdout ---" in captured.err
    assert "stdout text" in captured.err
    assert "--- remote command stderr ---" in captured.err
    assert "stderr text" in captured.err


def test_quiet_mode_suppresses_log_but_keeps_warn(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_cli_logging(quiet=True)
    try:
        log("hidden")
        warn("still shown")
        captured = capsys.readouterr()
        assert "hidden" not in captured.err
        assert "still shown" in captured.err
    finally:
        # Reset to the default level so other tests are unaffected.
        configure_cli_logging()
