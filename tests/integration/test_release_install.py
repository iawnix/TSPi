from __future__ import annotations

import json
import hashlib
import io
import subprocess
import tarfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts._component_release import REQUIRED_RUNTIME_FILES, prepare_install_root
from scripts._wheel import inspect_wheel


ROOT = Path(__file__).resolve().parents[2]
BUILD_RELEASE = ROOT / "scripts" / "build_release.py"
PACKAGE_VERSION = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["version"]


def test_prepare_install_root_rejects_relative_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError, match="must be absolute"):
        prepare_install_root(Path("install"))

    assert not (tmp_path / "install").exists()


@pytest.mark.parametrize("name", ['install"root', "install\\root", "install\nroot"])
def test_prepare_install_root_rejects_unsafe_characters(tmp_path: Path, name: str) -> None:
    install_root = tmp_path / name

    with pytest.raises(ValueError, match="cannot contain"):
        prepare_install_root(install_root)

    assert not install_root.exists()


def test_prepare_install_root_rejects_broad_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "owner"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)

    for install_root in (Path("/"), home, home.parent):
        with pytest.raises(ValueError, match="dedicated installation directory"):
            prepare_install_root(install_root)


def test_prepare_install_root_rejects_symbolic_link_parent(tmp_path: Path) -> None:
    physical_parent = tmp_path / "physical"
    physical_parent.mkdir()
    linked_parent = tmp_path / "linked"
    linked_parent.symlink_to(physical_parent, target_is_directory=True)

    with pytest.raises(ValueError, match="physical directory path"):
        prepare_install_root(linked_parent / "install")

    assert not (physical_parent / "install").exists()


def test_real_release_build_excludes_development_tree(tmp_path: Path) -> None:
    output = tmp_path / "dist"
    built = subprocess.run(
        [
            "python3",
            str(BUILD_RELEASE),
            "--output-dir",
            str(output),
            "--allow-dirty",
            "--json",
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert built.returncode == 0, built.stderr
    build_result = json.loads(built.stdout)
    archive = Path(build_result["archive"])
    manifest = Path(build_result["manifest"])
    with tarfile.open(archive, "r:gz") as handle:
        names = {member.name.removeprefix("package/") for member in handle.getmembers()}
    release_manifest = json.loads(manifest.read_text(encoding="utf-8"))
    distribution = release_manifest["python_distribution"]
    assert "scripts/_component_release.py" in names
    assert "docs/ARCHITECTURE.md" in names
    assert "docs/INSTALLATION.md" in names
    assert "docs/MAINTAINER_GUIDE.md" in names
    assert "apps/app-server/pi-app-server.mjs" in names
    assert "apps/app-server/pi-session-worker.mjs" in names
    assert "config/pi-source.json" in names
    assert "config/pi-patches/001-workspaces.patch" in names
    assert "scripts/prepare_pi_source.py" in names
    assert not any(name.startswith("packages/tspi-runtime/tspi_runtime/web/") for name in names)
    assert not any(name.startswith(("packages/research-compute/", "packages/tspi-provider-runtime/")) for name in names)
    assert "packages/research-state/research_state/contracts/finding_candidates.schema.json" not in names
    assert "packages/research-state/research_state/model.py" not in names
    assert "packages/research-state/research_state/operational_ids.py" in names
    assert "packages/research-state/research_state/agent_workspace.py" in names
    assert distribution == build_result["python_distribution"]
    assert distribution["name"] == "tspi-runtime"
    assert distribution["version"] == json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["version"]
    assert distribution["path"] in names
    assert sum(name.startswith("python-dist/") and name.endswith(".whl") for name in names) == 1
    assert "scripts/check_package.py" not in names
    assert "scripts/build_release.py" not in names
    assert not any(name.startswith("tests/") for name in names)
    assert not any("node_modules" in Path(name).parts for name in names)


def _synthetic_release(
    root: Path,
    *,
    marker: str,
    version: str = PACKAGE_VERSION,
    extra_files: dict[str, bytes] | None = None,
    required_files: frozenset[str] = REQUIRED_RUNTIME_FILES,
) -> tuple[Path, str]:
    root.mkdir(parents=True)
    temporary_archive = root / "package.tgz"
    files = {name: b"\n" for name in required_files}
    files["package.json"] = json.dumps(
        {"name": "@iawnix/tspi", "version": version},
        separators=(",", ":"),
    ).encode() + b"\n"
    files["ResearchAgent"] = b"#!/usr/bin/env bash\nexit 0\n"
    files["README.md"] = f"release {marker}\n".encode()
    files.update(extra_files or {})
    python_payload = {
        normalized.removeprefix("packages/tspi-runtime/"): content
        for name, content in files.items()
        if (normalized := name.removeprefix("package/")).startswith("packages/tspi-runtime/tspi_runtime/")
    }
    wheel = _synthetic_wheel(root, version=version, package_files=python_payload)
    wheel_descriptor = inspect_wheel(
        wheel,
    )
    distribution = {
        "name": wheel_descriptor["name"],
        "version": wheel_descriptor["version"],
        "path": f"python-dist/{wheel.name}",
        "sha256": wheel_descriptor["sha256"],
        "size_bytes": wheel_descriptor["size_bytes"],
        "payload_sha256": wheel_descriptor["payload_sha256"],
    }
    files[distribution["path"]] = wheel.read_bytes()
    with tarfile.open(temporary_archive, "w:gz") as archive:
        package = tarfile.TarInfo("package")
        package.type = tarfile.DIRTYPE
        package.mode = 0o755
        archive.addfile(package)
        for name, content in sorted(files.items()):
            info = tarfile.TarInfo(name if name.startswith("package/") else f"package/{name}")
            info.size = len(content)
            info.mode = 0o755 if name in {"ResearchAgent", "apps/agent-cli/provider_runner.py"} else 0o644
            archive.addfile(info, io.BytesIO(content))
    digest = hashlib.sha256(temporary_archive.read_bytes()).hexdigest()
    release_id = f"{version}-sha256-{digest[:16]}"
    archive_name = f"tspi-{release_id}.tgz"
    archive_path = root / archive_name
    temporary_archive.rename(archive_path)
    manifest = {
        "schema_version": "tspi-release/1",
        "release_id": release_id,
        "package": {"name": "@iawnix/tspi", "version": version},
        "python_distribution": distribution,
        "archive": {
            "filename": archive_name,
            "sha256": digest,
            "size_bytes": archive_path.stat().st_size,
        },
        "source": {"git_commit": "test", "dirty": False},
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path = root / "tspi-release.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path, release_id


def _synthetic_wheel(root: Path, *, version: str, package_files: dict[str, bytes]) -> Path:
    wheel = root / f"tspi_runtime-{version}-py3-none-any.whl"
    metadata = f"Metadata-Version: 2.4\nName: tspi-runtime\nVersion: {version}\n\n".encode()
    with zipfile.ZipFile(wheel, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in sorted(package_files.items()):
            archive.writestr(name, content)
        archive.writestr(f"tspi_runtime-{version}.dist-info/METADATA", metadata)
        archive.writestr(
            f"tspi_runtime-{version}.dist-info/WHEEL",
            "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        )
        archive.writestr(f"tspi_runtime-{version}.dist-info/RECORD", "")
    return wheel
