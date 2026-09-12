from __future__ import annotations

from pathlib import Path

from scripts.uninstall import uninstall


def _args(root: Path, **overrides: object):
    values = {
        "install_root": str(root),
        "service_scope": "none",
        "purge_workspaces": False,
        "purge_config": False,
        "purge_runtime": False,
        "remove_root": False,
        "purge_all": False,
        "non_interactive": True,
        "yes": True,
        "json": False,
    }
    values.update(overrides)
    return type("Options", (), values)()


def test_uninstall_preserves_workspace_and_config_by_default(tmp_path: Path) -> None:
    root = tmp_path / "install"
    (root / ".pi/packages/tspi").mkdir(parents=True)
    (root / "workspaces/ts_001").mkdir(parents=True)
    (root / ".pi/ts-phone-state").mkdir(parents=True)
    (root / "TSPi").symlink_to(".pi/packages/tspi/current")

    result = uninstall(_args(root))

    assert result["ok"] is True
    assert (root / "workspaces/ts_001").is_dir()
    assert (root / ".pi/ts-phone-state").is_dir()
    assert not (root / ".pi/packages/tspi").exists()


def test_uninstall_purge_can_remove_empty_installation(tmp_path: Path) -> None:
    root = tmp_path / "install"
    (root / ".pi/packages/tspi").mkdir(parents=True)
    (root / "workspaces/ts_001").mkdir(parents=True)
    (root / ".pi/ts-phone-state").mkdir(parents=True)
    (root / "TSPi").symlink_to(".pi/packages/tspi/current")

    result = uninstall(_args(root, purge_workspaces=True, purge_config=True, purge_runtime=True, remove_root=True))

    assert result["ok"] is True
    assert not root.exists()
