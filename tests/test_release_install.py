from __future__ import annotations

import hashlib
import io
import json
import os
import stat
import subprocess
import tarfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.install_release import REQUIRED_RUNTIME_FILES


ROOT = Path(__file__).resolve().parents[1]
BUILD_RELEASE = ROOT / "scripts" / "build_release.py"
INSTALL_RELEASE = ROOT / "scripts" / "install_release.py"


def test_real_release_build_and_install_excludes_development_tree(tmp_path: Path) -> None:
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
    assert "scripts/install_release.py" in names
    assert "docs/ARCHITECTURE.md" in names
    assert "docs/INSTALLATION.md" in names
    assert "docs/MAINTAINER_GUIDE.md" in names
    assert "scripts/check_package.py" not in names
    assert "scripts/build_release.py" not in names
    assert not any(name.startswith("tests/") for name in names)
    assert not any("node_modules" in Path(name).parts for name in names)

    install_root = tmp_path / "install"
    installed = _install(manifest, install_root)

    assert installed["release_id"] == build_result["release_id"]
    package_root = Path(installed["package_root"])
    assert package_root.is_dir()
    assert not (package_root / "tests").exists()
    assert not (package_root / ".git").exists()
    assert not (package_root / "node_modules").exists()
    assert (package_root / "docs" / "ARCHITECTURE.md").is_file()
    assert (package_root / "docs" / "INSTALLATION.md").is_file()
    assert (package_root / "docs" / "MAINTAINER_GUIDE.md").is_file()
    assert stat.S_IMODE(package_root.stat().st_mode) == 0o500
    assert all(stat.S_IMODE(path.stat().st_mode) & 0o222 == 0 for path in package_root.rglob("*"))
    assert (install_root / "TSPi").is_symlink()
    assert (install_root / "TSPi").resolve() == package_root / "TSPi"
    help_result = subprocess.run(
        [str(install_root / "TSPi"), "--help"],
        cwd=install_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert help_result.returncode == 0, help_result.stderr
    assert "Usage:" in help_result.stdout
    fake_pi = tmp_path / "fake-pi.py"
    fake_pi.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os\n"
        "print(json.dumps({\"package_root\": os.environ[\"TS_PACKAGE_ROOT\"]}))\n",
        encoding="utf-8",
    )
    fake_pi.chmod(0o755)
    startup = subprocess.run(
        [str(install_root / "TSPi"), "--workspace", "release-smoke"],
        cwd=install_root,
        env={**os.environ, "PI_BIN": str(fake_pi)},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert startup.returncode == 0, startup.stderr
    startup_result = json.loads(startup.stdout)
    assert Path(startup_result["package_root"]) == package_root
    assert (install_root / "workspaces" / "release-smoke").is_dir()


def test_release_install_is_idempotent_and_preserves_previous_versions(tmp_path: Path) -> None:
    manifest_one, release_one = _synthetic_release(tmp_path / "one", marker="one")
    manifest_two, release_two = _synthetic_release(tmp_path / "two", marker="two")
    install_root = tmp_path / "install"

    first = _install(manifest_one, install_root)
    repeated = _install(manifest_one, install_root)
    second = _install(manifest_two, install_root)

    assert first["created"] is True
    assert repeated["created"] is False
    assert second["created"] is True
    releases = install_root / ".pi" / "packages" / "ts-agent" / "releases"
    assert (releases / release_one).is_dir()
    assert (releases / release_two).is_dir()
    assert (install_root / ".pi" / "packages" / "ts-agent" / "current").resolve() == releases / release_two


def test_release_install_treats_build_time_as_non_identity_metadata(tmp_path: Path) -> None:
    manifest_path, release_id = _synthetic_release(tmp_path / "release", marker="same-content")
    install_root = tmp_path / "install"
    first = _install(manifest_path, install_root)
    rebuilt = json.loads(manifest_path.read_text(encoding="utf-8"))
    rebuilt["created_at_utc"] = "2099-01-01T00:00:00+00:00"
    manifest_path.write_text(json.dumps(rebuilt), encoding="utf-8")

    repeated = _install(manifest_path, install_root)

    assert first["created"] is True
    assert repeated["created"] is False
    assert repeated["release_id"] == release_id


def test_release_install_rejects_a_modified_archive_before_creating_state(tmp_path: Path) -> None:
    manifest_path, _ = _synthetic_release(tmp_path / "release", marker="original")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    archive = manifest_path.parent / manifest["archive"]["filename"]
    content = bytearray(archive.read_bytes())
    content[len(content) // 2] ^= 1
    archive.write_bytes(content)
    install_root = tmp_path / "install"

    completed = subprocess.run(
        ["python3", str(INSTALL_RELEASE), "--manifest", str(manifest_path), "--install-root", str(install_root)],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert completed.returncode == 1
    assert "SHA-256" in completed.stderr
    assert not (install_root / ".pi").exists()


def test_release_install_rejects_a_release_id_not_bound_to_the_archive(tmp_path: Path) -> None:
    manifest_path, _ = _synthetic_release(tmp_path / "release", marker="identity")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["release_id"] = "0.5.0-sha256-0000000000000000"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    install_root = tmp_path / "install"

    completed = subprocess.run(
        ["python3", str(INSTALL_RELEASE), "--manifest", str(manifest_path), "--install-root", str(install_root)],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert completed.returncode == 1
    assert "release_id does not match" in completed.stderr
    assert not install_root.exists()


@pytest.mark.parametrize("member_name", ["package/../escape", "package/tests/private_probe.py"])
def test_release_install_rejects_unsafe_or_development_members(tmp_path: Path, member_name: str) -> None:
    manifest_path, _ = _synthetic_release(
        tmp_path / "release",
        marker="unsafe",
        extra_files={member_name: b"private\n"},
    )
    install_root = tmp_path / "install"

    completed = subprocess.run(
        ["python3", str(INSTALL_RELEASE), "--manifest", str(manifest_path), "--install-root", str(install_root)],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert completed.returncode == 1
    assert "archive" in completed.stderr
    assert not (install_root / ".pi").exists()
    assert not (tmp_path / "escape").exists()


def _install(manifest: Path, install_root: Path) -> dict:
    completed = subprocess.run(
        [
            "python3",
            str(INSTALL_RELEASE),
            "--manifest",
            str(manifest),
            "--install-root",
            str(install_root),
            "--json",
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def _synthetic_release(
    root: Path,
    *,
    marker: str,
    extra_files: dict[str, bytes] | None = None,
) -> tuple[Path, str]:
    root.mkdir(parents=True)
    temporary_archive = root / "package.tgz"
    files = {name: b"\n" for name in REQUIRED_RUNTIME_FILES}
    files["package.json"] = b'{"name":"@iawnix/ts-agent","version":"0.5.0"}\n'
    files["TSPi"] = b"#!/usr/bin/env bash\nexit 0\n"
    files["README.md"] = f"release {marker}\n".encode()
    files.update(extra_files or {})
    with tarfile.open(temporary_archive, "w:gz") as archive:
        package = tarfile.TarInfo("package")
        package.type = tarfile.DIRTYPE
        package.mode = 0o755
        archive.addfile(package)
        for name, content in sorted(files.items()):
            info = tarfile.TarInfo(name if name.startswith("package/") else f"package/{name}")
            info.size = len(content)
            info.mode = 0o755 if name == "TSPi" else 0o644
            archive.addfile(info, io.BytesIO(content))
    digest = hashlib.sha256(temporary_archive.read_bytes()).hexdigest()
    release_id = f"0.5.0-sha256-{digest[:16]}"
    archive_name = f"ts-agent-{release_id}.tgz"
    archive_path = root / archive_name
    temporary_archive.rename(archive_path)
    manifest = {
        "schema_version": "ts-agent-release/1",
        "release_id": release_id,
        "package": {"name": "@iawnix/ts-agent", "version": "0.5.0"},
        "archive": {
            "filename": archive_name,
            "sha256": digest,
            "size_bytes": archive_path.stat().st_size,
        },
        "source": {"git_commit": "test", "dirty": False},
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path = root / "ts-agent-release.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path, release_id
