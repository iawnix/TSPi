from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts._source_capture import SourceCaptureError, capture_source_tree


def test_clean_release_capture_is_commit_bound_and_immutable(tmp_path: Path) -> None:
    repository = _repository(tmp_path / "repository")
    executable = repository / "scripts" / "build_release.py"
    executable.chmod(0o700)
    assert subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout == ""
    captured = capture_source_tree(repository, tmp_path / "captured", allow_dirty=False)
    original = (captured.root / "README.md").read_text(encoding="utf-8")

    (repository / "README.md").write_text("changed after capture\n", encoding="utf-8")

    assert captured.dirty is False
    assert (captured.root / "README.md").read_text(encoding="utf-8") == original
    captured.verify()

    (captured.root / "README.md").write_text("changed captured bytes\n", encoding="utf-8")
    with pytest.raises(SourceCaptureError, match="changed during"):
        captured.verify()


def test_dirty_release_capture_requires_explicit_local_override(tmp_path: Path) -> None:
    repository = _repository(tmp_path / "repository")
    (repository / "README.md").write_text("dirty source\n", encoding="utf-8")

    with pytest.raises(SourceCaptureError, match="--allow-dirty"):
        capture_source_tree(repository, tmp_path / "rejected", allow_dirty=False)

    captured = capture_source_tree(repository, tmp_path / "captured", allow_dirty=True)
    assert captured.dirty is True
    assert (captured.root / "README.md").read_text(encoding="utf-8") == "dirty source\n"
    captured.verify()


def _repository(root: Path) -> Path:
    files = {
        "README.md": "captured source\n",
        "package.json": '{"name":"@iawnix/ts-agent"}\n',
        "pyproject.toml": "[build-system]\nrequires = []\n",
        "scripts/build_release.py": "# build fixture\n",
        "scripts/check_package.py": "# check fixture\n",
        "scripts/package_inventory.py": "# package fixture\n",
    }
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    (root / "scripts" / "build_release.py").chmod(0o755)
    _git(root, "init", "-q")
    _git(root, "config", "user.name", "TSPi Test")
    _git(root, "config", "user.email", "tspi-test@example.invalid")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "initial")
    return root


def _git(root: Path, *arguments: str) -> None:
    subprocess.run(["git", *arguments], cwd=root, check=True)
