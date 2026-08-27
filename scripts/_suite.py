"""Contracts and archive helpers for the complete TSPi Package release."""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import re
import shutil
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

try:
    from ._wheel import WheelContractError, validate_descriptor
    from .install_release import ReleaseInstallError, load_manifest as _load_agent_manifest
except ImportError:
    from _wheel import WheelContractError, validate_descriptor
    from install_release import ReleaseInstallError, load_manifest as _load_agent_manifest


SUITE_SCHEMA_VERSION = "tspi-package-release/1"
SUITE_COMPONENTS_SCHEMA_VERSION = "tspi-package-components/1"
SUITE_INSTALL_SCHEMA_VERSION = "tspi-package-install/1"
PHONE_SCHEMA_VERSION = "ts-phone-component-release/1"
SUITE_MANIFEST_NAME = "tspi-package-release.json"
SUITE_PACKAGE_NAME = "@iawnix/tspi"
SHA256 = re.compile(r"^[0-9a-f]{64}$")
RELEASE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")
EXPECTED_PHONE_PROTOCOLS = {
    "api": "ts-phone-api/3",
    "events": "ts-phone-events/3",
    "bridge": "ts-phone-bridge/2",
}
WEB_COMPONENT = {
    "embedded_in": "agent",
    "kernel_protocol": "ts-research-kernel/5",
    "projection_protocol": "ts-web-workspace/5",
    "graph_protocol": "ts-explorer-graph/5",
}
PHONE_REQUIRED_FILES = {
    "VERSION",
    "README.md",
    "package.json",
    "services/server/package.json",
    "services/server/dist/index.js",
    "services/server/dist/cli.js",
    "bin/ts-phone-ctl",
    "bin/ts-phone-server",
    "deploy/server.env.example",
    "packages/protocol/versions.json",
    "packages/protocol/bridge.schema.json",
    "packages/protocol/events.schema.json",
    "packages/protocol/openapi.yaml",
    "docs/architecture.md",
    "docs/deployment.md",
    "docs/recovery.md",
    "docs/security.md",
}
PHONE_FORBIDDEN_PARTS = {
    ".git",
    ".gradle",
    ".runtime",
    "build",
    "node_modules",
    "tests",
    "test",
}
PHONE_FORBIDDEN_FILES = {
    "deploy/systemd/ts-phone.service",
}
MAX_ARCHIVE_MEMBER_BYTES = 512 * 1024 * 1024
MAX_ARCHIVE_TOTAL_BYTES = 1024 * 1024 * 1024


class SuiteReleaseError(RuntimeError):
    """Raised when a suite release violates its immutable component contract."""


def load_agent_manifest(path: Path) -> dict[str, Any]:
    try:
        return _load_agent_manifest(path)
    except (ReleaseInstallError, WheelContractError) as error:
        raise SuiteReleaseError(f"invalid Agent component manifest: {error}") from error


def load_phone_manifest(path: Path) -> dict[str, Any]:
    return validate_phone_manifest(read_json_object(path, "TS Phone component manifest"))


def validate_phone_manifest(value: object) -> dict[str, Any]:
    manifest = exact_object(
        value,
        "TS Phone component manifest",
        {
            "schema_version",
            "release_id",
            "component",
            "protocols",
            "server_entry",
            "mobile_artifact",
            "archive",
            "source",
            "created_at_utc",
        },
    )
    if manifest.get("schema_version") != PHONE_SCHEMA_VERSION:
        raise SuiteReleaseError("unsupported TS Phone component manifest schema")
    release_id = require_release_id(manifest.get("release_id"), "phone release_id")
    component = exact_object(
        manifest.get("component"),
        "phone component",
        {"name", "server_version", "mobile_version", "mobile_build"},
    )
    if component.get("name") != "ts-phone":
        raise SuiteReleaseError("phone component name must be ts-phone")
    for key in ("server_version", "mobile_version"):
        require_string(component.get(key), f"phone component.{key}")
    mobile_build = component.get("mobile_build")
    if not isinstance(mobile_build, int) or isinstance(mobile_build, bool) or mobile_build <= 0:
        raise SuiteReleaseError("phone component.mobile_build must be a positive integer")
    protocols = exact_object(manifest.get("protocols"), "phone protocols", set(EXPECTED_PHONE_PROTOCOLS))
    if protocols != EXPECTED_PHONE_PROTOCOLS:
        raise SuiteReleaseError("phone protocol set is incompatible with this TSPi Package")
    server_entry = validate_file_descriptor(manifest.get("server_entry"), "phone server_entry", key="path")
    if server_entry["path"] != "services/server/dist/index.js":
        raise SuiteReleaseError("phone server entry path is invalid")
    mobile = exact_object(
        manifest.get("mobile_artifact"),
        "phone mobile_artifact",
        {"path", "sha256", "size_bytes", "abi", "certificate_sha256"},
    )
    validate_file_descriptor({key: mobile[key] for key in ("path", "sha256", "size_bytes")}, "phone mobile_artifact", key="path")
    if mobile.get("abi") != "arm64-v8a":
        raise SuiteReleaseError("phone mobile artifact must target arm64-v8a")
    require_sha256(mobile.get("certificate_sha256"), "phone mobile certificate")
    archive = validate_file_descriptor(manifest.get("archive"), "phone archive", key="filename")
    expected_release_id = (
        f"{component['server_version']}-mobile-{component['mobile_version']}-"
        f"build{mobile_build}-sha256-{archive['sha256'][:16]}"
    )
    if release_id != expected_release_id:
        raise SuiteReleaseError("phone release_id does not match its versions and archive digest")
    if archive["filename"] != f"ts-phone-component-{release_id}.tgz":
        raise SuiteReleaseError("phone archive filename does not match release_id")
    validate_source(manifest.get("source"), "phone source")
    require_string(manifest.get("created_at_utc"), "phone created_at_utc")
    return manifest


def suite_components(agent: dict[str, Any], phone: dict[str, Any]) -> dict[str, Any]:
    agent_archive = agent["archive"]
    phone_archive = phone["archive"]
    return {
        "agent": {
            "release_id": agent["release_id"],
            "version": agent["package"]["version"],
            "archive": {
                "path": f"components/agent/{agent_archive['filename']}",
                "sha256": agent_archive["sha256"],
                "size_bytes": agent_archive["size_bytes"],
            },
            "python_distribution": agent["python_distribution"],
            "source": agent["source"],
        },
        "web": dict(WEB_COMPONENT),
        "phone": {
            "release_id": phone["release_id"],
            "server_version": phone["component"]["server_version"],
            "mobile_version": phone["component"]["mobile_version"],
            "mobile_build": phone["component"]["mobile_build"],
            "protocols": phone["protocols"],
            "archive": {
                "path": f"components/phone/{phone_archive['filename']}",
                "sha256": phone_archive["sha256"],
                "size_bytes": phone_archive["size_bytes"],
            },
            "server_entry": phone["server_entry"],
            "mobile_artifact": phone["mobile_artifact"],
            "source": phone["source"],
        },
    }


def validate_components(value: object) -> dict[str, Any]:
    components = exact_object(value, "suite components", {"agent", "web", "phone"})
    agent = exact_object(
        components.get("agent"),
        "suite agent component",
        {"release_id", "version", "archive", "python_distribution", "source"},
    )
    agent_release_id = require_release_id(agent.get("release_id"), "suite agent release_id")
    agent_version = require_string(agent.get("version"), "suite agent version")
    agent_archive = validate_file_descriptor(agent.get("archive"), "suite agent archive", key="path")
    expected_agent_archive = f"components/agent/ts-agent-{agent_release_id}.tgz"
    if agent_archive["path"] != expected_agent_archive:
        raise SuiteReleaseError(f"suite Agent archive path must be {expected_agent_archive}")
    try:
        distribution = validate_descriptor(agent.get("python_distribution"))
    except WheelContractError as error:
        raise SuiteReleaseError(f"invalid suite Agent python_distribution: {error}") from error
    if distribution["version"] != agent_version:
        raise SuiteReleaseError("suite Agent Python distribution version does not match the component version")
    validate_source(agent.get("source"), "suite agent source")
    web = exact_object(components.get("web"), "suite web component", set(WEB_COMPONENT))
    if web != WEB_COMPONENT:
        raise SuiteReleaseError("suite Web component contract is incompatible")
    phone = exact_object(
        components.get("phone"),
        "suite phone component",
        {
            "release_id",
            "server_version",
            "mobile_version",
            "mobile_build",
            "protocols",
            "archive",
            "server_entry",
            "mobile_artifact",
            "source",
        },
    )
    phone_release_id = require_release_id(phone.get("release_id"), "suite phone release_id")
    require_string(phone.get("server_version"), "suite phone server_version")
    require_string(phone.get("mobile_version"), "suite phone mobile_version")
    if not isinstance(phone.get("mobile_build"), int) or isinstance(phone["mobile_build"], bool) or phone["mobile_build"] <= 0:
        raise SuiteReleaseError("suite phone mobile_build must be a positive integer")
    if exact_object(phone.get("protocols"), "suite phone protocols", set(EXPECTED_PHONE_PROTOCOLS)) != EXPECTED_PHONE_PROTOCOLS:
        raise SuiteReleaseError("suite phone protocols are incompatible")
    phone_archive = validate_file_descriptor(phone.get("archive"), "suite phone archive", key="path")
    expected_phone_archive = f"components/phone/ts-phone-component-{phone_release_id}.tgz"
    if phone_archive["path"] != expected_phone_archive:
        raise SuiteReleaseError(f"suite Phone archive path must be {expected_phone_archive}")
    server_entry = validate_file_descriptor(phone.get("server_entry"), "suite phone server_entry", key="path")
    if server_entry["path"] != "services/server/dist/index.js":
        raise SuiteReleaseError("suite Phone server entry path is invalid")
    mobile = exact_object(
        phone.get("mobile_artifact"),
        "suite phone mobile_artifact",
        {"path", "sha256", "size_bytes", "abi", "certificate_sha256"},
    )
    validate_file_descriptor({key: mobile[key] for key in ("path", "sha256", "size_bytes")}, "suite phone mobile artifact", key="path")
    if mobile.get("abi") != "arm64-v8a":
        raise SuiteReleaseError("suite phone mobile artifact ABI is incompatible")
    expected_mobile_path = (
        f"artifacts/ts-phone-v{phone['mobile_version']}-build{phone['mobile_build']}-arm64-v8a-release.apk"
    )
    if mobile["path"] != expected_mobile_path:
        raise SuiteReleaseError(f"suite Phone mobile artifact path must be {expected_mobile_path}")
    require_sha256(mobile.get("certificate_sha256"), "suite phone mobile certificate")
    validate_source(phone.get("source"), "suite phone source")
    return components


def validate_suite_manifest(value: object) -> dict[str, Any]:
    manifest = exact_object(
        value,
        "TSPi Package manifest",
        {"schema_version", "release_id", "package", "components", "archive", "created_at_utc"},
    )
    if manifest.get("schema_version") != SUITE_SCHEMA_VERSION:
        raise SuiteReleaseError("unsupported TSPi Package manifest schema")
    release_id = require_release_id(manifest.get("release_id"), "suite release_id")
    package = exact_object(manifest.get("package"), "suite package", {"name", "version"})
    if package.get("name") != SUITE_PACKAGE_NAME:
        raise SuiteReleaseError(f"suite package name must be {SUITE_PACKAGE_NAME}")
    version = require_string(package.get("version"), "suite package.version")
    components = validate_components(manifest.get("components"))
    if components["agent"]["version"] != version:
        raise SuiteReleaseError("suite package version must match the Agent component version")
    archive = validate_file_descriptor(manifest.get("archive"), "suite archive", key="filename")
    expected_release_id = f"{version}-sha256-{archive['sha256'][:16]}"
    if release_id != expected_release_id:
        raise SuiteReleaseError("suite release_id does not match package version and archive digest")
    if archive["filename"] != f"tspi-package-{release_id}.tgz":
        raise SuiteReleaseError("suite archive filename does not match release_id")
    require_string(manifest.get("created_at_utc"), "suite created_at_utc")
    return manifest


def write_suite_archive(
    destination: Path,
    components: dict[str, Any],
    agent_archive: Path,
    phone_archive: Path,
) -> None:
    records = [
        (PurePosixPath("components.json"), canonical_json({"schema_version": SUITE_COMPONENTS_SCHEMA_VERSION, "components": components}) + b"\n", 0o644),
        (PurePosixPath(components["agent"]["archive"]["path"]), require_regular_file(agent_archive).read_bytes(), 0o644),
        (PurePosixPath(components["phone"]["archive"]["path"]), require_regular_file(phone_archive).read_bytes(), 0o644),
    ]
    write_deterministic_archive(destination, "package", records)


def write_deterministic_archive(
    destination: Path,
    root_name: str,
    records: Iterable[tuple[PurePosixPath, bytes, int]],
) -> None:
    prepared = sorted(records, key=lambda item: item[0].as_posix())
    directories = {PurePosixPath(root_name)}
    for relative, _, _ in prepared:
        safe_relative(relative.as_posix())
        parent = PurePosixPath(root_name) / relative.parent
        while parent.parts:
            directories.add(parent)
            if parent == PurePosixPath(root_name):
                break
            parent = parent.parent
    with destination.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
                for directory in sorted(directories, key=lambda item: (len(item.parts), item.as_posix())):
                    info = normalized_tar_info(directory.as_posix() + "/", mode=0o755, size=0)
                    info.type = tarfile.DIRTYPE
                    archive.addfile(info)
                for relative, content, mode in prepared:
                    info = normalized_tar_info((PurePosixPath(root_name) / relative).as_posix(), mode=mode, size=len(content))
                    archive.addfile(info, io.BytesIO(content))


def inspect_rooted_archive(
    path: Path,
    root_name: str,
) -> tuple[list[tuple[tarfile.TarInfo, PurePosixPath]], set[str]]:
    require_regular_file(path)
    inspected: list[tuple[tarfile.TarInfo, PurePosixPath]] = []
    files: set[str] = set()
    seen: set[str] = set()
    total = 0
    with tarfile.open(path, "r:gz") as archive:
        for member in archive.getmembers():
            raw = PurePosixPath(member.name)
            if raw.is_absolute() or not raw.parts or raw.parts[0] != root_name or ".." in raw.parts:
                raise SuiteReleaseError(f"archive member escapes {root_name}: {member.name}")
            relative = PurePosixPath(*raw.parts[1:])
            if not relative.parts:
                if not member.isdir():
                    raise SuiteReleaseError(f"archive {root_name} root must be a directory")
                continue
            name = relative.as_posix()
            if name in seen:
                raise SuiteReleaseError(f"archive contains duplicate member: {name}")
            seen.add(name)
            if not member.isdir() and not member.isreg():
                raise SuiteReleaseError(f"archive contains unsupported member type: {name}")
            if member.size < 0 or member.size > MAX_ARCHIVE_MEMBER_BYTES:
                raise SuiteReleaseError(f"archive member is too large: {name}")
            total += member.size
            if total > MAX_ARCHIVE_TOTAL_BYTES:
                raise SuiteReleaseError("archive expands beyond the package size limit")
            inspected.append((member, relative))
            if member.isreg():
                files.add(name)
    return inspected, files


def extract_rooted_archive(
    archive_path: Path,
    members: list[tuple[tarfile.TarInfo, PurePosixPath]],
    destination: Path,
) -> None:
    with tarfile.open(archive_path, "r:gz") as archive:
        for member, relative in sorted(members, key=lambda item: (len(item[1].parts), item[1].as_posix())):
            target = destination.joinpath(*relative.parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True, mode=0o700)
                continue
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            source = archive.extractfile(member)
            if source is None:
                raise SuiteReleaseError(f"could not read archive member: {relative.as_posix()}")
            with source, target.open("xb") as handle:
                shutil.copyfileobj(source, handle)
                handle.flush()
                os.fsync(handle.fileno())
            target.chmod(0o700 if member.mode & 0o111 else 0o600)


def validate_phone_runtime(root: Path, descriptor: dict[str, Any]) -> None:
    for relative in PHONE_REQUIRED_FILES:
        require_regular_file(root / relative)
    package = read_json_object(root / "package.json", "installed TS Phone package")
    if package.get("name") != "ts-phone":
        raise SuiteReleaseError("installed TS Phone package name is invalid")
    if package.get("version") != descriptor["server_version"]:
        raise SuiteReleaseError("installed TS Phone package version does not match the suite manifest")
    server_package = read_json_object(
        root / "services" / "server" / "package.json",
        "installed TS Phone server package",
    )
    if server_package.get("name") != "@iawnix/ts-phone-server":
        raise SuiteReleaseError("installed TS Phone server package name is invalid")
    if server_package.get("version") != descriptor["server_version"]:
        raise SuiteReleaseError("installed TS Phone server package version does not match the suite manifest")
    if (root / "VERSION").read_text(encoding="utf-8").strip() != descriptor["server_version"]:
        raise SuiteReleaseError("installed TS Phone VERSION does not match the suite manifest")
    protocol_set = read_json_object(root / "packages" / "protocol" / "versions.json", "installed phone protocols")
    expected_protocols = {"schema_version": "ts-phone-protocol-set/1", **descriptor["protocols"]}
    if protocol_set != expected_protocols:
        raise SuiteReleaseError("installed TS Phone protocols do not match the suite manifest")
    validate_runtime_file(root, descriptor["server_entry"], "phone server entry")
    validate_runtime_file(root, descriptor["mobile_artifact"], "phone mobile artifact")
    for executable in (root / "bin" / "ts-phone-ctl", root / "bin" / "ts-phone-server"):
        if not os.access(executable, os.X_OK):
            raise SuiteReleaseError(f"installed TS Phone entrypoint is not executable: {executable}")


def validate_phone_archive_files(files: set[str], descriptor: dict[str, Any]) -> None:
    required = {*PHONE_REQUIRED_FILES, descriptor["mobile_artifact"]["path"]}
    missing = sorted(required - files)
    if missing:
        raise SuiteReleaseError(f"Phone component archive is missing runtime files: {', '.join(missing)}")
    for name in files:
        relative = safe_relative(name)
        if name in PHONE_FORBIDDEN_FILES:
            raise SuiteReleaseError(f"Phone component archive contains installation-owned content: {name}")
        if PHONE_FORBIDDEN_PARTS.intersection(relative.parts):
            raise SuiteReleaseError(f"Phone component archive contains development-only content: {name}")
        if relative.name.startswith(".env") or relative.suffix in {".jks", ".keystore", ".p12", ".pyc", ".pyo"}:
            raise SuiteReleaseError(f"Phone component archive contains forbidden runtime content: {name}")


def validate_runtime_file(root: Path, descriptor: dict[str, Any], label: str) -> None:
    relative = safe_relative(str(descriptor["path"]))
    path = require_regular_file(root.joinpath(*relative.parts))
    if path.stat().st_size != descriptor["size_bytes"] or sha256_file(path) != descriptor["sha256"]:
        raise SuiteReleaseError(f"installed {label} does not match its release descriptor")


def verify_archive_descriptor(path: Path, descriptor: dict[str, Any], label: str) -> Path:
    archive = require_regular_file(path)
    if archive.stat().st_size != descriptor["size_bytes"]:
        raise SuiteReleaseError(f"{label} size does not match its descriptor")
    if sha256_file(archive) != descriptor["sha256"]:
        raise SuiteReleaseError(f"{label} SHA-256 does not match its descriptor")
    return archive


def validate_source(value: object, label: str) -> dict[str, Any]:
    source = exact_object(value, label, {"git_commit", "dirty"})
    if source.get("git_commit") is not None:
        require_string(source.get("git_commit"), f"{label}.git_commit")
    if not isinstance(source.get("dirty"), bool):
        raise SuiteReleaseError(f"{label}.dirty must be boolean")
    return source


def validate_file_descriptor(value: object, label: str, *, key: str) -> dict[str, Any]:
    descriptor = exact_object(value, label, {key, "sha256", "size_bytes"})
    name = require_string(descriptor.get(key), f"{label}.{key}")
    if key == "path":
        safe_relative(name)
    elif Path(name).name != name:
        raise SuiteReleaseError(f"{label}.{key} must be one basename")
    require_sha256(descriptor.get("sha256"), f"{label}.sha256")
    size = descriptor.get("size_bytes")
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        raise SuiteReleaseError(f"{label}.size_bytes must be a positive integer")
    return descriptor


def read_json_object(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(require_regular_file(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SuiteReleaseError(f"{label} must contain an object")
    return value


def exact_object(value: object, label: str, keys: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise SuiteReleaseError(f"{label} must contain exactly: {', '.join(sorted(keys))}")
    return value


def require_release_id(value: object, label: str) -> str:
    parsed = require_string(value, label)
    if not RELEASE_ID.fullmatch(parsed):
        raise SuiteReleaseError(f"{label} contains unsupported characters")
    return parsed


def require_sha256(value: object, label: str) -> str:
    parsed = require_string(value, label)
    if not SHA256.fullmatch(parsed):
        raise SuiteReleaseError(f"{label} must be a lowercase SHA-256 digest")
    return parsed


def require_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise SuiteReleaseError(f"{label} must be a non-empty string")
    return value


def safe_relative(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or ".." in path.parts or "." in path.parts:
        raise SuiteReleaseError(f"unsafe package path: {value}")
    return path


def require_regular_file(path: Path) -> Path:
    if not path.is_file() or path.is_symlink():
        raise SuiteReleaseError(f"required file is missing or unsafe: {path}")
    return path


def normalized_tar_info(name: str, *, mode: int, size: int) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.mode = mode
    info.size = size
    info.mtime = 0
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    return info


def canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_json(path: Path, value: dict[str, Any], *, mode: int = 0o600) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
