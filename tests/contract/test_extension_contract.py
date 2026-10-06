from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "contracts" / "tspi-extension" / "1" / "extension-manifest.schema.json"
PROVIDER_SCHEMA = ROOT / "contracts" / "tspi-extension" / "1" / "provider-descriptor.schema.json"


def test_installed_extension_manifest_schema_accepts_minimal_provider() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate({
        "schema_version": "tspi-extension/1",
        "name": "amber-tools",
        "version": "1.0.0",
        "skills": [{"path": "skills/amber"}],
        "providers": [{
            "id": "amber.md",
            "version": "1",
            "kind": "compute",
            "descriptor": "providers/amber.json",
        }],
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


def test_default_chemical_extension_inventory_validates_provider_descriptors() -> None:
    manifest = json.loads((ROOT / "extensions" / "chemical" / "manifest.json").read_text(encoding="utf-8"))
    manifest_schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator(manifest_schema).validate(manifest)
    provider_schema = json.loads(PROVIDER_SCHEMA.read_text(encoding="utf-8"))
    validator = Draft202012Validator(provider_schema)
    provider_ids = {item["id"] for item in manifest["providers"]}
    assert provider_ids == {
        "create_mol_structure", "chemical.analysis", "chemical.comparison.plan",
        "crest", "gaussian", "pyscf", "xtb",
    }
    for item in manifest["providers"]:
        descriptor = json.loads((ROOT / "extensions" / "chemical" / item["descriptor"]).read_text(encoding="utf-8"))
        validator.validate(descriptor)
        assert descriptor["provider_id"] == item["id"]
        assert descriptor["kind"] == item["kind"]
