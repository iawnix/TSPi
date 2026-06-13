"""Unified CLI output, diagnostics, and error handling.

Every command-line tool in this package shares one convention, enforced here so
no tool re-implements it:

* **stdout** carries the machine-readable result, always emitted by
  :func:`emit_json` (one place owns JSON formatting: ASCII, sorted keys, indent).
* **stderr** carries diagnostics (:func:`log`, :func:`warn`) and, on failure, a
  one-line JSON error envelope written by :func:`run_cli`.
* A tool signals a user-facing failure by raising :class:`CliError`; the
  :func:`run_cli` wrapper turns it into the error envelope plus a stable exit
  code, so individual ``main`` functions never call ``sys.exit`` with ad-hoc
  numbers or print error text by hand.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any, Callable

EXIT_OK = 0
EXIT_ERROR = 2


class CliError(Exception):
    """A user-facing CLI failure carrying a stable exit code.

    Raise this (instead of printing and returning a number) for any error the
    user should see. :func:`run_cli` renders it as the standard error envelope.
    """

    def __init__(self, message: str, *, exit_code: int = EXIT_ERROR) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def configure_cli_logging(*, verbose: bool = False, quiet: bool = False) -> logging.Logger:
    """Configure stderr logging for command-line tools.

    Machine-readable command output goes to stdout via :func:`emit_json`; logs,
    warnings, and diagnostics go to stderr through this logger. ``quiet=True``
    raises the package level to WARNING, so informational diagnostics are
    hidden but warnings remain visible. ``verbose=True`` lowers it to DEBUG.
    Tools that never call this still get INFO-level output on stderr via the
    bootstrap handler installed at import.
    """

    # quiet -> hide informational ``log()`` lines but keep ``warn()`` visible.
    # verbose -> include DEBUG. Default -> INFO and up.
    level = logging.WARNING if quiet else (logging.DEBUG if verbose else logging.INFO)
    _LOGGER.setLevel(level)
    logging.basicConfig(
        level=level,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
        force=True,
    )
    return _LOGGER


def emit_json(payload: Any, *, pretty: bool = True) -> None:
    """Write a result payload to stdout as canonical JSON.

    This is the preferred stdout result writer for the whole package.
    """

    text = json.dumps(payload, ensure_ascii=True, indent=2 if pretty else None, sort_keys=True)
    sys.stdout.write(text + "\n")


def emit_stdout(message: str = "", *, end: str = "\n", flush: bool = False) -> None:
    """Write a CLI text line to stdout.

    Most tools should prefer :func:`emit_json`; this helper exists for legacy
    text protocols such as dry-run command transcripts and long-running service
    startup messages, so stdout writes still have one package-owned path.
    """

    sys.stdout.write(message + end)
    if flush:
        sys.stdout.flush()


def emit_stderr(message: str = "", *, end: str = "\n", flush: bool = False) -> None:
    """Write a raw diagnostic line to stderr.

    Prefer :func:`log` and :func:`warn` for ordinary messages. This helper is
    for relaying already-formatted subprocess output or HTTP access-log lines
    without adding another prefix.
    """

    sys.stderr.write(message + end)
    if flush:
        sys.stderr.flush()


def relay_stdout(text: str | None) -> None:
    """Relay captured stdout text without changing its bytes."""

    if text:
        sys.stdout.write(text)


def relay_stderr(text: str | None) -> None:
    """Relay captured stderr text without changing its bytes."""

    if text:
        sys.stderr.write(text)


_LOGGER = logging.getLogger("transition_state_workflow")


class _LiveStderrHandler(logging.Handler):
    """Stream handler that looks up ``sys.stderr`` on every emit.

    The default :class:`logging.StreamHandler` captures the stream by value at
    construction time, so it misses test-runner redirects (e.g. pytest's
    ``capsys``) and any in-process replacement of ``sys.stderr``. This handler
    rebinds the stream per record so output always lands on the real stderr.
    """

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            sys.stderr.write(msg + "\n")
            sys.stderr.flush()
        except Exception:
            self.handleError(record)


# Bootstrap a default stderr handler so ``log`` / ``warn`` never disappear
# silently in tools that have not called ``configure_cli_logging``. The
# handler stays attached even after ``configure_cli_logging`` re-runs
# basicConfig — the package-level logger keeps emitting.
if not _LOGGER.handlers:
    _default_handler = _LiveStderrHandler()
    _default_handler.setFormatter(logging.Formatter("%(message)s"))
    _LOGGER.addHandler(_default_handler)
    _LOGGER.setLevel(logging.INFO)
    # Don't propagate to the root logger; otherwise messages may be duplicated
    # once ``configure_cli_logging`` installs root handlers via basicConfig.
    _LOGGER.propagate = False


def log(message: str) -> None:
    """Emit a human-readable diagnostic line.

    Routed through the package logger so ``--quiet`` / ``--verbose`` (configured
    by :func:`configure_cli_logging`) actually take effect. Tools that have not
    called ``configure_cli_logging`` still see the line on stderr because
    Python's default lastResort handler writes at WARNING level; using INFO
    means a quiet tool stays quiet.
    """

    _LOGGER.info(message)


def warn(message: str) -> None:
    """Emit a human-readable warning through the package logger.

    The default handler prefixes nothing; tools that want a ``warning:`` prefix
    in their output should rely on the WARNING log level the handler emits. The
    package logger writes at WARNING level even under ``quiet=True`` so
    warnings still surface.
    """

    _LOGGER.warning("warning: %s", message)


def emit_captured_streams(label: str, stdout: str | None, stderr: str | None) -> None:
    """Write captured command output to stderr for actionable failures."""

    if stdout:
        emit_stderr(f"--- {label} stdout ---")
        emit_stderr(stdout.rstrip())
    if stderr:
        emit_stderr(f"--- {label} stderr ---")
        emit_stderr(stderr.rstrip())


def _emit_error_envelope(message: str, *, exit_code: int) -> int:
    emit_stderr(json.dumps({"ok": False, "error": message}, ensure_ascii=True))
    return exit_code


def run_cli(main_func: Callable[[list[str] | None], int], argv: list[str] | None = None) -> int:
    """Run a tool ``main`` and render expected failures as the error envelope.

    ``main_func`` parses its own arguments and returns an exit code.
    :class:`CliError` (explicit user-facing failures) and ``FileNotFoundError``
    (a missing input file is almost always bad input, not a bug) are rendered as
    a one-line ``{"ok": false, "error": ...}`` envelope on stderr instead of a
    traceback. Other exceptions propagate so genuine bugs stay loud.
    """

    try:
        return main_func(argv)
    except CliError as exc:
        return _emit_error_envelope(str(exc), exit_code=exc.exit_code)
    except FileNotFoundError as exc:
        detail = exc.filename or exc.strerror or str(exc)
        return _emit_error_envelope(f"file not found: {detail}", exit_code=EXIT_ERROR)
