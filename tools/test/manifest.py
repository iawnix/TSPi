"""Discover test ownership from suite rules; never maintain file inventories."""
from __future__ import annotations
import tomllib
from pathlib import Path
from typing import Any
ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / 'tools/test/manifest.toml'


def load_manifest(root: Path = ROOT) -> dict[str, Any]:
    with (root / 'tools/test/manifest.toml').open('rb') as handle:
        manifest = tomllib.load(handle)
    if manifest.get('schema_version') != 'coragent-test-manifest/1':
        raise ValueError('Unsupported test manifest')
    return manifest


def suite(name: str, root: Path = ROOT) -> dict[str, Any]:
    return load_manifest(root)['suites'][name]


def suite_paths(name: str, root: Path = ROOT) -> list[str]:
    selected = suite(name, root)
    paths = {root / path for path in selected.get('paths', [])}
    for pattern in selected.get('globs', []): paths.update(root.glob(pattern))
    excluded={path for pattern in selected.get('exclude',[]) for path in root.glob(pattern)}
    paths-=excluded
    if any(not path.is_file() for path in paths): raise ValueError(f'Missing test entry in {name}')
    return [str(path) for path in sorted(paths)]


def audit(root: Path = ROOT) -> dict[str, int]:
    owners: dict[Path, list[str]] = {}
    for name, selected in load_manifest(root)['suites'].items():
        if selected.get('aggregate') or selected.get('external'): continue
        for path in suite_paths(name, root): owners.setdefault(Path(path), []).append(name)
    found = set((root / 'tests/node').rglob('*.test.mjs'))
    found.update((root / 'backend/tests').rglob('test_*.py'))
    for directory in ('unit','contract','integration'):
        found.update((root / 'tests' / directory).rglob('test_*.py'))
    bad = [str(path.relative_to(root)) for path in sorted(found) if len(owners.get(path, [])) != 1]
    if bad: raise ValueError('Tests must have exactly one owner: ' + ', '.join(bad))
    return {'files':len(found),'suites':len(load_manifest(root)['suites'])}
