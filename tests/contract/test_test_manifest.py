from __future__ import annotations

from pathlib import Path

from tools.test.manifest import ROOT, load_manifest, suite_paths


def test_test_manifest_declares_all_supported_lanes_and_existing_paths() -> None:
    suites = load_manifest()["suites"]
    assert {
        "fast",
        "source",
        "subagents",
        "native-pi",
        "package",
        "remote-smoke",
        "live-eval",
    } <= set(suites)
    for name in suites:
        assert all(Path(path).exists() for path in suite_paths(name))


def test_test_root_contains_only_configuration_files() -> None:
    allowed = {"__init__.py", "conftest.py"}
    files = {path.name for path in (ROOT / "tests").iterdir() if path.is_file()}
    assert files <= allowed
