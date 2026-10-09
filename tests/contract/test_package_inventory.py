from __future__ import annotations

import json
from pathlib import Path

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
