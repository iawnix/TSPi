from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from scripts import _component_release, check_package, package_inventory


ROOT = Path(__file__).resolve().parents[2]


def test_release_inventory_is_shared_by_checker_and_installer() -> None:
    manifest = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))

    assert manifest["files"] == package_inventory.PACKAGE_FILES
    assert check_package.PACKAGE_FILES is package_inventory.PACKAGE_FILES
    assert check_package.REQUIRED_TARBALL_FILES is package_inventory.REQUIRED_TARBALL_FILES
    assert _component_release.REQUIRED_RUNTIME_FILES is package_inventory.REQUIRED_RUNTIME_FILES


@pytest.mark.parametrize("retired", [
    "apps/app-server/app_server.mjs",
    "packages/agent-runtime/runtime.mjs",
])
def test_retired_runtime_is_rejected_even_if_allowlisted(retired: str, monkeypatch: pytest.MonkeyPatch) -> None:
    allowlisted = check_package.expanded_allowlisted_files() | {retired}
    monkeypatch.setattr(check_package, "expanded_allowlisted_files", lambda: allowlisted)

    with pytest.raises(check_package.PackageCheckError) as error:
        check_package.validate_tarball({"package.json", *allowlisted})

    assert str(error.value) == f"retired implementation included in package: {retired}"


def test_required_release_members_are_in_the_npm_allowlist() -> None:
    manifest = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    allowlisted = {"package.json", *check_package.expanded_allowlisted_files()}

    assert package_inventory.REQUIRED_TARBALL_FILES <= allowlisted
    assert package_inventory.REQUIRED_RUNTIME_FILES <= allowlisted
    assert "scripts/package_inventory.py" in allowlisted
    assert "environment.lock.txt" in allowlisted
    assert "contracts/ts-web/provider-response.schema.json" in allowlisted
    assert "contracts/ts-render/curve-data.schema.json" in allowlisted
    assert "apps/agent/pi/prompt.mjs" in allowlisted
    assert manifest["pi"]["extensions"] == []
    assert not any("local_debug" in Path(path).parts for path in allowlisted)
    assert not any(path.startswith(package_inventory.RETIRED_RUNTIME_PATHS) for path in allowlisted)
    assert not any(path.endswith(".pyc") for path in allowlisted)


def test_private_installation_inputs_are_excluded_from_release_and_npm(tmp_path: Path) -> None:
    private = {
        "config/models.json", "config/auth.json", "config/job.toml", "config/name-resolver.toml",
        "config/email.toml", "config/smtp-password", "config/secrets/smtp-password",
    }
    examples = {"config/models.example.json", "config/auth.example.json", "config/email.example.toml"}
    for name in private | examples:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic fixture only\n")
    shutil.copyfile(ROOT / "package.json", tmp_path / "package.json")
    shutil.copyfile(ROOT / ".npmignore", tmp_path / ".npmignore")
    inventory = package_inventory.release_files(tmp_path)
    assert not private.intersection(inventory)
    assert examples <= inventory
    result = subprocess.run(
        ["npm", "pack", "--dry-run", "--ignore-scripts", "--json"],
        cwd=tmp_path, env={**os.environ, "npm_config_cache": str(tmp_path / "npm-cache")},
        capture_output=True, text=True, check=True,
    )
    members = {entry["path"] for entry in json.loads(result.stdout)[0]["files"]}
    assert not private.intersection(members)
    assert examples <= members
