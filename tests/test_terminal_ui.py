from __future__ import annotations

import io
import time

from scripts import _terminal_ui as ui


class TerminalBuffer(io.StringIO):
    def isatty(self) -> bool:
        return True


def test_terminal_ui_uses_semantic_colors_on_a_tty(monkeypatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("TERM", raising=False)
    stream = TerminalBuffer()

    ui.field("State", "Ready", tone="success", stream=stream)
    ui.failure("Failed", stream=stream)

    output = stream.getvalue()
    assert "\033[1;32mReady\033[0m" in output
    assert "\033[1;31mFailed\033[0m" in output


def test_no_color_disables_ansi_even_on_a_tty(monkeypatch) -> None:
    monkeypatch.setenv("NO_COLOR", "")
    stream = TerminalBuffer()

    ui.title("TSPi Installer", "Configure TSPi.", stream=stream)

    assert "\033[" not in stream.getvalue()


def test_confirmation_defaults_are_explicit(monkeypatch) -> None:
    replies = iter(["", ""])
    monkeypatch.setattr("builtins.input", lambda _: next(replies))

    assert ui.ask_yes_no("Proceed", True) is True
    assert ui.ask_yes_no("Delete data", False) is False


def test_prompts_do_not_use_an_ambiguous_question_mark(monkeypatch) -> None:
    labels = []
    replies = iter(["", ""])
    monkeypatch.setattr("builtins.input", lambda label: labels.append(label) or next(replies))

    assert ui.ask_text("Installation directory", "/tmp/tspi") == "/tmp/tspi"
    assert ui.ask_yes_no("Proceed", True) is True

    assert all("?" not in label for label in labels)
    assert labels[0].startswith("  Installation directory")


def test_spinner_animates_on_a_tty_and_finishes_on_one_status_line(monkeypatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("TERM", raising=False)
    stream = TerminalBuffer()

    with ui.Spinner("Preparing release", stream=stream, interval=0.005) as activity:
        time.sleep(0.015)
        activity.update("Activating release")
        time.sleep(0.01)
        activity.succeed("Release ready")

    output = stream.getvalue()
    assert "\r\033[2K" in output
    assert "Preparing release" in output
    assert "Release ready" in output
    assert "\033[1;32mOK\033[0m" in output


def test_spinner_uses_stable_progress_without_terminal_control_codes() -> None:
    stream = io.StringIO()

    with ui.Spinner("Preparing release", stream=stream) as activity:
        activity.update("Activating release")

    output = stream.getvalue()
    assert output.splitlines() == ["  Preparing release", "  Activating release"]
    assert "\033[" not in output
