"""Build and validate the TS Agent Python wheel without importing the package."""

from __future__ import annotations

import email.parser
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any


PYTHON_DISTRIBUTION = "ts-agent-kernel"
PI_PACKAGE = "@iawnix/ts-agent"
PYTHON_PACKAGE_NAME = "ts_agent"
PYTHON_PAYLOAD_SUFFIXES = frozenset({".css", ".html", ".js", ".json", ".py", ".svg", ".toml"})
RELEASE_MANIFEST = ".ts-agent-release.json"
RELEASE_SCHEMA_VERSION = "ts-agent-release/2"
WHEEL_DIRECTORY = "python-dist"
SOURCE_DATE_EPOCH = "315532800"


class WheelContractError(RuntimeError):
    """The Python distribution artifact does not satisfy the release contract."""


def build_wheel(
    package_root: str | Path,
    output_dir: str | Path,
    *,
    python: str | Path = sys.executable,
) -> dict[str, Any]:
    """Build one deterministic wheel from a temporary writable source copy."""

    root = Path(package_root).expanduser().resolve()
    destination = Path(output_dir).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    existing = sorted(path.name for path in destination.glob("*.whl"))
    if existing:
        raise WheelContractError(f"wheel output directory is not empty: {', '.join(existing)}")

    with tempfile.TemporaryDirectory(prefix="ts-agent-wheel-source-") as temporary:
        source = Path(temporary) / "source"
        source.mkdir()
        for name in ("pyproject.toml", "README.md"):
            path = root / name
            if not path.is_file() or path.is_symlink():
                raise WheelContractError(f"wheel source file is missing or unsafe: {path}")
            shutil.copy2(path, source / name)
        package_source = root / "packages" / "ts-agent-kernel" / PYTHON_PACKAGE_NAME
        if not package_source.is_dir() or package_source.is_symlink():
            raise WheelContractError(f"Python package source is missing or unsafe: {package_source}")
        shutil.copytree(
            package_source,
            source / "packages" / "ts-agent-kernel" / PYTHON_PACKAGE_NAME,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", "*.egg-info"),
        )

        environment = dict(os.environ)
        environment.pop("PYTHONHOME", None)
        environment.pop("PYTHONPATH", None)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        environment["PYTHONNOUSERSITE"] = "1"
        environment["SOURCE_DATE_EPOCH"] = SOURCE_DATE_EPOCH
        completed = subprocess.run(
            [
                str(Path(python).expanduser()),
                "-m",
                "pip",
                "wheel",
                "--disable-pip-version-check",
                "--no-build-isolation",
                "--no-deps",
                "--no-cache-dir",
                "--wheel-dir",
                str(destination),
                str(source),
            ],
            cwd=source,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip() or "wheel build failed"
            raise WheelContractError(detail)

    created = list(destination.glob("*.whl"))
    if len(created) != 1:
        names = ", ".join(sorted(path.name for path in created)) or "none"
        raise WheelContractError(f"wheel build must create exactly one artifact; found: {names}")
    descriptor = inspect_wheel(created[0])
    package = package_identity(root)
    if descriptor["name"] != PYTHON_DISTRIBUTION or descriptor["version"] != package["version"]:
        raise WheelContractError("wheel identity does not match package.json")
    source_digest = source_payload_sha256(root)
    if descriptor["payload_sha256"] != source_digest:
        raise WheelContractError("wheel payload does not match the authored Python source")
    return descriptor


def inspect_wheel(path: str | Path) -> dict[str, Any]:
    """Return the identity and deterministic payload digest of one wheel."""

    wheel = Path(path).expanduser().resolve()
    if not wheel.is_file() or wheel.is_symlink() or wheel.suffix != ".whl":
        raise WheelContractError(f"wheel must be one regular .whl file: {wheel}")
    records: list[tuple[str, bytes]] = []
    metadata_documents: list[bytes] = []
    seen: set[str] = set()
    try:
        with zipfile.ZipFile(wheel) as archive:
            for item in archive.infolist():
                relative = PurePosixPath(item.filename)
                if relative.is_absolute() or not relative.parts or ".." in relative.parts:
                    raise WheelContractError(f"wheel member escapes its root: {item.filename}")
                name = relative.as_posix().rstrip("/")
                if name in seen:
                    raise WheelContractError(f"wheel contains duplicate member: {name}")
                seen.add(name)
                if item.is_dir():
                    continue
                mode = item.external_attr >> 16
                if mode and (mode & 0o170000) not in {0, 0o100000}:
                    raise WheelContractError(f"wheel contains unsupported member type: {name}")
                content = archive.read(item)
                if relative.name == "METADATA" and relative.parent.name.endswith(".dist-info"):
                    metadata_documents.append(content)
                if relative.parts[0] == PYTHON_PACKAGE_NAME:
                    if not is_python_payload_path(relative):
                        raise WheelContractError(f"wheel contains unsupported package payload: {name}")
                    records.append((relative.as_posix(), content))
                elif not relative.parts[0].endswith(".dist-info"):
                    raise WheelContractError(f"wheel contains an unexpected install target: {name}")
    except zipfile.BadZipFile as exc:
        raise WheelContractError(f"invalid wheel archive: {wheel.name}") from exc

    if len(metadata_documents) != 1:
        raise WheelContractError("wheel must contain exactly one dist-info/METADATA document")
    if not records:
        raise WheelContractError("wheel contains no ts_agent package payload")
    metadata = email.parser.BytesParser().parsebytes(metadata_documents[0])
    name = metadata.get("Name")
    version = metadata.get("Version")
    if not isinstance(name, str) or not name or not isinstance(version, str) or not version:
        raise WheelContractError("wheel metadata is missing Name or Version")
    return {
        "name": name,
        "version": version,
        "filename": wheel.name,
        "sha256": sha256_file(wheel),
        "size_bytes": wheel.stat().st_size,
        "payload_sha256": payload_records_sha256(records),
    }


def release_wheel(package_root: str | Path) -> tuple[Path, dict[str, Any]] | None:
    """Resolve and revalidate the wheel bound to an installed release."""

    root = Path(package_root).expanduser().resolve()
    manifest_path = root / RELEASE_MANIFEST
    if not manifest_path.exists():
        return None
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise WheelContractError(f"release manifest must be a regular file: {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise WheelContractError(f"release manifest is not valid JSON: {manifest_path}") from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != RELEASE_SCHEMA_VERSION:
        raise WheelContractError("installed release does not declare a supported Python wheel contract")
    package = package_identity(root)
    if manifest.get("package") != package:
        raise WheelContractError("installed release package identity does not match package.json")
    expected = validate_descriptor(manifest.get("python_distribution"))
    if expected["version"] != package["version"]:
        raise WheelContractError("bundled wheel version does not match the release package")
    relative = PurePosixPath(str(expected["path"]))
    wheel = root.joinpath(*relative.parts)
    actual = inspect_wheel(wheel)
    validate_descriptor_match(expected, actual)
    source_digest = source_payload_sha256(root)
    if actual["payload_sha256"] != source_digest:
        raise WheelContractError("bundled wheel payload does not match the release source payload")
    return wheel, {**actual, "path": relative.as_posix(), "source": "bundled-release-wheel"}


def validate_descriptor(value: object) -> dict[str, Any]:
    expected_keys = {"name", "version", "path", "sha256", "size_bytes", "payload_sha256"}
    if not isinstance(value, dict) or set(value) != expected_keys:
        raise WheelContractError("invalid python_distribution descriptor")
    for key in ("name", "version", "path", "sha256", "payload_sha256"):
        if not isinstance(value.get(key), str) or not value[key]:
            raise WheelContractError(f"python_distribution.{key} must be a non-empty string")
    if value["name"] != PYTHON_DISTRIBUTION:
        raise WheelContractError(f"Python distribution name must be {PYTHON_DISTRIBUTION}")
    relative = PurePosixPath(value["path"])
    if (
        relative.is_absolute()
        or len(relative.parts) != 2
        or relative.parts[0] != WHEEL_DIRECTORY
        or ".." in relative.parts
        or not relative.name.endswith(".whl")
    ):
        raise WheelContractError("python_distribution.path must name one wheel under python-dist/")
    if not relative.name.startswith(f"ts_agent_kernel-{value['version']}-"):
        raise WheelContractError("Python wheel filename does not match the distribution version")
    if len(value["sha256"]) != 64 or any(character not in "0123456789abcdef" for character in value["sha256"]):
        raise WheelContractError("python_distribution.sha256 must be a lowercase SHA-256 digest")
    if len(value["payload_sha256"]) != 64 or any(
        character not in "0123456789abcdef" for character in value["payload_sha256"]
    ):
        raise WheelContractError("python_distribution.payload_sha256 must be a lowercase SHA-256 digest")
    size = value.get("size_bytes")
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        raise WheelContractError("python_distribution.size_bytes must be a positive integer")
    return dict(value)


def validate_descriptor_match(expected: dict[str, Any], actual: dict[str, Any]) -> None:
    for key in ("name", "version", "sha256", "size_bytes", "payload_sha256"):
        if expected[key] != actual[key]:
            raise WheelContractError(f"Python wheel {key} does not match the release manifest")
    if PurePosixPath(expected["path"]).name != actual["filename"]:
        raise WheelContractError("Python wheel filename does not match the release manifest")


def source_payload_sha256(package_root: str | Path) -> str:
    root = Path(package_root).expanduser().resolve() / "packages" / "ts-agent-kernel"
    if not root.is_dir():
        raise WheelContractError(f"Python source root is missing: {root}")
    records: list[tuple[str, bytes]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        relative = PurePosixPath(path.relative_to(root).as_posix())
        if is_python_payload_path(relative):
            records.append((relative.as_posix(), path.read_bytes()))
    if not records:
        raise WheelContractError(f"Python source payload is empty: {root}")
    return payload_records_sha256(records)


def package_identity(package_root: str | Path) -> dict[str, str]:
    path = Path(package_root).expanduser().resolve() / "package.json"
    if not path.is_file() or path.is_symlink():
        raise WheelContractError(f"package.json is missing or unsafe: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise WheelContractError(f"package.json is not valid JSON: {path}") from exc
    if not isinstance(value, dict) or value.get("name") != PI_PACKAGE:
        raise WheelContractError(f"package.json name must be {PI_PACKAGE}")
    version = value.get("version")
    if not isinstance(version, str) or not version:
        raise WheelContractError("package.json version must be a non-empty string")
    return {"name": PI_PACKAGE, "version": version}


def is_python_payload_path(path: PurePosixPath) -> bool:
    return (
        bool(path.parts)
        and path.parts[0] == PYTHON_PACKAGE_NAME
        and "__pycache__" not in path.parts
        and not any(part.endswith(".egg-info") for part in path.parts)
        and path.suffix in PYTHON_PAYLOAD_SUFFIXES
    )


def payload_records_sha256(records: list[tuple[str, bytes]]) -> str:
    digest = hashlib.sha256()
    for relative, content in sorted(records):
        encoded = relative.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
