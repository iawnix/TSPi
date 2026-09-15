"""Small, dependency-free terminal UI shared by installation commands."""

from __future__ import annotations

import os
import sys
from typing import TextIO


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
    label = paint("?", "accent") + f" {prompt}" + paint(suffix, "muted") + ": "
    value = input(label).strip()
    return value or default


def ask_yes_no(prompt: str, default: bool = True) -> bool:
    marker = "Y/n" if default else "y/N"
    label = paint("?", "accent") + f" {prompt} " + paint(f"[{marker}]", "muted") + ": "
    while True:
        value = input(label).strip().lower()
        if not value:
            return default
        if value in {"y", "yes"}:
            return True
        if value in {"n", "no"}:
            return False
        note("Please answer y or n.", tone="warning")
