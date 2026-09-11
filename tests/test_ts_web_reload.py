from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "components" / "ts-web"))
from ts_web import reloader
from ts_web.reloader import ReleaseWatcher, exec_selected_release


def _release(root: Path, name: str) -> Path:
    script = root / "releases" / name / "components" / "ts-web" / "bin" / "ts-web"
    script.parent.mkdir(parents=True)
    script.write_text(f"# {name}\n", encoding="utf-8")
    return script


def test_release_watcher_detects_atomic_stable_entrypoint_switch(tmp_path: Path) -> None:
    first = _release(tmp_path, "release-a")
    second = _release(tmp_path, "release-b")
    current = tmp_path / "current"
    current.symlink_to("releases/release-a", target_is_directory=True)
    stable_entrypoint = current / "components" / "ts-web" / "bin" / "ts-web"
    changed = threading.Event()
    watcher = ReleaseWatcher(
        stable_entrypoint,
        loaded_entrypoint=first,
        poll_interval=0.01,
    )
    watcher.start(changed.set)
    try:
        replacement = tmp_path / ".current.next"
        replacement.symlink_to("releases/release-b", target_is_directory=True)
        os.replace(replacement, current)
        assert changed.wait(timeout=2)
    finally:
        watcher.stop()

    assert watcher.restart_requested is True
    assert watcher.changed_entrypoint == second.resolve()


def test_release_watcher_ignores_transient_missing_target(tmp_path: Path) -> None:
    first = _release(tmp_path, "release-a")
    second = _release(tmp_path, "release-b")
    current = tmp_path / "current"
    current.symlink_to("releases/release-a", target_is_directory=True)
    changed = threading.Event()
    watcher = ReleaseWatcher(
        current / "components" / "ts-web" / "bin" / "ts-web",
        loaded_entrypoint=first,
        poll_interval=0.01,
    )
    watcher.start(changed.set)
    try:
        current.unlink()
        assert changed.wait(timeout=0.05) is False
        current.symlink_to("releases/release-b", target_is_directory=True)
        assert changed.wait(timeout=2)
    finally:
        watcher.stop()

    assert watcher.changed_entrypoint == second.resolve()


def test_release_watcher_waits_until_selected_runtime_is_ready(tmp_path: Path) -> None:
    first = _release(tmp_path, "release-a")
    second = _release(tmp_path, "release-b")
    current = tmp_path / "current"
    current.symlink_to("releases/release-a", target_is_directory=True)
    changed = threading.Event()
    ready = threading.Event()
    watcher = ReleaseWatcher(
        current / "components" / "ts-web" / "bin" / "ts-web",
        loaded_entrypoint=first,
        poll_interval=0.01,
        ready=lambda selected: selected == second.resolve() and ready.is_set(),
    )
    watcher.start(changed.set)
    try:
        replacement = tmp_path / ".current.next"
        replacement.symlink_to("releases/release-b", target_is_directory=True)
        os.replace(replacement, current)
        assert changed.wait(timeout=0.05) is False
        ready.set()
        assert changed.wait(timeout=2)
    finally:
        watcher.stop()

    assert watcher.changed_entrypoint == second.resolve()


def test_exec_selected_release_preserves_stable_path_and_arguments(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _release(tmp_path, "release-a")
    current = tmp_path / "current"
    current.symlink_to("releases/release-a", target_is_directory=True)
    stable_entrypoint = current / "components" / "ts-web" / "bin" / "ts-web"
    captured = {}

    def fake_execv(executable: str, arguments: list[str]) -> None:
        captured["executable"] = executable
        captured["arguments"] = arguments

    monkeypatch.setattr(reloader.os, "execv", fake_execv)
    exec_selected_release(stable_entrypoint, ["serve", "--state-dir", "/tmp/state"])

    executable = str(Path(sys.executable).resolve())
    assert captured == {
        "executable": executable,
        "arguments": [
            executable,
            str(stable_entrypoint),
            "serve",
            "--state-dir",
            "/tmp/state",
        ],
    }
