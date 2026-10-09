from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "contracts" / "tspi-extension" / "1" / "extension-manifest.schema.json"


def test_installed_extension_manifest_schema_accepts_installed_server() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate({
        "schema_version": "tspi-extension/1",
        "name": "amber-tools",
        "version": "1.0.0",
        "skills": [{"path": "skills/amber"}],
        "server": {
            "entry": "server/index.mjs",
            "sha256": "sha256:" + "a" * 64,
            "tools": ["amber_run"],
            "permissions": ["workspace.read"],
        },
    })


def test_installed_extension_manifest_schema_rejects_unpinned_entry() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema).iter_errors({
        "schema_version": "tspi-extension/1",
        "name": "amber-tools",
        "version": "1.0.0",
        "skills": [],
        "providers": [{
            "id": "amber.md",
            "version": "1",
            "kind": "compute",
            "entry": "providers/amber.mjs",
        }],
    }))
    assert errors


def test_scientific_and_email_extensions_ship_skills_without_providers() -> None:
    schema = json.loads(SCHEMA.read_text())
    for name in ("core", "chemical", "email"):
        manifest = json.loads((ROOT / "extensions" / name / "manifest.json").read_text())
        Draft202012Validator(schema).validate(manifest)
        assert "providers" not in manifest
        assert manifest["skills"]
