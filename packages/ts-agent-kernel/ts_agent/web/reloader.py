"""Release-switch detection for the long-running read-only Web process."""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from typing import Callable, Sequence


class ReleaseWatcher:
    """Watch a stable entrypoint and signal when its resolved release changes."""

    def __init__(
        self,
        entrypoint: str | Path,
        *,
        loaded_entrypoint: str | Path | None = None,
        poll_interval: float = 1.0,
        ready: Callable[[Path], bool] | None = None,
    ) -> None:
        if poll_interval <= 0:
            raise ValueError("release poll interval must be positive")
        self.entrypoint = lexical_absolute(entrypoint)
        self.loaded_entrypoint = (
            Path(loaded_entrypoint).expanduser().resolve(strict=True)
            if loaded_entrypoint is not None
            else self.entrypoint.resolve(strict=True)
        )
        self.poll_interval = poll_interval
        self.ready = ready or (lambda _selected: True)
        self.changed_entrypoint: Path | None = None
        self._stop = threading.Event()
        self._changed = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def restart_requested(self) -> bool:
        return self._changed.is_set()

    def start(self, on_change: Callable[[], None]) -> None:
        if self._thread is not None:
            raise RuntimeError("release watcher has already started")
        self._thread = threading.Thread(
            target=self._run,
            args=(on_change,),
            name="ts-web-release-watcher",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(2.0, self.poll_interval * 2))

    def _run(self, on_change: Callable[[], None]) -> None:
        while not self._stop.wait(self.poll_interval):
            try:
                selected = self.entrypoint.resolve(strict=True)
            except OSError:
                continue
            if selected == self.loaded_entrypoint:
                continue
            try:
                if not self.ready(selected):
                    continue
            except (OSError, ValueError):
                continue
            self.changed_entrypoint = selected
            self._changed.set()
            on_change()
            return


def lexical_absolute(path: str | Path) -> Path:
    """Make a path absolute without resolving a stable symlink component."""

    return Path(os.path.abspath(os.fspath(Path(path).expanduser())))


def exec_selected_release(entrypoint: str | Path, arguments: Sequence[str]) -> None:
    """Replace this process with the same command through its stable entrypoint."""

    stable = lexical_absolute(entrypoint)
    stable.resolve(strict=True)
    executable = str(Path(sys.executable).resolve())
    os.execv(executable, [executable, str(stable), *arguments])
