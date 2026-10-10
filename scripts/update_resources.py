#!/usr/bin/env python3
"""Generate one release resource inventory and scientific script identities."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def generated(root: Path) -> dict[Path, str]:
    output = {}
    package = json.loads((root / "package.json").read_text())
    for name in package['coragent'].get('environments', []):
        path = root / name
        value = json.loads(path.read_text())
        for profile in value['profiles'].values():
            profile['resources'] = {key: digest(path.parent / key) for key in sorted(profile['resources'])}
        output[path] = json.dumps(value, indent=2) + '\n'
    for name in package["coragent"]["execution"]:
        path = root / name
        value = json.loads(path.read_text())
        for entry in value["executors"]:
            # The declared staging closure belongs to the executor, not a Skill loader.
            entry["resources"] = {key: digest(path.parent / key) for key in sorted(entry["resources"])}
        for entry in value["validators"]:
            entry["sha256"] = digest(path.parent / entry["entry"])
            for resource in entry.get("resources", {}).values():
                resource["sha256"] = digest(path.parent / resource["path"])
        output[path] = json.dumps(value, indent=2) + "\n"
    files = {}
    for directory in ("skills", "domains", "prompts"):
        if not (root / directory).is_dir():
            raise ValueError(f"required resource directory is missing: {directory}")
        for path in sorted((root / directory).rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            if path.is_symlink():
                raise ValueError(f"resource symlink: {path.relative_to(root)}")
            content = output[path].encode() if path in output else path.read_bytes()
            files[path.relative_to(root).as_posix()] = "sha256:" + hashlib.sha256(content).hexdigest()
    output[root / "config/resources.json"] = json.dumps({"schema_version": "coragent-resources/1", "files": files}, indent=2) + "\n"
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    for path, text in generated(ROOT).items():
        if args.check:
            if not path.is_file() or path.read_text() != text:
                raise SystemExit(f"resource inventory is stale: {path.relative_to(ROOT)}")
        else:
            path.write_text(text)


if __name__ == "__main__":
    main()
