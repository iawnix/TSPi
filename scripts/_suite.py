"""Contracts and archive helpers for a selected TSPi Package release."""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import re
import shutil
import stat
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


SUITE_SCHEMA_VERSION = "tspi-package-release/4"
SUITE_COMPONENTS_SCHEMA_VERSION = "tspi-package-components/4"
SUITE_INSTALL_SCHEMA_VERSION = "tspi-package-install/1"
WEB_SCHEMA_VERSION = "ts-web-component-release/1"
WEB_COMPONENT_PACKAGE_NAME = "@iawnix/ts-web"
WEB_PROVIDER_PROTOCOL = "ts-web-provider/1"
WEB_PROJECTION_PROTOCOL = "ts-web-workspace/6"
WEB_GRAPH_PROTOCOL = "ts-explorer-graph/6"
WEB_THEME_PROTOCOL = "ts-theme/1"
SUITE_MANIFEST_NAME = "tspi-package-release.json"
SUITE_PACKAGE_NAME = "@iawnix/tspi"
SHA256 = re.compile(r"^[0-9a-f]{64}$")
SEMANTIC_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
RELEASE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")
WEB_COMPONENT_FILES = frozenset(
    {
        "README.md",
        "README.zh-CN.md",
        "package.json",
        "bin/ts-web",
        "ts_web/__init__.py",
        "ts_web/cli.py",
        "ts_web/provider.py",
        "ts_web/registry.py",
        "ts_web/reloader.py",
        "ts_web/server.py",
        "static/index.html",
        "static/app.css",
        "static/app.js",
        "static/i18n.js",
        "static/logo.svg",
        "static/favicon.svg",
        "static/research-tree.js",
        "static/research-map.js",
        "static/claim-map.js",
        "static/attempt-timeline.js",
    }
)
WEB_PROTOCOLS = {
    "provider": WEB_PROVIDER_PROTOCOL,
    "projection": WEB_PROJECTION_PROTOCOL,
    "graph": WEB_GRAPH_PROTOCOL,
    "theme": WEB_THEME_PROTOCOL,
}
MAX_ARCHIVE_MEMBER_BYTES = 512 * 1024 * 1024
MAX_ARCHIVE_TOTAL_BYTES = 1024 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 100_000
MAX_ARCHIVE_PATH_CHARS = 4096
MAX_COMPONENT_ARCHIVE_BYTES = MAX_ARCHIVE_MEMBER_BYTES


class SuiteReleaseError(RuntimeError):
    """Raised when a suite release violates its immutable component contract."""


def load_agent_manifest(path: Path) -> dict[str, Any]:
    try:
        return _load_agent_manifest(path)
    except (ReleaseInstallError, WheelContractError) as error:
        raise SuiteReleaseError(f"invalid Agent component manifest: {error}") from error


def load_web_manifest(path: Path) -> dict[str, Any]:
    manifest = validate_web_manifest(read_json_object(path, "TS Web component manifest"))
    archive = path.parent / manifest["archive"]["filename"]
    content = read_verified_file_snapshot(
        archive,
        manifest["archive"],
        "TS Web component archive",
        max_bytes=MAX_COMPONENT_ARCHIVE_BYTES,
    )
    validate_web_component_archive(content, manifest)
    return manifest


def validate_web_manifest(value: object) -> dict[str, Any]:
    manifest = exact_object(
        value,
        "TS Web component manifest",
        {"schema_version", "release_id", "component", "protocols", "entrypoint", "archive", "source", "created_at_utc"},
    )
    if manifest.get("schema_version") != WEB_SCHEMA_VERSION:
        raise SuiteReleaseError("unsupported TS Web component manifest schema")
    release_id = require_release_id(manifest.get("release_id"), "web release_id")
    component = exact_object(manifest.get("component"), "web component", {"name", "version"})
    if component.get("name") != "ts-web":
        raise SuiteReleaseError("Web component name must be ts-web")
    version = require_string(component.get("version"), "web component.version")
    if not SEMANTIC_VERSION.fullmatch(version):
        raise SuiteReleaseError("web component.version must use semantic x.y.z form")
    protocols = exact_object(manifest.get("protocols"), "web protocols", set(WEB_PROTOCOLS))
    if protocols != WEB_PROTOCOLS:
        raise SuiteReleaseError("Web component protocols are incompatible with this TSPi Package")
    entrypoint = exact_object(manifest.get("entrypoint"), "web entrypoint", {"path"})
    if not isinstance(entrypoint.get("path"), str) or entrypoint["path"] != "bin/ts-web":
        raise SuiteReleaseError("Web component entrypoint path is invalid")
    archive = validate_file_descriptor(manifest.get("archive"), "web archive", key="filename")
    source = validate_source(manifest.get("source"), "web source")
    expected_release_id = f"{version}-sha256-{archive['sha256'][:16]}"
    if release_id != expected_release_id:
        raise SuiteReleaseError("web release_id does not match component version and archive digest")
    if archive["filename"] != f"ts-web-component-{release_id}.tgz":
        raise SuiteReleaseError("Web archive filename does not match release_id")
    require_string(manifest.get("created_at_utc"), "web created_at_utc")
    return manifest


def suite_components(
    agent: dict[str, Any],
    *,
    include_web: bool = True,
    web: dict[str, Any] | None = None,
) -> dict[str, Any]:
    agent_archive = agent["archive"]
    components: dict[str, Any] = {
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
    }
    if include_web:
        if web is None:
            raise SuiteReleaseError("TS Web component manifest is required when Web is selected")
        components["web"] = {
            "release_id": web["release_id"],
            "version": web["component"]["version"],
            "protocols": web["protocols"],
            "entrypoint": web["entrypoint"],
            "archive": {
                "path": f"components/web/{web['archive']['filename']}",
                "sha256": web["archive"]["sha256"],
                "size_bytes": web["archive"]["size_bytes"],
            },
            "source": web["source"],
        }
    return components


def suite_components_schema_version(schema_version: str) -> str:
    if schema_version == SUITE_SCHEMA_VERSION:
        return SUITE_COMPONENTS_SCHEMA_VERSION
    raise SuiteReleaseError("unsupported TSPi Package manifest schema")


def validate_components(
    value: object,
    *,
    schema_version: str = SUITE_COMPONENTS_SCHEMA_VERSION,
) -> dict[str, Any]:
    if schema_version != SUITE_COMPONENTS_SCHEMA_VERSION:
        raise SuiteReleaseError("unsupported TSPi Package components schema")
    if (
        not isinstance(value, dict)
        or "agent" not in value
        or not set(value).issubset({"agent", "web"})
    ):
        raise SuiteReleaseError("suite components must contain Agent and only optional Web")
    components = value
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
    if "web" in components:
        _validate_suite_web_component(components["web"])
    return components


def _validate_suite_web_component(value: object) -> None:
    web = exact_object(
        value,
        "suite web component",
        {"release_id", "version", "protocols", "entrypoint", "archive", "source"},
    )
    release_id = require_release_id(web.get("release_id"), "suite web release_id")
    version = require_string(web.get("version"), "suite web version")
    if not SEMANTIC_VERSION.fullmatch(version):
        raise SuiteReleaseError("suite Web version must use semantic x.y.z form")
    if exact_object(web.get("protocols"), "suite web protocols", set(WEB_PROTOCOLS)) != WEB_PROTOCOLS:
        raise SuiteReleaseError("suite Web protocols are incompatible")
    entrypoint = exact_object(web.get("entrypoint"), "suite web entrypoint", {"path"})
    if not isinstance(entrypoint.get("path"), str) or entrypoint["path"] != "bin/ts-web":
        raise SuiteReleaseError("suite Web entrypoint path is invalid")
    archive = validate_file_descriptor(web.get("archive"), "suite web archive", key="path")
    expected_archive = f"components/web/ts-web-component-{release_id}.tgz"
    if archive["path"] != expected_archive:
        raise SuiteReleaseError(f"suite Web archive path must be {expected_archive}")
    expected_release_id = f"{version}-sha256-{archive['sha256'][:16]}"
    if release_id != expected_release_id:
        raise SuiteReleaseError("suite Web release_id does not match version and archive digest")
    validate_source(web.get("source"), "suite web source")


def validate_suite_manifest(value: object) -> dict[str, Any]:
    manifest = exact_object(
        value,
        "TSPi Package manifest",
        {"schema_version", "release_id", "package", "components", "archive", "created_at_utc"},
    )
    schema_version = manifest.get("schema_version")
    if schema_version != SUITE_SCHEMA_VERSION:
        raise SuiteReleaseError("unsupported TSPi Package manifest schema")
    release_id = require_release_id(manifest.get("release_id"), "suite release_id")
    package = exact_object(manifest.get("package"), "suite package", {"name", "version"})
    if package.get("name") != SUITE_PACKAGE_NAME:
        raise SuiteReleaseError(f"suite package name must be {SUITE_PACKAGE_NAME}")
    version = require_string(package.get("version"), "suite package.version")
    components = validate_components(
        manifest.get("components"),
        schema_version=suite_components_schema_version(schema_version),
    )
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
    web_archive: Path | None = None,
) -> None:
    records = [
        (PurePosixPath("components.json"), canonical_json({"schema_version": SUITE_COMPONENTS_SCHEMA_VERSION, "components": components}) + b"\n", 0o644),
        (
            PurePosixPath(components["agent"]["archive"]["path"]),
            read_verified_file_snapshot(
                agent_archive,
                components["agent"]["archive"],
                "Agent component archive",
                max_bytes=MAX_COMPONENT_ARCHIVE_BYTES,
            ),
            0o644,
        ),
    ]
    if "web" in components:
        if web_archive is None:
            raise SuiteReleaseError("Web component archive is required when Web is selected")
        records.append(
            (
                PurePosixPath(components["web"]["archive"]["path"]),
                read_verified_file_snapshot(
                    web_archive,
                    components["web"]["archive"],
                    "TS Web component archive",
                    max_bytes=MAX_COMPONENT_ARCHIVE_BYTES,
                ),
                0o644,
            )
        )
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
    try:
        with tarfile.open(path, "r:gz") as archive:
            return inspect_rooted_archive_members(archive, root_name)
    except (OSError, tarfile.TarError) as error:
        raise SuiteReleaseError(f"could not inspect {root_name} archive: {error}") from error


def inspect_rooted_archive_members(
    archive: tarfile.TarFile,
    root_name: str,
) -> tuple[list[tuple[tarfile.TarInfo, PurePosixPath]], set[str]]:
    inspected: list[tuple[tarfile.TarInfo, PurePosixPath]] = []
    files: set[str] = set()
    seen: set[str] = set()
    total = 0
    for member_number, member in enumerate(archive, start=1):
        if member_number > MAX_ARCHIVE_MEMBERS:
            raise SuiteReleaseError("archive contains too many members")
        if len(member.name) > MAX_ARCHIVE_PATH_CHARS:
            raise SuiteReleaseError("archive member path exceeds the size limit")
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



def validate_web_archive_files(files: set[str]) -> None:
    missing = sorted(WEB_COMPONENT_FILES - files)
    if missing:
        raise SuiteReleaseError(f"TS Web component archive is missing runtime files: {', '.join(missing)}")
    forbidden = sorted(
        name
        for name in files
        if set(PurePosixPath(name).parts) & {".git", "__pycache__", "build", "dist", "node_modules", "tests"}
        or name.endswith((".pyc", ".pyo"))
        or name.startswith(("ts_agent/", "packages/", "source/"))
    )
    if forbidden:
        raise SuiteReleaseError(f"TS Web component archive contains forbidden runtime content: {', '.join(forbidden)}")


def validate_web_component_archive(content: bytes, manifest: dict[str, Any]) -> None:
    """Validate Web bytes before they enter a suite or an installation."""

    try:
        with tarfile.open(fileobj=io.BytesIO(content), mode="r:gz") as archive:
            inspected, files = inspect_rooted_archive_members(archive, "component")
            validate_web_archive_files(files)
            members = {relative.as_posix(): member for member, relative in inspected if member.isreg()}

            def read_member(name: str) -> bytes:
                member = members.get(name)
                if member is None:
                    raise SuiteReleaseError(f"TS Web component archive is missing {name}")
                handle = archive.extractfile(member)
                if handle is None:
                    raise SuiteReleaseError(f"TS Web component archive cannot read {name}")
                with handle:
                    return handle.read(MAX_ARCHIVE_MEMBER_BYTES + 1)

            try:
                package = json.loads(read_member("package.json"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise SuiteReleaseError("TS Web component package metadata is invalid") from error
            component = manifest.get("component")
            expected_version = component.get("version") if isinstance(component, dict) else manifest.get("version")
            if not isinstance(package, dict) or package.get("name") != WEB_COMPONENT_PACKAGE_NAME:
                raise SuiteReleaseError("TS Web component package name is invalid")
            if package.get("version") != expected_version:
                raise SuiteReleaseError("TS Web component package version does not match its manifest")
            if package.get("protocols") != manifest.get("protocols"):
                raise SuiteReleaseError("TS Web component package protocols do not match its manifest")
            entrypoint = manifest.get("entrypoint")
            entrypoint_path = entrypoint.get("path") if isinstance(entrypoint, dict) else None
            entrypoint_member = members.get(entrypoint_path)
            if entrypoint_member is None or not entrypoint_member.mode & 0o111:
                raise SuiteReleaseError("TS Web component entrypoint is not executable")
            for name in files:
                if name.endswith(".py") and b"ts_agent" in read_member(name):
                    raise SuiteReleaseError(f"TS Web component imports private TSPi module: {name}")
    except (OSError, tarfile.TarError) as error:
        raise SuiteReleaseError(f"could not validate TS Web component archive: {error}") from error



def verify_archive_descriptor(path: Path, descriptor: dict[str, Any], label: str) -> Path:
    file_descriptor, _ = open_verified_file_descriptor(
        path,
        descriptor,
        label,
        max_bytes=MAX_ARCHIVE_TOTAL_BYTES,
    )
    digest = hashlib.sha256()
    with os.fdopen(file_descriptor, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != descriptor["sha256"]:
        raise SuiteReleaseError(f"{label} SHA-256 does not match its descriptor")
    return path


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


def read_verified_file_snapshot(
    path: Path,
    descriptor: dict[str, Any],
    label: str,
    *,
    max_bytes: int = MAX_ARCHIVE_MEMBER_BYTES,
) -> bytes:
    """Read and verify one regular file through a single no-follow descriptor."""
    file_descriptor, size = open_verified_file_descriptor(
        path,
        descriptor,
        label,
        max_bytes=max_bytes,
    )
    with os.fdopen(file_descriptor, "rb") as handle:
        content = handle.read(size + 1)
    if len(content) != size:
        raise SuiteReleaseError(f"{label} changed while it was being read")
    if hashlib.sha256(content).hexdigest() != descriptor["sha256"]:
        raise SuiteReleaseError(f"{label} SHA-256 does not match its descriptor")
    return content


def copy_verified_file_snapshot(
    source: Path,
    destination: Path,
    descriptor: dict[str, Any],
    label: str,
    *,
    max_bytes: int = MAX_ARCHIVE_TOTAL_BYTES,
) -> Path:
    """Copy verified bytes from one stable descriptor into private staging."""
    source_descriptor, size = open_verified_file_descriptor(
        source,
        descriptor,
        label,
        max_bytes=max_bytes,
    )
    digest = hashlib.sha256()
    try:
        with os.fdopen(source_descriptor, "rb") as origin, destination.open("xb") as target:
            remaining = size
            while remaining:
                chunk = origin.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise SuiteReleaseError(f"{label} changed while it was being copied")
                target.write(chunk)
                digest.update(chunk)
                remaining -= len(chunk)
            if origin.read(1):
                raise SuiteReleaseError(f"{label} changed while it was being copied")
            target.flush()
            os.fsync(target.fileno())
        destination.chmod(0o600)
    except Exception:
        if destination.exists() or destination.is_symlink():
            destination.unlink()
        raise
    if digest.hexdigest() != descriptor["sha256"]:
        destination.unlink()
        raise SuiteReleaseError(f"{label} SHA-256 does not match its descriptor")
    return destination


def open_verified_file_descriptor(
    path: Path,
    descriptor: dict[str, Any],
    label: str,
    *,
    max_bytes: int,
) -> tuple[int, int]:
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        file_descriptor = os.open(path, flags)
    except OSError as error:
        raise SuiteReleaseError(f"required file is missing or unsafe: {path}") from error
    try:
        metadata = os.fstat(file_descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise SuiteReleaseError(f"required file is missing or unsafe: {path}")
        if metadata.st_size != descriptor["size_bytes"]:
            raise SuiteReleaseError(f"{label} size does not match its descriptor")
        if metadata.st_size > max_bytes:
            raise SuiteReleaseError(f"{label} exceeds the size limit")
        return file_descriptor, metadata.st_size
    except Exception:
        os.close(file_descriptor)
        raise


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
