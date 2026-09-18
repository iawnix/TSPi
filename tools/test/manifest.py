"""Load and validate the repository test manifest."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / "tools" / "test" / "manifest.toml"


def load_manifest() -> dict[str, Any]:
    with MANIFEST_PATH.open("rb") as handle:
        manifest = tomllib.load(handle)
    if manifest.get("schema_version") != "tspi-test-manifest/1":
        raise ValueError(f"unsupported test manifest: {MANIFEST_PATH}")
    suites = manifest.get("suites")
    if not isinstance(suites, dict) or not suites:
        raise ValueError("test manifest must declare at least one suite")
    return manifest


def suite(name: str) -> dict[str, Any]:
    suites = load_manifest()["suites"]
    selected = suites.get(name)
    if not isinstance(selected, dict):
        available = ", ".join(sorted(suites))
        raise KeyError(f"unknown test suite {name!r}; choose one of: {available}")
    return selected


def suite_paths(name: str) -> list[str]:
    paths = suite(name).get("paths", [])
    if not isinstance(paths, list) or not all(isinstance(path, str) for path in paths):
        raise ValueError(f"suite {name!r} paths must be a list of strings")
    resolved = [ROOT / path for path in paths]
    missing = [str(path.relative_to(ROOT)) for path in resolved if not path.exists()]
    if missing:
        raise ValueError(f"suite {name!r} references missing paths: {', '.join(missing)}")
    return [str(path) for path in resolved]
