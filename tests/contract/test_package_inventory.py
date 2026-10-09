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
    "packages/research-compute/research_compute/execution.py",
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
    assert "scripts/package_inventory.py" in package_inventory.PACKAGE_FILES
    assert "scripts/package_inventory.py" in package_inventory.REQUIRED_RUNTIME_FILES
    assert "environment.lock.txt" in package_inventory.REQUIRED_TARBALL_FILES
    assert "environment.lock.txt" in package_inventory.REQUIRED_RUNTIME_FILES
    assert not any(path.startswith("contracts/ts-phone/") for path in package_inventory.PACKAGE_FILES)
    assert "contracts/ts-web/component-manifest.schema.json" in package_inventory.PACKAGE_FILES
    assert "contracts/ts-web/provider-request.schema.json" in package_inventory.REQUIRED_TARBALL_FILES
    assert "contracts/ts-web/provider-response.schema.json" in package_inventory.REQUIRED_RUNTIME_FILES
    assert "contracts/ts-web/research-map-response.schema.json" in package_inventory.REQUIRED_TARBALL_FILES
    assert not any(path.startswith("packages/agent-ui/") and path.endswith("/index.ts") for path in package_inventory.PACKAGE_FILES)
    assert manifest["pi"]["extensions"] == []
    for retired in (
        "packages/agent-ui/runtime.ts",
        "packages/agent-ui/research/*.ts",
        "packages/agent-ui/compute/*.ts",
        "packages/agent-ui/review/*.ts",
        "packages/agent-ui/artifacts/*.ts",
        "packages/agent-ui/ui/*.ts",
        "packages/agent-ui/bridge/*",
    ):
        assert retired not in package_inventory.PACKAGE_FILES
    for retired in (
        "apps/app-server/pi-experimental-app-server.mjs",
        "apps/app-server/tspi-terminal-runtime.mjs",
        "apps/app-server/tspi-history.mjs",
    ):
        assert retired not in package_inventory.APP_SERVER_FILES
        assert retired not in package_inventory.REQUIRED_TARBALL_FILES
        assert retired not in package_inventory.REQUIRED_RUNTIME_FILES


    assert "contracts/ts-render/curve-data.schema.json" in package_inventory.REQUIRED_RUNTIME_FILES
    assert "apps/app-server/system-prompt.mjs" in package_inventory.REQUIRED_RUNTIME_FILES
    assert "docs/adr/0005-ordinary-pi-host-bridge.md" in package_inventory.REQUIRED_TARBALL_FILES
    assert "docs/adr/0005-ordinary-pi-host-bridge.md" in package_inventory.REQUIRED_RUNTIME_FILES
    assert set(package_inventory.APP_SERVER_FILES) <= package_inventory.REQUIRED_RUNTIME_FILES
