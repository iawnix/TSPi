"""Release ownership rules; source roots are declared once in source-layout.json."""
from __future__ import annotations

import fnmatch
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAYOUT = json.loads((ROOT / "config/source-layout.json").read_text())
PACKAGE_FILES = [*LAYOUT["roots"], *LAYOUT["files"], *LAYOUT["generated"], *("!" + value for value in LAYOUT["exclude"])]
REQUIRED_RUNTIME_FILES = frozenset(LAYOUT["required"])
REQUIRED_TARBALL_FILES = REQUIRED_RUNTIME_FILES | {"package.json", *LAYOUT["files"]}
RETIRED_RUNTIME_PATHS = ("apps/app-server/", "extensions/", "packages/agent-core/", "packages/agent-runtime/", "packages/runtime-bridge/", "packages/research-state/")
SKILL_ENTRIES = ["./skills", "./domains/chemical/skills"]
SKILL_ENTRY_FILES = sorted(str(p.relative_to(ROOT)) for root in (ROOT / "skills", ROOT / "domains/chemical/skills") for p in root.rglob("SKILL.md"))
FORBIDDEN_PARTS = {"local_debug", ".git", ".agents", "__pycache__", ".pytest_cache", "node_modules", "tests"}


def release_files(root: Path = ROOT) -> set[str]:
    """Select existing authored files, without descending into private/cache trees."""
    files = set(LAYOUT["files"])
    for name in LAYOUT["roots"]:
        for path in (root / name).rglob("*"):
            relative = path.relative_to(root)
            if path.is_file() and path.suffix not in {".pyc", ".pyo", ".tmp"} and not any(part.endswith(".egg-info") for part in relative.parts) and not FORBIDDEN_PARTS.intersection(relative.parts) and not any(fnmatch.fnmatchcase(relative.as_posix(), pattern) for pattern in LAYOUT["exclude"]):
                files.add(relative.as_posix())
    return files
