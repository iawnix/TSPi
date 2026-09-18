from __future__ import annotations

import hashlib
import io
import json
import os
import stat
import subprocess
import sys
import tarfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.install_release import REQUIRED_RUNTIME_FILES, install_release, prepare_install_root
from scripts._wheel import inspect_wheel
from tests.support.runtime_helpers import write_test_runtime_manifest


ROOT = Path(__file__).resolve().parents[2]
BUILD_RELEASE = ROOT / "scripts" / "build_release.py"
INSTALL_RELEASE = ROOT / "scripts" / "install_release.py"
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


def test_release_install_rejects_relative_install_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest_path, _ = _synthetic_release(tmp_path / "release", marker="relative-install-root")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError, match="must be absolute"):
        install_release(manifest_path, None, Path("install"))

    assert not (tmp_path / "install").exists()


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
    release_manifest = json.loads(manifest.read_text(encoding="utf-8"))
    distribution = release_manifest["python_distribution"]
    assert "scripts/install_release.py" in names
    assert "docs/ARCHITECTURE.md" in names
    assert "docs/INSTALLATION.md" in names
    assert "docs/MAINTAINER_GUIDE.md" in names
    assert "apps/app-server/pi-app-server.mjs" in names
    assert "apps/app-server/pi-session-worker.mjs" in names
    assert "config/pi-source.json" in names
    assert "config/pi-worker-entry.patch" in names
    assert "config/pi-multi-workspace-create.patch" in names
    assert "config/pi-system-prompt.patch" in names
    assert "scripts/prepare_pi_source.py" in names
    assert "packages/ts-agent-kernel/ts_agent/projection/provider.py" in names
    assert not any(name.startswith("packages/ts-agent-kernel/ts_agent/web/") for name in names)
    assert "packages/ts-agent-kernel/ts_agent/workspace/artifacts.py" in names
    assert "packages/ts-agent-kernel/ts_agent/workspace/candidates.py" in names
    assert "packages/ts-agent-kernel/ts_agent/workspace/claims.py" in names
    assert "packages/ts-agent-kernel/ts_agent/workspace/contracts/change_request.schema.json" in names
    assert "packages/ts-agent-kernel/ts_agent/workspace/contracts/observation_candidates.schema.json" in names
    assert "packages/ts-agent-kernel/ts_agent/workspace/contracts/proof_spec.schema.json" in names
    assert "packages/ts-agent-kernel/ts_agent/workspace/contracts/proof_spec_registry.schema.json" in names
    assert "packages/ts-agent-kernel/ts_agent/compute/capabilities.py" in names
    assert "packages/ts-agent-kernel/ts_agent/validation/templates/builtin/classical-ts__1.json" in names
    assert "packages/ts-agent-kernel/ts_agent/validation/acceptance_profiles/accepted-ts__3.json" in names
    assert distribution == build_result["python_distribution"]
    assert distribution["name"] == "ts-agent-kernel"
    assert distribution["version"] == json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["version"]
    assert distribution["path"] in names
    assert sum(name.startswith("python-dist/") and name.endswith(".whl") for name in names) == 1
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
    assert (package_root / "apps" / "app-server" / "pi-app-server.mjs").is_file()
    assert (package_root / "apps" / "app-server" / "pi-session-worker.mjs").is_file()
    assert (package_root / "config" / "pi-source.json").is_file()
    assert (package_root / "config" / "pi-worker-entry.patch").is_file()
    assert (package_root / "config" / "pi-multi-workspace-create.patch").is_file()
    assert (package_root / "config" / "pi-system-prompt.patch").is_file()
    assert (package_root / "scripts" / "prepare_pi_source.py").is_file()
    assert (package_root / "packages" / "ts-agent-kernel" / "ts_agent" / "projection" / "provider.py").is_file()
    assert not (package_root / "packages" / "ts-agent-kernel" / "ts_agent" / "web").exists()
    assert (package_root / "packages" / "ts-agent-kernel" / "ts_agent" / "workspace" / "artifacts.py").is_file()
    assert (package_root / "packages" / "ts-agent-kernel" / "ts_agent" / "workspace" / "candidates.py").is_file()
    assert (package_root / "packages" / "ts-agent-kernel" / "ts_agent" / "workspace" / "claims.py").is_file()
    assert (package_root / "packages" / "ts-agent-kernel" / "ts_agent" / "workspace" / "contracts" / "observation_candidates.schema.json").is_file()
    assert (package_root / "packages" / "ts-agent-kernel" / "ts_agent" / "workspace" / "contracts" / "proof_spec.schema.json").is_file()
    installed_wheel = package_root / distribution["path"]
    assert installed_wheel.is_file()
    assert inspect_wheel(installed_wheel)["payload_sha256"] == distribution["payload_sha256"]
    assert stat.S_IMODE(package_root.stat().st_mode) == 0o500
    assert all(stat.S_IMODE(path.stat().st_mode) & 0o222 == 0 for path in package_root.rglob("*"))
    wheel_site = tmp_path / "wheel-site"
    wheel_install = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-deps",
            "--no-cache-dir",
            "--target",
            str(wheel_site),
            str(installed_wheel),
        ],
        cwd=install_root,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert wheel_install.returncode == 0, wheel_install.stderr
    assert (wheel_site / "ts_agent" / "__init__.py").is_file()
    assert not list(package_root.rglob("*.egg-info"))
    runtime_plan = subprocess.run(
        [
            sys.executable,
            str(package_root / "scripts" / "install_env.py"),
            "--package-root",
            str(package_root),
            "--env-root",
            str(tmp_path / "envs"),
            "--dry-run",
            "--json",
        ],
        cwd=install_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert runtime_plan.returncode == 0, runtime_plan.stderr
    runtime_payload = json.loads(runtime_plan.stdout)
    assert runtime_payload["python_install_source"] == "bundled-release-wheel"
    assert runtime_payload["python_wheel"]["sha256"] == distribution["sha256"]
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
    write_test_runtime_manifest(package_root, install_root)
    startup = subprocess.run(
        [str(install_root / "TSPi"), "--workspace", "release-smoke"],
        cwd=install_root,
        env={**os.environ, "PI_BIN": str(fake_pi)},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert startup.returncode == 1
    assert "no selected TSPi Package release" in startup.stderr
    assert not (install_root / "workspaces" / "release-smoke").exists()


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


def test_release_install_archives_obsolete_notification_recipient_state(tmp_path: Path) -> None:
    manifest, _release = _synthetic_release(tmp_path / "release", marker="notification-cleanup")
    install_root = tmp_path / "install"
    pi_root = install_root / ".pi"
    pi_root.mkdir(parents=True)
    retired_names = (
        "ts-email-delivery-policy.json",
        "ts-email-delivery-authorization.json",
    )
    for name in retired_names:
        path = pi_root / name
        path.write_text('{"retired": true}\n', encoding="utf-8")
        path.chmod(0o600)

    installed = _install(manifest, install_root)

    assert all(not (pi_root / name).exists() for name in retired_names)
    archived = [install_root / ref for ref in installed["archived_retired_notification_state"]]
    assert {path.name for path in archived} == set(retired_names)
    assert all(path.read_text(encoding="utf-8") == '{"retired": true}\n' for path in archived)
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in archived)
    archive_metadata = archived[0].parent / "archive.json"
    assert json.loads(archive_metadata.read_text(encoding="utf-8"))["schema_version"] == "ts-legacy-notification-state-archive/1"

    repeated = _install(manifest, install_root)
    assert repeated["archived_retired_notification_state"] == []


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
    manifest["release_id"] = f"{manifest['package']['version']}-sha256-0000000000000000"
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


def test_release_install_rejects_an_extra_python_wheel(tmp_path: Path) -> None:
    manifest_path, _ = _synthetic_release(
        tmp_path / "release",
        marker="extra-wheel",
        extra_files={"package/python-dist/other-0-py3-none-any.whl": b"not a wheel"},
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
    assert "only the declared Python wheel" in completed.stderr
    assert not (install_root / ".pi").exists()


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
    version: str = PACKAGE_VERSION,
    extra_files: dict[str, bytes] | None = None,
    required_files: frozenset[str] = REQUIRED_RUNTIME_FILES,
) -> tuple[Path, str]:
    root.mkdir(parents=True)
    temporary_archive = root / "package.tgz"
    files = {name: b"\n" for name in required_files}
    files["package.json"] = json.dumps(
        {"name": "@iawnix/ts-agent", "version": version},
        separators=(",", ":"),
    ).encode() + b"\n"
    files["TSPi"] = b"#!/usr/bin/env bash\nexit 0\n"
    files["README.md"] = f"release {marker}\n".encode()
    files.update(extra_files or {})
    python_payload = {
        normalized.removeprefix("packages/ts-agent-kernel/"): content
        for name, content in files.items()
        if (normalized := name.removeprefix("package/")).startswith("packages/ts-agent-kernel/ts_agent/")
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
            info.mode = 0o755 if name in {"TSPi", "scripts/ts_web_provider.py"} else 0o644
            archive.addfile(info, io.BytesIO(content))
    digest = hashlib.sha256(temporary_archive.read_bytes()).hexdigest()
    release_id = f"{version}-sha256-{digest[:16]}"
    archive_name = f"ts-agent-{release_id}.tgz"
    archive_path = root / archive_name
    temporary_archive.rename(archive_path)
    manifest = {
        "schema_version": "ts-agent-release/2",
        "release_id": release_id,
        "package": {"name": "@iawnix/ts-agent", "version": version},
        "python_distribution": distribution,
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


def _synthetic_wheel(root: Path, *, version: str, package_files: dict[str, bytes]) -> Path:
    wheel = root / f"ts_agent_kernel-{version}-py3-none-any.whl"
    metadata = f"Metadata-Version: 2.4\nName: ts-agent-kernel\nVersion: {version}\n\n".encode()
    with zipfile.ZipFile(wheel, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in sorted(package_files.items()):
            archive.writestr(name, content)
        archive.writestr(f"ts_agent_kernel-{version}.dist-info/METADATA", metadata)
        archive.writestr(
            f"ts_agent_kernel-{version}.dist-info/WHEEL",
            "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        )
        archive.writestr(f"ts_agent_kernel-{version}.dist-info/RECORD", "")
    return wheel
