"""Manifest-bound deterministic email draft artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from ts_workspace.io import write_json

EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}")
TEMPLATE_ID = "ts-report-summary/1"
DRAFT_REQUEST_KEYS = {
    "schema_version",
    "summary_ref",
    "summary_digest",
    "manifest_ref",
    "manifest_digest",
    "source_workspace_revision",
    "draft_ref",
    "recipients",
}
DRAFT_KEYS = {
    "schema_version",
    "template_id",
    "recipients",
    "subject",
    "body",
    "summary_ref",
    "summary_digest",
    "package_manifest_ref",
    "package_manifest_digest",
    "source_workspace_revision",
    "delivery",
}


def create_draft(root: Path, request_file: Path) -> dict[str, Any]:
    workspace = workspace_root(root)
    request = json.loads(request_file.read_text(encoding="utf-8"))
    if not isinstance(request, dict):
        raise ValueError("email draft request must be an object")
    unknown = sorted(set(request) - DRAFT_REQUEST_KEYS)
    if unknown:
        raise ValueError(f"email draft request contains unknown fields: {', '.join(unknown)}")
    if request.get("schema_version") != "ts-email-draft/1":
        raise ValueError("email draft request schema_version must be ts-email-draft/1")

    summary_ref, summary_path = workspace_path(workspace, request.get("summary_ref"), must_exist=True)
    if not summary_ref.endswith("/email_summary.md"):
        raise ValueError("summary_ref must select a generated email_summary.md")
    context_path = summary_path.with_name("report_context.json")
    if not context_path.is_file():
        raise ValueError("email_summary.md must have a sibling report_context.json")
    manifest_ref, manifest_path = workspace_path(workspace, request.get("manifest_ref"), must_exist=True)
    if manifest_path != summary_path.with_name("package_manifest.json"):
        raise ValueError("manifest_ref must select the summary package manifest")
    manifest_digest = required_digest(request.get("manifest_digest"), "manifest_digest")
    summary_digest = required_digest(request.get("summary_digest"), "summary_digest")
    source_revision = required_digest(request.get("source_workspace_revision"), "source_workspace_revision")
    if sha256_path(manifest_path) != manifest_digest:
        raise ValueError("report package manifest digest changed after request validation")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    verify_manifest_binding(manifest, summary_path, context_path, summary_digest, source_revision)
    draft_ref, draft_path = workspace_path(workspace, request.get("draft_ref"), must_exist=False)
    if draft_path.suffix.lower() != ".json":
        raise ValueError("draft_ref must end in .json")

    fixed_recipients = recipients(request.get("recipients"))
    subject, body = fixed_message(summary_path)
    artifact = {
        "schema_version": "ts-email-draft/1",
        "template_id": TEMPLATE_ID,
        "recipients": fixed_recipients,
        "subject": subject,
        "body": body,
        "summary_ref": summary_ref,
        "summary_digest": summary_digest,
        "package_manifest_ref": manifest_ref,
        "package_manifest_digest": manifest_digest,
        "source_workspace_revision": source_revision,
        "delivery": {
            "status": "not_sent",
            "send_available": True,
            "requires_active_policy": True,
        },
    }
    draft_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(draft_path, artifact)
    os.chmod(draft_path, 0o600)
    return {
        "operation": "draft",
        "state": "drafted",
        "template_id": TEMPLATE_ID,
        "summary_ref": summary_ref,
        "summary_digest": summary_digest,
        "manifest_ref": manifest_ref,
        "manifest_digest": manifest_digest,
        "source_workspace_revision": source_revision,
        "draft_ref": draft_ref,
        "recipients": fixed_recipients,
        "subject": subject,
        "artifact_refs": [draft_ref],
        "external_side_effects": False,
    }


def validate_draft_artifact(workspace: Path, draft: Any) -> None:
    if not isinstance(draft, dict) or draft.get("schema_version") != "ts-email-draft/1":
        raise ValueError("draft artifact must use ts-email-draft/1")
    unknown = sorted(set(draft) - DRAFT_KEYS)
    if unknown:
        raise ValueError(f"draft artifact contains unknown fields: {', '.join(unknown)}")
    if draft.get("template_id") != TEMPLATE_ID:
        raise ValueError(f"draft artifact must use template_id={TEMPLATE_ID}")
    _, summary_path = workspace_path(workspace, draft.get("summary_ref"), must_exist=True)
    manifest_ref, manifest_path = workspace_path(
        workspace,
        draft.get("package_manifest_ref"),
        must_exist=True,
    )
    if manifest_path != summary_path.with_name("package_manifest.json"):
        raise ValueError("draft manifest does not belong to the selected summary package")
    if manifest_ref != draft.get("package_manifest_ref"):
        raise ValueError("draft package manifest ref is not normalized")
    manifest_digest = required_digest(draft.get("package_manifest_digest"), "package_manifest_digest")
    if sha256_path(manifest_path) != manifest_digest:
        raise ValueError("draft package manifest digest no longer matches")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    verify_manifest_binding(
        manifest,
        summary_path,
        summary_path.with_name("report_context.json"),
        required_digest(draft.get("summary_digest"), "summary_digest"),
        required_digest(draft.get("source_workspace_revision"), "source_workspace_revision"),
    )
    subject, body = fixed_message(summary_path)
    if draft.get("subject") != subject or draft.get("body") != body:
        raise ValueError("draft subject/body no longer match the deterministic report summary template")
    recipients(draft.get("recipients"))


def resolve_attachments(
    workspace: Path,
    draft: dict[str, Any],
    names: list[str],
) -> tuple[list[str], list[Path]]:
    summary_ref = str(draft["summary_ref"])
    package_ref = summary_ref.rsplit("/", 1)[0]
    manifest_path = workspace / str(draft["package_manifest_ref"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    records = manifest_records(manifest)
    refs: list[str] = []
    paths: list[Path] = []
    for name in names:
        ref = f"{package_ref}/{name}"
        normalized, path = workspace_path(workspace, ref, must_exist=True)
        if name == "package_manifest.json":
            expected = required_digest(draft.get("package_manifest_digest"), "package_manifest_digest")
        else:
            if name not in records:
                raise ValueError(f"fixed attachment is not bound by the report manifest: {name}")
            expected = records[name]
        if sha256_path(path) != expected:
            raise ValueError(f"fixed attachment digest no longer matches the report manifest: {name}")
        refs.append(normalized)
        paths.append(path)
    return refs, paths


def verify_manifest_binding(
    manifest: Any,
    summary_path: Path,
    context_path: Path,
    expected_summary_digest: str,
    expected_workspace_revision: str,
) -> None:
    if not isinstance(manifest, dict) or manifest.get("schema_version") != "ts-report-package/1":
        raise ValueError("report package manifest must use ts-report-package/1")
    if manifest.get("workspace_revision") != expected_workspace_revision:
        raise ValueError("report package workspace revision does not match the bound request")
    digests = manifest_records(manifest)
    if digests.get(summary_path.name) != expected_summary_digest:
        raise ValueError("report package manifest does not bind the requested summary digest")
    if sha256_path(summary_path) != expected_summary_digest:
        raise ValueError("report email summary digest changed after request validation")
    context_digest = digests.get(context_path.name)
    if not isinstance(context_digest, str) or sha256_path(context_path) != context_digest:
        raise ValueError("report context digest does not match the package manifest")


def manifest_records(manifest: Any) -> dict[str, str]:
    if not isinstance(manifest, dict) or not isinstance(manifest.get("files"), list):
        raise ValueError("report package manifest files must be an array")
    records: dict[str, str] = {}
    for index, record in enumerate(manifest["files"]):
        if not isinstance(record, dict):
            raise ValueError(f"report package manifest files[{index}] must be an object")
        ref = attachment_name(record.get("ref"))
        if ref in records:
            raise ValueError(f"report package manifest contains duplicate ref: {ref}")
        records[ref] = required_digest(record.get("sha256"), f"manifest digest for {ref}")
    return records


def fixed_message(summary_path: Path) -> tuple[str, str]:
    text = summary_path.read_text(encoding="utf-8")
    if len(text) > 20_400:
        raise ValueError("generated email summary exceeds the fixed template limit")
    lines = text.splitlines()
    if not lines or not lines[0].startswith("Subject: "):
        raise ValueError("generated email summary must begin with 'Subject: '")
    subject = bounded_text(lines[0].removeprefix("Subject: "), "subject", 300)
    body = "\n".join(lines[1:]).strip()
    return subject, bounded_text(body, "body", 20_000) + "\n"


def workspace_root(root: Path) -> Path:
    workspace = root.resolve(strict=True)
    if not workspace.is_dir():
        raise ValueError("workspace root must be a directory")
    return workspace


def workspace_path(
    workspace: Path,
    value: Any,
    *,
    must_exist: bool,
    allow_existing: bool = False,
) -> tuple[str, Path]:
    ref = bounded_text(value, "workspace ref", 4096).replace("\\", "/")
    parts = ref.split("/")
    if not ref.startswith("reports/") or any(part in {"", ".", ".."} for part in parts):
        raise ValueError("email artifacts must use a safe reports/ workspace-relative path")
    path = workspace.joinpath(*parts)
    current = workspace
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"email artifact path contains a symbolic link: {ref}")
        if not current.exists():
            break
    if must_exist and not path.is_file():
        raise ValueError(f"email artifact does not exist: {ref}")
    if not must_exist and path.exists() and not allow_existing:
        raise ValueError(f"email artifact already exists: {ref}")
    return ref, path


def attachment_names(value: Any) -> list[str]:
    if not isinstance(value, list) or not 1 <= len(value) <= 16:
        raise ValueError("attachment_names must contain 1-16 fixed package-relative names")
    names = [attachment_name(item) for item in value]
    if len(set(names)) != len(names):
        raise ValueError("attachment_names contains duplicates")
    if "email_summary.md" in names:
        raise ValueError("email_summary.md is the fixed body and cannot also be an attachment")
    return names


def attachment_name(value: Any) -> str:
    name = bounded_text(value, "attachment name", 4096).replace("\\", "/")
    parts = name.split("/")
    if name.startswith("/") or any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"unsafe package-relative attachment name: {name}")
    return name


def recipients(value: Any) -> list[str]:
    if not isinstance(value, list) or not 1 <= len(value) <= 20:
        raise ValueError("recipients must contain 1-20 explicit email addresses")
    result = [bounded_text(item, f"recipients[{index}]", 320) for index, item in enumerate(value)]
    if len(set(result)) != len(result):
        raise ValueError("recipients contains duplicates")
    invalid = [item for item in result if EMAIL_RE.fullmatch(item) is None]
    if invalid:
        raise ValueError(f"invalid explicit email recipient: {invalid[0]}")
    return result


def required_digest(value: Any, label: str) -> str:
    text = bounded_text(value, label, 71)
    if DIGEST_RE.fullmatch(text) is None:
        raise ValueError(f"{label} must be a sha256 digest")
    return text


def bounded_text(value: Any, label: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    text = value.strip()
    if len(text) > maximum:
        raise ValueError(f"{label} exceeds {maximum} characters")
    return text


def bounded_content(value: Any, label: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    if len(value) > maximum:
        raise ValueError(f"{label} exceeds {maximum} characters")
    return value


def sha256_path(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_json(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return sha256_text(payload)
