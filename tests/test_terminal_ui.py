from __future__ import annotations

import io

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
