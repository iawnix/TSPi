"""Small, dependency-free terminal UI shared by installation commands."""

from __future__ import annotations

import os
import sys
import threading
from typing import TextIO

# Python only wires GNU readline into ``input`` when the module is imported.
# Keep this optional so the installer remains usable on platforms without it.
try:
    import readline  # noqa: F401
except ImportError:
    readline = None  # type: ignore[assignment]


RESET = "\033[0m"
COLORS = {
    "brand": "\033[1;36m",
    "accent": "\033[36m",
    "success": "\033[1;32m",
    "warning": "\033[1;33m",
    "danger": "\033[1;31m",
    "muted": "\033[2m",
    "bold": "\033[1m",
}


def colors_enabled(stream: TextIO | None = None) -> bool:
    stream = stream or sys.stdout
    if "NO_COLOR" in os.environ or os.environ.get("TERM") == "dumb":
        return False
    if os.environ.get("FORCE_COLOR", "").lower() not in {"", "0", "false", "no"}:
        return True
    return bool(getattr(stream, "isatty", lambda: False)())


def animations_enabled(stream: TextIO | None = None) -> bool:
    stream = stream or sys.stderr
    return os.environ.get("TERM") != "dumb" and bool(getattr(stream, "isatty", lambda: False)())


def paint(value: object, tone: str, *, stream: TextIO | None = None) -> str:
    text = str(value)
    if tone not in COLORS or not colors_enabled(stream):
        return text
    return f"{COLORS[tone]}{text}{RESET}"


def title(value: str, subtitle: str, *, tone: str = "brand", stream: TextIO | None = None) -> None:
    stream = stream or sys.stdout
    print(file=stream)
    print(paint(value, tone, stream=stream), file=stream)
    print(paint("=" * len(value), "muted", stream=stream), file=stream)
    print(subtitle, file=stream)


def section(value: str, *, stream: TextIO | None = None) -> None:
    stream = stream or sys.stdout
    print(file=stream)
    print(paint(value, "bold", stream=stream), file=stream)
    print(paint("-" * len(value), "muted", stream=stream), file=stream)


def field(label: str, value: object, *, tone: str = "", stream: TextIO | None = None) -> None:
    stream = stream or sys.stdout
    rendered = paint(value, tone, stream=stream) if tone else str(value)
    print(f"  {label:<20} {rendered}", file=stream)


def note(value: str, *, tone: str = "muted", stream: TextIO | None = None) -> None:
    stream = stream or sys.stdout
    print(f"  {paint(value, tone, stream=stream)}", file=stream)


def success(value: str, *, stream: TextIO | None = None) -> None:
    stream = stream or sys.stdout
    print(file=stream)
    print(paint(value, "success", stream=stream), file=stream)


def failure(value: str, *, stream: TextIO | None = None) -> None:
    stream = stream or sys.stderr
    print(paint(value, "danger", stream=stream), file=stream)


def ask_text(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    label = f"  {prompt}" + paint(suffix, "muted") + ": "
    value = input(label).strip()
    return value or default


def ask_yes_no(prompt: str, default: bool = True) -> bool:
    marker = "Y/n" if default else "y/N"
    label = f"  {prompt} " + paint(f"[{marker}]", "muted") + ": "
    while True:
        value = input(label).strip().lower()
        if not value:
            return default
        if value in {"y", "yes"}:
            return True
        if value in {"n", "no"}:
            return False
        note("Please answer y or n.", tone="warning")


class Spinner:
    """A transient TTY spinner with stable line output for non-TTY streams."""

    _frames = ("|", "/", "-", "\\")

    def __init__(
        self,
        message: str,
        *,
        stream: TextIO | None = None,
        enabled: bool = True,
        interval: float = 0.12,
    ) -> None:
        self.message = message
        self.stream = stream or sys.stderr
        self.enabled = enabled
        self.interval = interval
        self.animated = enabled and animations_enabled(self.stream)
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._active = False
        self._last_stable_message: str | None = None

    def __enter__(self) -> Spinner:
        self.start()
        return self

    def __exit__(self, exception_type, _exception, _traceback) -> None:
        if not self._active:
            return
        if exception_type is None:
            self.succeed()
        else:
            self.fail()

    def start(self) -> None:
        if self._active or not self.enabled:
            return
        self._active = True
        if not self.animated:
            self._write_stable(self.message)
            return
        self._render(self._frames[0])
        self._thread = threading.Thread(target=self._animate, daemon=True)
        self._thread.start()

    def update(self, message: str) -> None:
        with self._lock:
            if message == self.message:
                return
            self.message = message
            if self._active and not self.animated:
                self._write_stable(message)

    def succeed(self, message: str | None = None) -> None:
        self._finish(message, "OK", "success")

    def fail(self, message: str | None = None) -> None:
        self._finish(message, "FAILED", "danger")

    def _animate(self) -> None:
        index = 1
        while not self._stop.wait(self.interval):
            self._render(self._frames[index % len(self._frames)])
            index += 1

    def _render(self, frame: str) -> None:
        with self._lock:
            self.stream.write(f"\r\033[2K  {paint(frame, 'accent', stream=self.stream)} {self.message}")
            self.stream.flush()

    def _write_stable(self, message: str) -> None:
        if message == self._last_stable_message:
            return
        print(f"  {message}", file=self.stream, flush=True)
        self._last_stable_message = message

    def _finish(self, message: str | None, marker: str, tone: str) -> None:
        if not self._active:
            return
        if message is not None:
            with self._lock:
                self.message = message
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
        if self.animated:
            with self._lock:
                self.stream.write("\r\033[2K")
                print(f"  {paint(marker, tone, stream=self.stream)} {self.message}", file=self.stream, flush=True)
        self._active = False
