from __future__ import annotations

import json
from pathlib import Path

from scripts import check_package, install_release, package_inventory


ROOT = Path(__file__).resolve().parents[2]


def test_release_inventory_is_shared_by_checker_and_installer() -> None:
    manifest = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))

    assert manifest["files"] == package_inventory.PACKAGE_FILES
    assert check_package.PACKAGE_FILES is package_inventory.PACKAGE_FILES
    assert check_package.REQUIRED_TARBALL_FILES is package_inventory.REQUIRED_TARBALL_FILES
    assert install_release.REQUIRED_RUNTIME_FILES is package_inventory.REQUIRED_RUNTIME_FILES


def test_required_release_members_are_in_the_npm_allowlist() -> None:
    allowlisted = {"package.json", *check_package.expanded_allowlisted_files()}

    assert package_inventory.REQUIRED_TARBALL_FILES <= allowlisted
    assert package_inventory.REQUIRED_RUNTIME_FILES <= allowlisted
    assert "scripts/package_inventory.py" in package_inventory.PACKAGE_FILES
    assert "scripts/package_inventory.py" in package_inventory.REQUIRED_RUNTIME_FILES
    assert "requirements-runtime.txt" in package_inventory.REQUIRED_TARBALL_FILES
    assert "requirements-runtime.txt" in package_inventory.REQUIRED_RUNTIME_FILES
    assert not any(path.startswith("contracts/ts-phone/") for path in package_inventory.PACKAGE_FILES)
    assert "contracts/ts-web/component-manifest.schema.json" in package_inventory.PACKAGE_FILES
    assert "contracts/ts-web/provider-request.schema.json" in package_inventory.REQUIRED_TARBALL_FILES
    assert "contracts/ts-web/provider-response.schema.json" in package_inventory.REQUIRED_RUNTIME_FILES
    assert "contracts/ts-web/research-map-response.schema.json" in package_inventory.REQUIRED_TARBALL_FILES


    assert "contracts/ts-render/curve-data.schema.json" in package_inventory.REQUIRED_RUNTIME_FILES
    assert "apps/app-server/system-prompt.mjs" in package_inventory.REQUIRED_RUNTIME_FILES
    assert "docs/adr/0005-ordinary-pi-host-bridge.md" in package_inventory.REQUIRED_TARBALL_FILES
    assert "docs/adr/0005-ordinary-pi-host-bridge.md" in package_inventory.REQUIRED_RUNTIME_FILES
    assert set(package_inventory.APP_SERVER_FILES) <= package_inventory.REQUIRED_RUNTIME_FILES
