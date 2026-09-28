from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.app_layout import inspect_installation, write_standalone_marker


def _legacy_install(root: Path, release: str = "r1") -> None:
    package = root / ".pi/packages/tspi"
    (package / "releases" / release).mkdir(parents=True)
    (package / "current").symlink_to(f"releases/{release}")
    (package / "install-state.json").write_text(
        json.dumps({
            "schema_version": "tspi-package-install/1",
            "current_release_id": release,
            "package_root": str(package / "releases" / release),
        }),
        encoding="utf-8",
    )


def _standalone_install(root: Path, release: str = "r1") -> None:
    (root / "releases" / release).mkdir(parents=True)
    (root / "etc").mkdir()
    (root / "var").mkdir()
    (root / "bin").mkdir()
    (root / "current").symlink_to(f"releases/{release}")
    write_standalone_marker(root)


def test_legacy_layout_is_explicitly_reported_as_migration_required(tmp_path: Path) -> None:
    _legacy_install(tmp_path)
    report = inspect_installation(tmp_path)
    assert report["layout"] == "legacy"
    assert report["ok"] is True
    assert report["migration_required"] is True
    assert report["release_id"] == "r1"


def test_standalone_layout_is_healthy_without_legacy_store(tmp_path: Path) -> None:
    _standalone_install(tmp_path)
    report = inspect_installation(tmp_path)
    assert report["layout"] == "standalone"
    assert report["ok"] is True
    assert report["migration_required"] is False
    assert report["release_id"] == "r1"


def test_mixed_layout_is_never_considered_healthy(tmp_path: Path) -> None:
    _standalone_install(tmp_path)
    _legacy_install(tmp_path, release="old")
    report = inspect_installation(tmp_path)
    assert report["layout"] == "mixed"
    assert report["ok"] is False
    assert any(item["code"] == "mixed_layout" for item in report["findings"])


def test_current_pointer_must_remain_inside_release_store(tmp_path: Path) -> None:
    _legacy_install(tmp_path)
    package = tmp_path / ".pi/packages/tspi"
    package.joinpath("current").unlink()
    package.joinpath("current").symlink_to("/tmp")
    report = inspect_installation(tmp_path)
    assert report["ok"] is False
    assert any(item["code"] == "current_escapes_releases" for item in report["findings"])


def test_legacy_state_and_current_pointer_must_agree(tmp_path: Path) -> None:
    _legacy_install(tmp_path, release="new")
    package = tmp_path / ".pi/packages/tspi"
    (package / "releases/old").mkdir()
    package.joinpath("current").unlink()
    package.joinpath("current").symlink_to("releases/old")
    report = inspect_installation(tmp_path)
    assert report["ok"] is False
    assert any(item["code"] == "legacy_current_state_mismatch" for item in report["findings"])


def test_unmarked_standalone_candidate_is_not_accepted(tmp_path: Path) -> None:
    (tmp_path / "releases/r1").mkdir(parents=True)
    (tmp_path / "current").symlink_to("releases/r1")
    report = inspect_installation(tmp_path)
    assert report["layout"] == "standalone_unmarked"
    assert report["ok"] is False
    assert any(item["code"] == "standalone_unmarked" for item in report["findings"])


def test_marker_requires_prepared_standalone_directories(tmp_path: Path) -> None:
    (tmp_path / "etc").mkdir()
    with pytest.raises(ValueError, match="standalone directory"):
        write_standalone_marker(tmp_path)
