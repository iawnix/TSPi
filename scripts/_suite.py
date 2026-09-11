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
import subprocess
import tarfile
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable

try:
    from ._wheel import WheelContractError, validate_descriptor
    from .install_release import ReleaseInstallError, load_manifest as _load_agent_manifest
except ImportError:
    from _wheel import WheelContractError, validate_descriptor
    from install_release import ReleaseInstallError, load_manifest as _load_agent_manifest


SUITE_SCHEMA_VERSION = "tspi-package-release/4"
SUITE_COMPONENTS_SCHEMA_VERSION = "tspi-package-components/4"
SUITE_COMPAT_SCHEMA_VERSION = "tspi-package-release/3"
SUITE_COMPAT_COMPONENTS_SCHEMA_VERSION = "tspi-package-components/3"
SUITE_INSTALL_SCHEMA_VERSION = "tspi-package-install/1"
PHONE_SCHEMA_VERSION = "ts-phone-component-release/2"
PHONE_SOURCE_SCHEMA_VERSION = "ts-phone-source-snapshot/1"
PHONE_MOBILE_ATTESTATION_SCHEMA_VERSION = "ts-phone-mobile-build-attestation/1"
WEB_SCHEMA_VERSION = "ts-web-component-release/1"
WEB_COMPONENT_PACKAGE_NAME = "@iawnix/ts-web"
WEB_PROVIDER_PROTOCOL = "ts-web-provider/1"
WEB_PROJECTION_PROTOCOL = "ts-web-workspace/6"
WEB_GRAPH_PROTOCOL = "ts-explorer-graph/6"
WEB_THEME_PROTOCOL = "ts-theme/1"
SUITE_MANIFEST_NAME = "tspi-package-release.json"
SUITE_PACKAGE_NAME = "@iawnix/tspi"
SHA256 = re.compile(r"^[0-9a-f]{64}$")
GIT_OBJECT_ID = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
SEMANTIC_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
RELEASE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")
PHONE_ANDROID_PACKAGE = "xyz.iawnix.ts_phone"
PHONE_ANDROID_ABI = "arm64-v8a"
PHONE_ANDROID_VERSION_CODE_OFFSET = 2000
PHONE_ANDROID_CERTIFICATE_SHA256 = "41998c3f13ee6a2b5e370b3ded25de4dc2af4e0de7172dbcc33e63bfa9fdc19f"
PHONE_APK_SOURCE_MEMBER = "assets/ts-phone-source-snapshot.json"
PHONE_ANDROID_BUILD_TOOLS_ENV = "TSPI_ANDROID_BUILD_TOOLS"
EXPECTED_PHONE_PROTOCOLS = {
    "api": "ts-phone-api/4",
    "events": "ts-phone-events/3",
    "bridge": "ts-phone-bridge/3",
}
EXPECTED_PHONE_PROTOCOL_SCHEMA_IDS = {
    "bridge": "https://tsphone.iawnix.xyz/schema/bridge-v3.json",
    "events": "https://tsphone.iawnix.xyz/schema/events-v3.json",
}
PHONE_LIFECYCLE_EVENT_TYPES = frozenset({"agent_start", "agent_settled"})
PHONE_LIFECYCLE_ORIGINS = frozenset({"local", "extension", "phone", "terminal", "host", "unknown"})
PHONE_LIFECYCLE_FIELDS = frozenset({"type", "origin", "turnId", "agentRunId"})
PHONE_BOUNDED_ID_PATTERN = "^[A-Za-z0-9._:-]{1,160}$"
PHONE_EVENT_ENVELOPE_FIELDS = frozenset(
    {
        "protocolVersion",
        "id",
        "workspaceId",
        "sessionId",
        "sessionRevision",
        "instanceEpoch",
        "sessionGeneration",
        "type",
        "payload",
        "at",
    }
)
PHONE_BRIDGE_ENVELOPE_FIELDS = frozenset(
    {"protocolVersion", "type", "workspaceId", "sessionId", "instanceEpoch"}
)
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
COMPAT_WEB_COMPONENT = {
    "embedded_in": "agent",
    "kernel_protocol": "ts-research-kernel/6",
    "projection_protocol": "ts-web-workspace/6",
    "graph_protocol": "ts-explorer-graph/6",
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
MAX_ARCHIVE_MEMBERS = 100_000
MAX_ARCHIVE_PATH_CHARS = 4096
MAX_COMPONENT_ARCHIVE_BYTES = MAX_ARCHIVE_MEMBER_BYTES
MAX_PHONE_ATTESTATION_BYTES = 16 * 1024
MAX_PHONE_RUNTIME_METADATA_BYTES = 64 * 1024 * 1024


class SuiteReleaseError(RuntimeError):
    """Raised when a suite release violates its immutable component contract."""


def load_agent_manifest(path: Path) -> dict[str, Any]:
    try:
        return _load_agent_manifest(path)
    except (ReleaseInstallError, WheelContractError) as error:
        raise SuiteReleaseError(f"invalid Agent component manifest: {error}") from error


def load_phone_manifest(path: Path) -> dict[str, Any]:
    manifest = validate_phone_manifest(read_json_object(path, "TS Phone component manifest"))
    archive = path.parent / manifest["archive"]["filename"]
    content = read_verified_file_snapshot(
        archive,
        manifest["archive"],
        "Phone component archive",
        max_bytes=MAX_COMPONENT_ARCHIVE_BYTES,
    )
    validate_phone_component_archive(content, manifest)
    return manifest


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
            "mobile_build_attestation",
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
        version = require_string(component.get(key), f"phone component.{key}")
        if not SEMANTIC_VERSION.fullmatch(version):
            raise SuiteReleaseError(f"phone component.{key} must use semantic x.y.z form")
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
    if mobile.get("abi") != PHONE_ANDROID_ABI:
        raise SuiteReleaseError("phone mobile artifact must target arm64-v8a")
    if mobile.get("certificate_sha256") != PHONE_ANDROID_CERTIFICATE_SHA256:
        raise SuiteReleaseError("phone mobile artifact signing certificate is not trusted")
    expected_mobile_path = (
        f"artifacts/ts-phone-v{component['mobile_version']}-build{mobile_build}-"
        f"{PHONE_ANDROID_ABI}-release.apk"
    )
    if mobile["path"] != expected_mobile_path:
        raise SuiteReleaseError("phone mobile artifact path does not match its version, build, and ABI")
    attestation = validate_file_descriptor(
        manifest.get("mobile_build_attestation"),
        "phone mobile_build_attestation",
        key="path",
    )
    if attestation["path"] != f"{mobile['path']}.attestation.json":
        raise SuiteReleaseError("phone mobile build attestation path does not match the mobile artifact")
    if attestation["size_bytes"] > MAX_PHONE_ATTESTATION_BYTES:
        raise SuiteReleaseError("phone mobile build attestation exceeds the size limit")
    archive = validate_file_descriptor(manifest.get("archive"), "phone archive", key="filename")
    source = validate_phone_source_snapshot(manifest.get("source"), "phone source")
    expected_release_id = (
        f"{component['server_version']}-mobile-{component['mobile_version']}-"
        f"build{mobile_build}-source-{canonical_object_sha256(source)[:16]}-"
        f"sha256-{archive['sha256'][:16]}"
    )
    if release_id != expected_release_id:
        raise SuiteReleaseError("phone release_id does not match its versions and archive digest")
    if archive["filename"] != f"ts-phone-component-{release_id}.tgz":
        raise SuiteReleaseError("phone archive filename does not match release_id")
    require_string(manifest.get("created_at_utc"), "phone created_at_utc")
    return manifest


def suite_components(
    agent: dict[str, Any],
    phone: dict[str, Any] | None = None,
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
    if phone is not None:
        phone_archive = phone["archive"]
        components["phone"] = {
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
            "mobile_build_attestation": phone["mobile_build_attestation"],
            "source": phone["source"],
        }
    return components


def suite_components_schema_version(schema_version: str) -> str:
    if schema_version == SUITE_SCHEMA_VERSION:
        return SUITE_COMPONENTS_SCHEMA_VERSION
    if schema_version == SUITE_COMPAT_SCHEMA_VERSION:
        return SUITE_COMPAT_COMPONENTS_SCHEMA_VERSION
    raise SuiteReleaseError("unsupported TSPi Package manifest schema")


def validate_components(
    value: object,
    *,
    schema_version: str = SUITE_COMPONENTS_SCHEMA_VERSION,
) -> dict[str, Any]:
    if schema_version not in (
        SUITE_COMPONENTS_SCHEMA_VERSION,
        SUITE_COMPAT_COMPONENTS_SCHEMA_VERSION,
    ):
        raise SuiteReleaseError("unsupported TSPi Package components schema")
    if (
        not isinstance(value, dict)
        or "agent" not in value
        or not set(value).issubset({"agent", "web", "phone"})
    ):
        raise SuiteReleaseError("suite components must contain Agent and only optional Web or Phone components")
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
        if schema_version == SUITE_COMPAT_COMPONENTS_SCHEMA_VERSION:
            _validate_compat_suite_web_component(components["web"])
        elif schema_version == SUITE_COMPONENTS_SCHEMA_VERSION:
            _validate_suite_web_component(components["web"])
        else:
            raise SuiteReleaseError("unsupported TSPi Package components schema")
    if "phone" in components:
        _validate_suite_phone_component(components["phone"])
    return components


def _validate_compat_suite_web_component(value: object) -> None:
    web = exact_object(value, "historical suite web component", set(COMPAT_WEB_COMPONENT))
    if web != COMPAT_WEB_COMPONENT:
        raise SuiteReleaseError("historical suite Web component contract is incompatible")


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


def _validate_suite_phone_component(value: object) -> None:
    phone = exact_object(
        value,
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
            "mobile_build_attestation",
            "source",
        },
    )
    phone_release_id = require_release_id(phone.get("release_id"), "suite phone release_id")
    for key in ("server_version", "mobile_version"):
        version = require_string(phone.get(key), f"suite phone {key}")
        if not SEMANTIC_VERSION.fullmatch(version):
            raise SuiteReleaseError(f"suite phone {key} must use semantic x.y.z form")
    if (
        not isinstance(phone.get("mobile_build"), int)
        or isinstance(phone["mobile_build"], bool)
        or phone["mobile_build"] <= 0
    ):
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
    validate_file_descriptor(
        {key: mobile[key] for key in ("path", "sha256", "size_bytes")},
        "suite phone mobile artifact",
        key="path",
    )
    if mobile.get("abi") != PHONE_ANDROID_ABI:
        raise SuiteReleaseError("suite phone mobile artifact ABI is incompatible")
    expected_mobile_path = (
        f"artifacts/ts-phone-v{phone['mobile_version']}-build{phone['mobile_build']}-arm64-v8a-release.apk"
    )
    if mobile["path"] != expected_mobile_path:
        raise SuiteReleaseError(f"suite Phone mobile artifact path must be {expected_mobile_path}")
    if mobile.get("certificate_sha256") != PHONE_ANDROID_CERTIFICATE_SHA256:
        raise SuiteReleaseError("suite phone mobile artifact signing certificate is not trusted")
    attestation = validate_file_descriptor(
        phone.get("mobile_build_attestation"),
        "suite phone mobile build attestation",
        key="path",
    )
    if attestation["path"] != f"{mobile['path']}.attestation.json":
        raise SuiteReleaseError("suite phone mobile build attestation path does not match the mobile artifact")
    if attestation["size_bytes"] > MAX_PHONE_ATTESTATION_BYTES:
        raise SuiteReleaseError("suite phone mobile build attestation exceeds the size limit")
    source = validate_phone_source_snapshot(phone.get("source"), "suite phone source")
    expected_phone_release = (
        f"{phone['server_version']}-mobile-{phone['mobile_version']}-"
        f"build{phone['mobile_build']}-source-{canonical_object_sha256(source)[:16]}-"
        f"sha256-{phone_archive['sha256'][:16]}"
    )
    if phone_release_id != expected_phone_release:
        raise SuiteReleaseError("suite phone release_id does not match its source and archive")


def validate_suite_manifest(value: object) -> dict[str, Any]:
    manifest = exact_object(
        value,
        "TSPi Package manifest",
        {"schema_version", "release_id", "package", "components", "archive", "created_at_utc"},
    )
    schema_version = manifest.get("schema_version")
    if schema_version not in (SUITE_SCHEMA_VERSION, SUITE_COMPAT_SCHEMA_VERSION):
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
    phone_archive: Path | None = None,
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
    if "phone" in components:
        if phone_archive is None:
            raise SuiteReleaseError("Phone component archive is required when Phone is selected")
        records.append(
            (
                PurePosixPath(components["phone"]["archive"]["path"]),
                read_verified_file_snapshot(
                    phone_archive,
                    components["phone"]["archive"],
                    "Phone component archive",
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


def validate_extracted_phone_matches_archive(
    root: Path,
    archive_path: Path,
    members: list[tuple[tarfile.TarInfo, PurePosixPath]],
) -> None:
    if root.is_symlink() or not root.is_dir():
        raise SuiteReleaseError(f"installed Phone runtime is not a regular directory: {root}")
    expected = {
        relative.as_posix(): member
        for member, relative in members
        if member.isreg()
    }
    actual: dict[str, Path] = {}
    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise SuiteReleaseError(f"installed Phone runtime contains a symbolic link: {relative}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise SuiteReleaseError(f"installed Phone runtime contains a non-file entry: {relative}")
        actual[relative] = path
    if set(actual) != set(expected):
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        detail = []
        if missing:
            detail.append(f"missing: {', '.join(missing)}")
        if extra:
            detail.append(f"extra: {', '.join(extra)}")
        raise SuiteReleaseError(f"installed Phone runtime inventory differs from its archive ({'; '.join(detail)})")

    try:
        with tarfile.open(archive_path, "r:gz") as archive:
            archived = {member.name: member for member in archive.getmembers() if member.isreg()}
            for name, inspected_member in expected.items():
                member_name = (PurePosixPath("component") / PurePosixPath(name)).as_posix()
                member = archived.get(member_name)
                if member is None or member.size != inspected_member.size:
                    raise SuiteReleaseError(f"installed Phone runtime archive member changed: {name}")
                path = actual[name]
                if path.stat().st_size != member.size:
                    raise SuiteReleaseError(f"installed Phone runtime file size differs from its archive: {name}")
                expected_executable = bool(member.mode & 0o111)
                actual_mode = stat.S_IMODE(path.stat().st_mode)
                valid_modes = {0o700, 0o500} if expected_executable else {0o600, 0o400}
                if actual_mode not in valid_modes:
                    raise SuiteReleaseError(f"installed Phone runtime mode differs from its archive: {name}")
                extracted = archive.extractfile(member)
                if extracted is None:
                    raise SuiteReleaseError(f"installed Phone runtime archive member cannot be read: {name}")
                digest = hashlib.sha256()
                with extracted:
                    for chunk in iter(lambda: extracted.read(1024 * 1024), b""):
                        digest.update(chunk)
                if digest.hexdigest() != sha256_file(path):
                    raise SuiteReleaseError(f"installed Phone runtime content differs from its archive: {name}")
    except (OSError, tarfile.TarError) as error:
        raise SuiteReleaseError(f"could not compare installed Phone runtime with its archive: {error}") from error


def validate_phone_runtime(root: Path, descriptor: dict[str, Any]) -> None:
    for relative in PHONE_REQUIRED_FILES:
        require_regular_file(root / relative)

    def read_member(name: str, label: str) -> bytes:
        path = require_regular_file(root.joinpath(*safe_relative(name).parts))
        if path.stat().st_size > MAX_PHONE_RUNTIME_METADATA_BYTES:
            raise SuiteReleaseError(f"installed {label} exceeds the size limit")
        return path.read_bytes()

    def is_executable(name: str) -> bool:
        return bool(require_regular_file(root.joinpath(*safe_relative(name).parts)).stat().st_mode & 0o111)

    validate_phone_runtime_metadata(read_member, is_executable, descriptor)
    validate_runtime_file(root, descriptor["server_entry"], "phone server entry")
    mobile_content = read_runtime_file(root, descriptor["mobile_artifact"], "phone mobile artifact")
    attestation_content = read_runtime_file(
        root,
        descriptor["mobile_build_attestation"],
        "phone mobile build attestation",
    )
    validate_phone_mobile_payload(
        attestation_content,
        mobile_content,
        source=descriptor["source"],
        mobile_version=descriptor["mobile_version"],
        mobile_build=descriptor["mobile_build"],
        mobile=descriptor["mobile_artifact"],
    )


def validate_phone_runtime_metadata(
    read_member: Callable[[str, str], bytes],
    is_executable: Callable[[str], bool],
    descriptor: dict[str, Any],
) -> None:
    package = decode_json_object(read_member("package.json", "TS Phone package"), "TS Phone package")
    if package.get("name") != "ts-phone":
        raise SuiteReleaseError("installed TS Phone package name is invalid")
    if package.get("version") != descriptor["server_version"]:
        raise SuiteReleaseError("installed TS Phone package version does not match the suite manifest")
    server_package = decode_json_object(
        read_member("services/server/package.json", "TS Phone server package"),
        "TS Phone server package",
    )
    if server_package.get("name") != "@iawnix/ts-phone-server":
        raise SuiteReleaseError("installed TS Phone server package name is invalid")
    if server_package.get("version") != descriptor["server_version"]:
        raise SuiteReleaseError("installed TS Phone server package version does not match the suite manifest")
    try:
        version = read_member("VERSION", "TS Phone VERSION").decode("utf-8").strip()
    except UnicodeDecodeError as error:
        raise SuiteReleaseError("installed TS Phone VERSION is not UTF-8") from error
    if version != descriptor["server_version"]:
        raise SuiteReleaseError("installed TS Phone VERSION does not match the suite manifest")
    protocol_set = decode_json_object(
        read_member("packages/protocol/versions.json", "phone protocols"),
        "phone protocols",
    )
    expected_protocols = {"schema_version": "ts-phone-protocol-set/1", **descriptor["protocols"]}
    if protocol_set != expected_protocols:
        raise SuiteReleaseError("installed TS Phone protocols do not match the suite manifest")
    validate_phone_protocol_documents(
        read_member("packages/protocol/bridge.schema.json", "phone bridge schema"),
        read_member("packages/protocol/events.schema.json", "phone events schema"),
        read_member("packages/protocol/openapi.yaml", "phone OpenAPI document"),
        server_version=descriptor["server_version"],
        protocols=descriptor["protocols"],
    )
    for executable in ("bin/ts-phone-ctl", "bin/ts-phone-server"):
        if not is_executable(executable):
            raise SuiteReleaseError(f"installed TS Phone entrypoint is not executable: {executable}")


def validate_phone_protocol_documents(
    bridge_content: bytes,
    events_content: bytes,
    openapi_content: bytes,
    *,
    server_version: str,
    protocols: dict[str, str],
) -> None:
    documents = {
        "bridge": decode_json_object(bridge_content, "phone bridge schema"),
        "events": decode_json_object(events_content, "phone events schema"),
    }
    for key, document in documents.items():
        if document.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
            raise SuiteReleaseError(f"installed phone {key} schema must use JSON Schema Draft 2020-12")
        if document.get("$id") != EXPECTED_PHONE_PROTOCOL_SCHEMA_IDS[key]:
            raise SuiteReleaseError(f"installed phone {key} schema ID does not match its version")
        properties = document.get("properties")
        protocol_version = properties.get("protocolVersion") if isinstance(properties, dict) else None
        if not isinstance(protocol_version, dict) or protocol_version.get("const") != protocols[key]:
            raise SuiteReleaseError(f"installed phone {key} schema does not bind its declared version")

    validate_phone_events_schema(documents["events"])
    validate_phone_bridge_schema(documents["bridge"])

    try:
        openapi = openapi_content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise SuiteReleaseError("installed phone OpenAPI document is not UTF-8") from error
    lines = openapi.splitlines()
    if sum(line.strip() == "openapi: 3.1.0" for line in lines) != 1:
        raise SuiteReleaseError("installed phone OpenAPI document must declare OpenAPI 3.1.0 exactly once")
    info_versions = openapi_info_versions(lines)
    if info_versions != [server_version]:
        raise SuiteReleaseError("installed phone OpenAPI info.version does not match the server")
    if sum(re.fullmatch(r"  /api/v4/version:\s*", line) is not None for line in lines) != 1:
        raise SuiteReleaseError("installed phone OpenAPI document does not define the version endpoint")
    api_constants = [
        match.group(1)
        for line in lines
        if (match := re.fullmatch(r"\s*version:\s*\{\s*const:\s*([^}\s]+)\s*}\s*", line)) is not None
    ]
    if api_constants != [protocols["api"]]:
        raise SuiteReleaseError("installed phone OpenAPI document does not bind the declared API version")


def validate_phone_events_schema(document: dict[str, Any]) -> None:
    validate_phone_object_schema(
        document,
        "installed phone events schema",
        required=PHONE_EVENT_ENVELOPE_FIELDS,
        additional_properties=False,
    )
    validate_phone_lifecycle_definition(document, "events")
    validate_phone_lifecycle_bindings(document, "events", bridge=False)


def validate_phone_bridge_schema(document: dict[str, Any]) -> None:
    validate_phone_object_schema(
        document,
        "installed phone bridge schema",
        required=PHONE_BRIDGE_ENVELOPE_FIELDS,
        additional_properties=True,
    )
    validate_phone_lifecycle_definition(document, "bridge")
    validate_phone_lifecycle_bindings(document, "bridge", bridge=True)

    abort_branch = find_phone_conditional_branch(document, type_const="command.abort")
    if abort_branch is None or "agentRunId" not in phone_schema_required(abort_branch.get("then")):
        raise SuiteReleaseError("installed phone bridge schema does not bind abort to an agent run")

    definitions = document.get("$defs")
    snapshot = definitions.get("sessionSnapshot") if isinstance(definitions, dict) else None
    if not isinstance(snapshot, dict):
        raise SuiteReleaseError("installed phone bridge schema is missing the session snapshot")
    validate_phone_object_schema(
        snapshot,
        "installed phone bridge session snapshot",
        required=frozenset({"sessionId", "isStreaming", "messages"}),
        additional_properties=False,
    )
    snapshot_properties = snapshot.get("properties")
    if not isinstance(snapshot_properties, dict) or snapshot_properties.get("agentRunId") != {
        "type": "string",
        "pattern": PHONE_BOUNDED_ID_PATTERN,
    }:
        raise SuiteReleaseError("installed phone bridge snapshot does not define a bounded agentRunId")
    streaming_branch = find_phone_conditional_branch(
        snapshot,
        property_name="isStreaming",
        property_const=True,
    )
    if streaming_branch is None:
        raise SuiteReleaseError("installed phone bridge snapshot does not bind streaming state to an agent run")
    if "agentRunId" not in phone_schema_required(streaming_branch.get("then")):
        raise SuiteReleaseError("installed phone bridge snapshot does not require agentRunId while streaming")
    otherwise = streaming_branch.get("else")
    if not isinstance(otherwise, dict) or otherwise.get("not") != {"required": ["agentRunId"]}:
        raise SuiteReleaseError("installed phone bridge snapshot permits agentRunId while idle")


def validate_phone_object_schema(
    schema: object,
    label: str,
    *,
    required: frozenset[str],
    additional_properties: bool,
) -> None:
    if not isinstance(schema, dict) or schema.get("type") != "object":
        raise SuiteReleaseError(f"{label} must define an object")
    if phone_schema_required(schema) != required:
        raise SuiteReleaseError(f"{label} does not require its exact envelope fields")
    if schema.get("additionalProperties") is not additional_properties:
        raise SuiteReleaseError(f"{label} has an invalid unknown-field policy")
    properties = schema.get("properties")
    if not isinstance(properties, dict) or not required.issubset(properties):
        raise SuiteReleaseError(f"{label} is missing required property definitions")


def validate_phone_lifecycle_definition(document: dict[str, Any], label: str) -> None:
    definitions = document.get("$defs")
    lifecycle = definitions.get("agentRunEvent") if isinstance(definitions, dict) else None
    if not isinstance(lifecycle, dict) or lifecycle.get("type") != "object":
        raise SuiteReleaseError(f"installed phone {label} schema is missing the lifecycle payload definition")
    if phone_schema_required(lifecycle) != PHONE_LIFECYCLE_FIELDS:
        raise SuiteReleaseError(f"installed phone {label} schema does not bind lifecycle event identity")
    properties = lifecycle.get("properties")
    if not isinstance(properties, dict) or not PHONE_LIFECYCLE_FIELDS <= set(properties) <= PHONE_LIFECYCLE_FIELDS | {"attempt", "outcome"}:
        raise SuiteReleaseError(f"installed phone {label} schema has invalid lifecycle event fields")
    if "attempt" in properties and properties["attempt"] != {"type": "integer", "minimum": 1}:
        raise SuiteReleaseError(f"installed phone {label} lifecycle payload has invalid attempt metadata")
    if "outcome" in properties and properties["outcome"] != {
        "type": "object", "required": ["status"], "additionalProperties": False,
        "properties": {
            "status": {"enum": ["completed", "failed", "cancelled"]},
            "problem": {"enum": ["provider_unavailable", "provider_rate_limited", "provider_auth_failed", "provider_error", "generation_incomplete"]},
            "httpStatus": {"type": "integer", "minimum": 400, "maximum": 599},
        },
    }:
        raise SuiteReleaseError(f"installed phone {label} lifecycle payload has invalid outcome metadata")
    if lifecycle.get("additionalProperties") is not False:
        raise SuiteReleaseError(f"installed phone {label} lifecycle payload must reject unknown fields")
    type_schema = properties.get("type")
    origin_schema = properties.get("origin")
    if (
        not isinstance(type_schema, dict)
        or phone_string_set(type_schema.get("enum")) != PHONE_LIFECYCLE_EVENT_TYPES
    ):
        raise SuiteReleaseError(f"installed phone {label} lifecycle payload has invalid event types")
    if (
        not isinstance(origin_schema, dict)
        or phone_string_set(origin_schema.get("enum")) != PHONE_LIFECYCLE_ORIGINS
    ):
        raise SuiteReleaseError(f"installed phone {label} lifecycle payload has invalid origins")
    bounded_id = {"type": "string", "pattern": PHONE_BOUNDED_ID_PATTERN}
    if properties["turnId"] != bounded_id or properties["agentRunId"] != bounded_id:
        raise SuiteReleaseError(f"installed phone {label} lifecycle payload has invalid bounded identifiers")


def validate_phone_lifecycle_bindings(
    document: dict[str, Any],
    label: str,
    *,
    bridge: bool,
) -> None:
    for event_type in PHONE_LIFECYCLE_EVENT_TYPES:
        branch = find_phone_conditional_branch(
            document,
            type_const="event.publish" if bridge else event_type,
            property_name="eventType" if bridge else None,
            property_const=event_type if bridge else None,
        )
        if branch is None:
            raise SuiteReleaseError(f"installed phone {label} schema does not bind {event_type}")
        condition_required = phone_schema_required(branch.get("if"))
        expected_condition = {"type", "eventType"} if bridge else {"type"}
        if not expected_condition.issubset(condition_required):
            raise SuiteReleaseError(f"installed phone {label} schema has an incomplete {event_type} condition")
        then = branch.get("then")
        if not isinstance(then, dict):
            raise SuiteReleaseError(f"installed phone {label} schema has an invalid {event_type} branch")
        if bridge and "payload" not in phone_schema_required(then):
            raise SuiteReleaseError(f"installed phone {label} schema does not require {event_type} payload")
        then_properties = then.get("properties")
        payload = then_properties.get("payload") if isinstance(then_properties, dict) else None
        all_of = payload.get("allOf") if isinstance(payload, dict) else None
        if not isinstance(all_of, list):
            raise SuiteReleaseError(f"installed phone {label} schema has an invalid {event_type} payload")
        references = [item.get("$ref") for item in all_of if isinstance(item, dict) and "$ref" in item]
        inner_types = [
            inner_type
            for item in all_of
            if (inner_type := phone_schema_inner_type(item)) is not None
        ]
        if references != ["#/$defs/agentRunEvent"] or inner_types != [event_type]:
            raise SuiteReleaseError(f"installed phone {label} schema misbinds {event_type} payload")


def find_phone_conditional_branch(
    document: dict[str, Any],
    *,
    type_const: object | None = None,
    property_name: str | None = None,
    property_const: object | None = None,
) -> dict[str, Any] | None:
    branches = document.get("allOf")
    if not isinstance(branches, list):
        return None
    matches: list[dict[str, Any]] = []
    for branch in branches:
        if not isinstance(branch, dict):
            continue
        condition = branch.get("if")
        properties = condition.get("properties") if isinstance(condition, dict) else None
        if not isinstance(properties, dict):
            continue
        if type_const is not None:
            type_schema = properties.get("type")
            if not isinstance(type_schema, dict) or type_schema.get("const") != type_const:
                continue
        if property_name is not None:
            property_schema = properties.get(property_name)
            if not isinstance(property_schema, dict) or property_schema.get("const") != property_const:
                continue
        matches.append(branch)
    if len(matches) > 1:
        raise SuiteReleaseError("installed phone protocol schema contains duplicate conditional bindings")
    return matches[0] if matches else None


def phone_schema_required(schema: object) -> frozenset[str]:
    if not isinstance(schema, dict):
        return frozenset()
    required = schema.get("required")
    if (
        not isinstance(required, list)
        or any(not isinstance(value, str) for value in required)
        or len(required) != len(set(required))
    ):
        return frozenset()
    return frozenset(required)


def phone_string_set(value: object) -> frozenset[str]:
    if (
        not isinstance(value, list)
        or any(not isinstance(item, str) for item in value)
        or len(value) != len(set(value))
    ):
        return frozenset()
    return frozenset(value)


def phone_schema_inner_type(schema: object) -> object | None:
    if not isinstance(schema, dict):
        return None
    properties = schema.get("properties")
    type_schema = properties.get("type") if isinstance(properties, dict) else None
    return type_schema.get("const") if isinstance(type_schema, dict) else None


def openapi_info_versions(lines: list[str]) -> list[str]:
    in_info = False
    versions: list[str] = []
    for line in lines:
        if line and not line[0].isspace():
            if in_info:
                break
            in_info = line.strip() == "info:"
            continue
        if in_info:
            match = re.fullmatch(r"  version:\s*([0-9]+\.[0-9]+\.[0-9]+)\s*", line)
            if match is not None:
                versions.append(match.group(1))
    return versions


def decode_json_object(content: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SuiteReleaseError(f"installed {label} is not valid UTF-8 JSON") from error
    if not isinstance(value, dict):
        raise SuiteReleaseError(f"installed {label} must contain an object")
    return value


def validate_phone_archive_files(files: set[str], descriptor: dict[str, Any]) -> None:
    required = {
        *PHONE_REQUIRED_FILES,
        descriptor["mobile_artifact"]["path"],
        descriptor["mobile_build_attestation"]["path"],
    }
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


def validate_runtime_file(root: Path, descriptor: dict[str, Any], label: str) -> None:
    read_runtime_file(root, descriptor, label)


def read_runtime_file(root: Path, descriptor: dict[str, Any], label: str) -> bytes:
    relative = safe_relative(str(descriptor["path"]))
    path = require_regular_file(root.joinpath(*relative.parts))
    return read_verified_file_snapshot(path, descriptor, f"installed {label}")


def validate_phone_component_archive(content: bytes, manifest: dict[str, Any]) -> None:
    """Validate bound Phone members from the exact archive bytes being consumed."""
    try:
        with tarfile.open(fileobj=io.BytesIO(content), mode="r:gz") as archive:
            inspected, files = inspect_rooted_archive_members(archive, "component")
            validate_phone_archive_files(files, manifest)
            members_by_name = {relative.as_posix(): member for member, relative in inspected if member.isreg()}

            def read_member(name: str, label: str) -> bytes:
                member = members_by_name.get(safe_relative(name).as_posix())
                if member is None:
                    raise SuiteReleaseError(f"Phone component archive is missing {label}")
                return read_archive_member(archive, member, label, max_bytes=MAX_PHONE_RUNTIME_METADATA_BYTES)

            def is_executable(name: str) -> bool:
                member = members_by_name.get(safe_relative(name).as_posix())
                return member is not None and bool(member.mode & 0o111)

            component = manifest["component"]
            runtime_descriptor = {
                "server_version": component["server_version"],
                "mobile_version": component["mobile_version"],
                "mobile_build": component["mobile_build"],
                "protocols": manifest["protocols"],
                "source": manifest["source"],
                "server_entry": manifest["server_entry"],
                "mobile_artifact": manifest["mobile_artifact"],
                "mobile_build_attestation": manifest["mobile_build_attestation"],
            }
            validate_phone_runtime_metadata(read_member, is_executable, runtime_descriptor)
            server_content = read_bound_archive_member(archive, manifest["server_entry"], "phone server entry")
            mobile_content = read_bound_archive_member(archive, manifest["mobile_artifact"], "phone mobile artifact")
            attestation_content = read_bound_archive_member(
                archive,
                manifest["mobile_build_attestation"],
                "phone mobile build attestation",
                max_bytes=MAX_PHONE_ATTESTATION_BYTES,
            )
    except (OSError, tarfile.TarError) as error:
        raise SuiteReleaseError(f"could not validate Phone component archive: {error}") from error
    if not server_content:
        raise SuiteReleaseError("Phone component server entry is empty")
    validate_phone_mobile_payload(
        attestation_content,
        mobile_content,
        source=manifest["source"],
        mobile_version=component["mobile_version"],
        mobile_build=component["mobile_build"],
        mobile=manifest["mobile_artifact"],
    )


def read_archive_member(
    archive: tarfile.TarFile,
    member: tarfile.TarInfo,
    label: str,
    *,
    max_bytes: int,
) -> bytes:
    if not member.isreg() or member.size < 0 or member.size > max_bytes:
        raise SuiteReleaseError(f"Phone component archive {label} exceeds the size limit or is not regular")
    extracted = archive.extractfile(member)
    if extracted is None:
        raise SuiteReleaseError(f"Phone component archive {label} cannot be read")
    with extracted:
        content = extracted.read(member.size + 1)
    if len(content) != member.size:
        raise SuiteReleaseError(f"Phone component archive {label} size is invalid")
    return content


def read_bound_archive_member(
    archive: tarfile.TarFile,
    descriptor: dict[str, Any],
    label: str,
    *,
    max_bytes: int = MAX_ARCHIVE_MEMBER_BYTES,
) -> bytes:
    member_name = (PurePosixPath("component") / safe_relative(str(descriptor["path"]))).as_posix()
    matches = [member for member in archive.getmembers() if member.name == member_name]
    if len(matches) != 1 or not matches[0].isreg():
        raise SuiteReleaseError(f"Phone component archive must contain exactly one regular {label}")
    member = matches[0]
    if member.size > max_bytes:
        raise SuiteReleaseError(f"Phone component archive {label} exceeds the size limit")
    if member.size != descriptor["size_bytes"]:
        raise SuiteReleaseError(f"Phone component archive {label} size does not match its descriptor")
    extracted = archive.extractfile(member)
    if extracted is None:
        raise SuiteReleaseError(f"Phone component archive {label} cannot be read")
    with extracted:
        content = extracted.read(member.size + 1)
    if len(content) != member.size or hashlib.sha256(content).hexdigest() != descriptor["sha256"]:
        raise SuiteReleaseError(f"Phone component archive {label} digest or size does not match its descriptor")
    return content


def validate_phone_mobile_payload(
    attestation_content: bytes,
    mobile_content: bytes,
    *,
    source: object,
    mobile_version: str,
    mobile_build: int,
    mobile: dict[str, Any],
) -> None:
    expected_source = validate_phone_source_snapshot(source, "phone source")
    try:
        attestation_value = json.loads(attestation_content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SuiteReleaseError("phone mobile build attestation is not valid UTF-8 JSON") from error
    attestation = exact_object(
        attestation_value,
        "phone mobile build attestation",
        {"schema_version", "source", "mobile", "target", "artifact"},
    )
    if attestation.get("schema_version") != PHONE_MOBILE_ATTESTATION_SCHEMA_VERSION:
        raise SuiteReleaseError("phone mobile build attestation schema is unsupported")
    if validate_phone_source_snapshot(attestation.get("source"), "phone attestation source") != expected_source:
        raise SuiteReleaseError("phone mobile build attestation does not match the component source")
    attested_mobile = exact_object(attestation.get("mobile"), "phone attested mobile", {"version", "build"})
    if attested_mobile != {"version": mobile_version, "build": mobile_build}:
        raise SuiteReleaseError("phone mobile build attestation version does not match the component")
    target = exact_object(attestation.get("target"), "phone attested target", {"format", "abi"})
    if target != {"format": "apk", "abi": PHONE_ANDROID_ABI} or mobile.get("abi") != PHONE_ANDROID_ABI:
        raise SuiteReleaseError("phone mobile build attestation target does not match the component")
    artifact = validate_file_descriptor(attestation.get("artifact"), "phone attested artifact", key="filename")
    expected_name = PurePosixPath(mobile["path"]).name
    if artifact["filename"] != expected_name:
        raise SuiteReleaseError("phone mobile build attestation names a different APK")
    if artifact["size_bytes"] != len(mobile_content) or artifact["sha256"] != hashlib.sha256(mobile_content).hexdigest():
        raise SuiteReleaseError("phone mobile build attestation APK digest or size does not match")
    embedded_source = read_phone_apk_source_snapshot(mobile_content)
    if embedded_source != expected_source:
        raise SuiteReleaseError("phone APK embedded source snapshot does not match the component")
    verify_phone_apk(mobile_content, expected_name, mobile_version, mobile_build)


def read_phone_apk_source_snapshot(content: bytes) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            matches = [entry for entry in archive.infolist() if entry.filename == PHONE_APK_SOURCE_MEMBER]
            if len(matches) != 1 or matches[0].is_dir():
                raise SuiteReleaseError("phone APK must contain exactly one source snapshot")
            if matches[0].file_size > MAX_PHONE_ATTESTATION_BYTES:
                raise SuiteReleaseError("phone APK source snapshot exceeds the size limit")
            with archive.open(matches[0]) as handle:
                encoded = handle.read(MAX_PHONE_ATTESTATION_BYTES + 1)
    except (OSError, RuntimeError, zipfile.BadZipFile, zipfile.LargeZipFile) as error:
        raise SuiteReleaseError(f"could not read phone APK source snapshot: {error}") from error
    if len(encoded) > MAX_PHONE_ATTESTATION_BYTES:
        raise SuiteReleaseError("phone APK source snapshot exceeds the size limit")
    try:
        value = json.loads(encoded.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SuiteReleaseError("phone APK source snapshot is not valid UTF-8 JSON") from error
    return validate_phone_source_snapshot(value, "phone APK source snapshot")


def verify_phone_apk(content: bytes, filename: str, mobile_version: str, mobile_build: int) -> None:
    apksigner, aapt = configured_android_build_tools()
    with tempfile.TemporaryDirectory(prefix="tspi-phone-apk-") as temporary:
        apk = Path(temporary) / filename
        with apk.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        apk.chmod(0o600)
        signature = run_android_tool(
            [str(apksigner), "verify", "--verbose", "--print-certs", str(apk)],
            "APK signature verification",
        )
        expected_signature = "Verified using v2 scheme (APK Signature Scheme v2): true"
        if expected_signature not in signature:
            raise SuiteReleaseError("phone APK does not carry the required signature scheme")
        certificates = [
            digest.lower()
            for digest in re.findall(
                r"(?m)^Signer #[0-9]+ certificate SHA-256 digest:\s*([0-9a-fA-F]{64})\s*$",
                signature,
            )
        ]
        if certificates != [PHONE_ANDROID_CERTIFICATE_SHA256]:
            raise SuiteReleaseError("phone APK signer does not match the pinned release certificate")
        badging = run_android_tool(
            [str(aapt), "dump", "badging", str(apk)],
            "APK metadata verification",
        )
    validate_phone_apk_badging(badging, mobile_version, mobile_build)


def validate_phone_apk_badging(value: str, mobile_version: str, mobile_build: int) -> None:
    package = re.search(
        r"(?m)^package: name='([^']+)' versionCode='([0-9]+)' versionName='([^']+)'",
        value,
    )
    if package is None:
        raise SuiteReleaseError("phone APK package metadata is unavailable")
    expected_version_code = PHONE_ANDROID_VERSION_CODE_OFFSET + mobile_build
    if package.groups() != (PHONE_ANDROID_PACKAGE, str(expected_version_code), mobile_version):
        raise SuiteReleaseError("phone APK package name, version name, or version code is invalid")
    native_code = re.search(r"(?m)^native-code:\s*(.+)$", value)
    native_abis = re.findall(r"'([^']+)'", native_code.group(1)) if native_code is not None else []
    if native_abis != [PHONE_ANDROID_ABI]:
        raise SuiteReleaseError("phone APK native ABI does not match the release target")
    if re.search(r"(?m)^application-debuggable(?:\s|$)", value):
        raise SuiteReleaseError("phone APK must not be debuggable")


def configured_android_build_tools() -> tuple[Path, Path]:
    configured = os.environ.get(PHONE_ANDROID_BUILD_TOOLS_ENV)
    if configured:
        return android_tools_in_directory(Path(configured), f"${PHONE_ANDROID_BUILD_TOOLS_ENV}")
    candidates: list[Path] = []
    for variable in ("ANDROID_SDK_ROOT", "ANDROID_HOME"):
        value = os.environ.get(variable)
        if value:
            build_tools = Path(value) / "build-tools"
            if build_tools.is_dir():
                candidates.extend(path for path in build_tools.iterdir() if path.is_dir())
    candidates.sort(key=android_build_tools_version_key, reverse=True)
    for candidate in candidates:
        try:
            return android_tools_in_directory(candidate, "Android SDK build-tools")
        except SuiteReleaseError:
            continue
    apksigner = shutil.which("apksigner")
    aapt = shutil.which("aapt")
    if apksigner and aapt:
        return require_executable(Path(apksigner), "apksigner"), require_executable(Path(aapt), "aapt")
    raise SuiteReleaseError(
        f"Android APK verification tools are not configured; set {PHONE_ANDROID_BUILD_TOOLS_ENV} "
        "to a build-tools directory containing apksigner and aapt"
    )


def android_tools_in_directory(directory: Path, label: str) -> tuple[Path, Path]:
    if not directory.is_dir():
        raise SuiteReleaseError(f"{label} is not a directory: {directory}")
    return (
        require_executable(directory / "apksigner", "apksigner"),
        require_executable(directory / "aapt", "aapt"),
    )


def android_build_tools_version_key(path: Path) -> tuple[tuple[int, int | str], ...]:
    """Sort dotted Android build-tools versions numerically where possible."""
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part)
        for part in re.split(r"[._-]", path.name)
    )


def require_executable(path: Path, label: str) -> Path:
    try:
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise SuiteReleaseError(f"configured {label} is unavailable: {path}") from error
    if not resolved.is_file() or not os.access(resolved, os.X_OK):
        raise SuiteReleaseError(f"configured {label} is not executable: {path}")
    return resolved


def run_android_tool(command: list[str], label: str) -> str:
    try:
        completed = subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise SuiteReleaseError(f"{label} could not run: {error}") from error
    if completed.returncode != 0:
        raise SuiteReleaseError(completed.stderr.strip() or f"{label} failed")
    return completed.stdout


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


def validate_phone_source_snapshot(value: object, label: str) -> dict[str, Any]:
    source = exact_object(value, label, {"schema_version", "git_commit", "dirty", "sha256"})
    if source.get("schema_version") != PHONE_SOURCE_SCHEMA_VERSION:
        raise SuiteReleaseError(f"{label}.schema_version is unsupported")
    commit = require_string(source.get("git_commit"), f"{label}.git_commit")
    if not GIT_OBJECT_ID.fullmatch(commit):
        raise SuiteReleaseError(f"{label}.git_commit must be a full Git object ID")
    if not isinstance(source.get("dirty"), bool):
        raise SuiteReleaseError(f"{label}.dirty must be boolean")
    require_sha256(source.get("sha256"), f"{label}.sha256")
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


def canonical_object_sha256(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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
