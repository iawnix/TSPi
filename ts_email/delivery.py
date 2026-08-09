"""Private fixed-scope policy and idempotent ClawEmail delivery."""

from __future__ import annotations

import hmac
import json
import os
import secrets
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .artifacts import (
    TEMPLATE_ID,
    attachment_names as validate_attachment_names,
    bounded_content,
    bounded_text,
    recipients as validate_recipients,
    required_digest,
    resolve_attachments,
    sha256_json,
    sha256_path,
    sha256_text,
    validate_draft_artifact,
    workspace_path,
    workspace_root,
)

POLICY_SCHEMA = "ts-email-delivery-policy/1"
AUTHORIZATION_SCHEMA = "ts-email-delivery-authorization/1"
RECEIPT_SCHEMA = "ts-email-delivery-receipt/1"
POLICY_NAME = "ts-email-delivery-policy.json"
AUTHORIZATION_NAME = "ts-email-delivery-authorization.json"
POLICY_REF = f".pi/{POLICY_NAME}"
AUTHORIZATION_REF = f".pi/{AUTHORIZATION_NAME}"
DELIVERY_DIR_REF = "reports/email/deliveries"
DEFAULT_CLAWEMAIL_ROOT = Path.home() / ".pi" / "agent" / "skills" / "clawemail"


def create_delivery_policy(
    root: Path,
    *,
    recipients: list[str],
    attachment_names: list[str],
    clawemail_root: Path,
) -> dict[str, Any]:
    workspace = workspace_root(root)
    policy_path = _private_state_path(workspace, POLICY_NAME)
    authorization_path = _private_state_path(workspace, AUTHORIZATION_NAME)
    _refuse_existing_private_state(policy_path, authorization_path)
    fixed_recipients = validate_recipients(recipients)
    fixed_attachments = validate_attachment_names(attachment_names)
    skill_root = clawemail_root.expanduser().resolve(strict=True)
    _validate_clawemail_install(skill_root)
    token = f"APPROVE-TS-EMAIL-{secrets.token_hex(8).upper()}"
    policy = {
        "schema_version": POLICY_SCHEMA,
        "policy_id": f"email_policy_{secrets.token_hex(12)}",
        "created_at": _now(),
        "transport": {
            "kind": "clawemail",
            "skill_root": str(skill_root),
        },
        "recipients": fixed_recipients,
        "template_id": TEMPLATE_ID,
        "attachment_names": fixed_attachments,
        "activation_token_digest": sha256_text(token),
    }
    _write_private_json(policy_path, policy, exclusive=True)
    return {
        "operation": "policy_create",
        "state": "pending_activation",
        "policy_ref": POLICY_REF,
        "authorization_ref": AUTHORIZATION_REF,
        "policy_id": policy["policy_id"],
        "policy_digest": sha256_json(policy),
        "recipients": fixed_recipients,
        "template_id": TEMPLATE_ID,
        "attachment_names": fixed_attachments,
        "activation_token": token,
        "external_side_effects": False,
    }


def activate_delivery_policy(root: Path, token: str) -> dict[str, Any]:
    workspace = workspace_root(root)
    policy = _load_private_json(
        _private_state_path(workspace, POLICY_NAME),
        POLICY_SCHEMA,
        "delivery policy",
    )
    expected = required_digest(policy.get("activation_token_digest"), "activation_token_digest")
    if not hmac.compare_digest(sha256_text(bounded_text(token, "activation token", 128)), expected):
        raise ValueError("delivery policy activation token does not match")
    authorization_path = _private_state_path(workspace, AUTHORIZATION_NAME)
    policy_digest = sha256_json(policy)
    if authorization_path.exists():
        existing = _load_private_json(
            authorization_path,
            AUTHORIZATION_SCHEMA,
            "delivery authorization",
        )
        if existing.get("policy_id") != policy.get("policy_id") or existing.get("policy_digest") != policy_digest:
            raise ValueError("existing delivery authorization belongs to a different policy")
        if existing.get("state") == "active":
            return _authorization_result("already_active", existing)
        if existing.get("state") != "disabled":
            raise ValueError("existing delivery authorization cannot be reactivated")
    authorization = {
        "schema_version": AUTHORIZATION_SCHEMA,
        "state": "active",
        "policy_id": bounded_text(policy.get("policy_id"), "policy_id", 128),
        "policy_digest": policy_digest,
        "activated_at": _now(),
        "approval_method": "exact_activation_token",
    }
    _write_private_json(authorization_path, authorization, exclusive=not authorization_path.exists())
    return _authorization_result("active", authorization)


def disable_delivery_policy(root: Path) -> dict[str, Any]:
    workspace = workspace_root(root)
    authorization_path = _private_state_path(workspace, AUTHORIZATION_NAME)
    authorization = _load_private_json(
        authorization_path,
        AUTHORIZATION_SCHEMA,
        "delivery authorization",
    )
    if authorization.get("state") == "disabled":
        return _authorization_result("already_disabled", authorization)
    if authorization.get("state") != "active":
        raise ValueError("delivery authorization is not active")
    disabled = {
        **authorization,
        "state": "disabled",
        "disabled_at": _now(),
    }
    _write_private_json(authorization_path, disabled, exclusive=False)
    return _authorization_result("disabled", disabled)


def delivery_policy_status(root: Path) -> dict[str, Any]:
    workspace = workspace_root(root)
    policy_path = _private_state_path(workspace, POLICY_NAME)
    authorization_path = _private_state_path(workspace, AUTHORIZATION_NAME)
    if not policy_path.exists():
        return {
            "operation": "policy_status",
            "state": "not_configured",
            "policy_ref": POLICY_REF,
            "authorization_ref": AUTHORIZATION_REF,
            "external_side_effects": False,
        }
    policy = _load_private_json(policy_path, POLICY_SCHEMA, "delivery policy")
    policy_digest = sha256_json(policy)
    state = "pending_activation"
    if authorization_path.exists():
        authorization = _load_private_json(
            authorization_path,
            AUTHORIZATION_SCHEMA,
            "delivery authorization",
        )
        if authorization.get("state") == "disabled":
            state = "disabled"
        elif authorization.get("state") != "active":
            state = "inactive"
        elif authorization.get("policy_id") != policy.get("policy_id"):
            state = "policy_mismatch"
        elif authorization.get("policy_digest") != policy_digest:
            state = "policy_changed"
        else:
            state = "active"
    return {
        "operation": "policy_status",
        "state": state,
        "policy_ref": POLICY_REF,
        "authorization_ref": AUTHORIZATION_REF,
        "policy_id": policy.get("policy_id"),
        "policy_digest": policy_digest,
        "recipients": policy.get("recipients"),
        "template_id": policy.get("template_id"),
        "attachment_names": policy.get("attachment_names"),
        "external_side_effects": False,
    }


def send_draft(root: Path, draft_ref_value: str) -> dict[str, Any]:
    workspace = workspace_root(root)
    draft_ref, draft_path = workspace_path(workspace, draft_ref_value, must_exist=True)
    if draft_path.suffix.lower() != ".json":
        raise ValueError("draft_ref must select a JSON artifact")
    draft = json.loads(draft_path.read_text(encoding="utf-8"))
    validate_draft_artifact(workspace, draft)

    policy = _load_private_json(
        _private_state_path(workspace, POLICY_NAME),
        POLICY_SCHEMA,
        "delivery policy",
    )
    authorization = _load_private_json(
        _private_state_path(workspace, AUTHORIZATION_NAME),
        AUTHORIZATION_SCHEMA,
        "delivery authorization",
    )
    policy_digest = sha256_json(policy)
    _validate_active_authorization(policy, policy_digest, authorization)
    fixed_recipients = validate_recipients(draft.get("recipients"))
    if fixed_recipients != validate_recipients(policy.get("recipients")):
        raise ValueError("draft recipients do not match the active fixed delivery policy")
    if draft.get("template_id") != policy.get("template_id") or draft.get("template_id") != TEMPLATE_ID:
        raise ValueError("draft template does not match the active fixed delivery policy")

    fixed_attachments = validate_attachment_names(policy.get("attachment_names"))
    attachment_refs, attachment_paths = resolve_attachments(workspace, draft, fixed_attachments)
    manager = _validate_clawemail_install(Path(_transport_skill_root(policy)))
    draft_digest = sha256_path(draft_path)
    receipt_ref = f"{DELIVERY_DIR_REF}/{draft_digest.removeprefix('sha256:')}.json"
    _, receipt_path = workspace_path(workspace, receipt_ref, must_exist=False, allow_existing=True)
    if receipt_path.exists():
        return _existing_delivery_result(receipt_ref, receipt_path, draft_ref, draft_digest)

    guard = {
        "schema_version": RECEIPT_SCHEMA,
        "state": "sending",
        "created_at": _now(),
        "draft_ref": draft_ref,
        "draft_digest": draft_digest,
        "policy_id": policy["policy_id"],
        "policy_digest": policy_digest,
        "recipients": fixed_recipients,
        "template_id": TEMPLATE_ID,
        "attachment_refs": attachment_refs,
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    _write_private_json(receipt_path, guard, exclusive=True)

    try:
        provider_output = _run_clawemail(
            manager,
            recipients=fixed_recipients,
            subject=bounded_text(draft.get("subject"), "draft subject", 300),
            body=bounded_content(draft.get("body"), "draft body", 20_000),
            attachments=attachment_paths,
        )
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        unknown = {
            **guard,
            "state": "unknown",
            "updated_at": _now(),
            "error_class": "delivery_ambiguous",
            "error": _bounded_error(exc),
        }
        _write_private_json(receipt_path, unknown, exclusive=False)
        raise ValueError(
            f"email delivery result is ambiguous; do not retry automatically; receipt={receipt_ref}"
        ) from exc

    receipt = {
        **guard,
        "state": "sent",
        "sent_at": _now(),
        "provider_result_digest": sha256_text(provider_output),
    }
    _write_private_json(receipt_path, receipt, exclusive=False)
    return {
        "operation": "send",
        "state": "sent",
        "draft_ref": draft_ref,
        "draft_digest": draft_digest,
        "policy_id": policy["policy_id"],
        "policy_digest": policy_digest,
        "recipients": fixed_recipients,
        "template_id": TEMPLATE_ID,
        "attachment_refs": attachment_refs,
        "receipt_ref": receipt_ref,
        "artifact_refs": [draft_ref, receipt_ref],
        "external_side_effects": True,
    }


def _run_clawemail(
    manager: Path,
    *,
    recipients: list[str],
    subject: str,
    body: str,
    attachments: list[Path],
) -> str:
    with tempfile.TemporaryDirectory(prefix="ts-email-send-") as temp_dir:
        body_path = Path(temp_dir) / "body.txt"
        body_path.write_text(body, encoding="utf-8")
        body_path.chmod(0o600)
        command = [
            str(manager),
            "--json",
            "send",
            "--to",
            ",".join(recipients),
            "--subject",
            subject,
            "--body-file",
            str(body_path),
        ]
        for path in attachments:
            command.extend(["--attach", str(path)])
        command.append("--yes")
        completed = subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,
            check=False,
            env={**os.environ, "NO_COLOR": "1"},
        )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        diagnostic = bounded_text(detail or "no diagnostic", "ClawEmail diagnostic", 2000)
        raise ValueError(f"ClawEmail send failed with exit {completed.returncode}: {diagnostic}")
    return completed.stdout


def _existing_delivery_result(
    receipt_ref: str,
    receipt_path: Path,
    draft_ref: str,
    draft_digest: str,
) -> dict[str, Any]:
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if not isinstance(receipt, dict) or receipt.get("schema_version") != RECEIPT_SCHEMA:
        raise ValueError("existing email delivery receipt is invalid")
    if receipt.get("draft_ref") != draft_ref or receipt.get("draft_digest") != draft_digest:
        raise ValueError("existing email delivery receipt does not match the draft")
    state = receipt.get("state")
    if state != "sent":
        raise ValueError(f"email delivery remains {state}; do not retry automatically; receipt={receipt_ref}")
    return {
        "operation": "send",
        "state": "already_sent",
        "draft_ref": draft_ref,
        "draft_digest": draft_digest,
        "policy_id": receipt.get("policy_id"),
        "policy_digest": receipt.get("policy_digest"),
        "recipients": receipt.get("recipients"),
        "template_id": receipt.get("template_id"),
        "attachment_refs": receipt.get("attachment_refs"),
        "receipt_ref": receipt_ref,
        "artifact_refs": [draft_ref, receipt_ref],
        "external_side_effects": False,
    }


def _validate_active_authorization(
    policy: dict[str, Any],
    policy_digest: str,
    authorization: dict[str, Any],
) -> None:
    if authorization.get("state") != "active":
        raise ValueError("fixed delivery policy is not active")
    if authorization.get("policy_id") != policy.get("policy_id"):
        raise ValueError("delivery authorization policy_id does not match")
    if authorization.get("policy_digest") != policy_digest:
        raise ValueError("delivery policy changed after activation")
    if authorization.get("approval_method") != "exact_activation_token":
        raise ValueError("delivery authorization approval method is invalid")


def _authorization_result(state: str, authorization: dict[str, Any]) -> dict[str, Any]:
    return {
        "operation": "policy_authorization",
        "state": state,
        "policy_ref": POLICY_REF,
        "authorization_ref": AUTHORIZATION_REF,
        "policy_id": authorization["policy_id"],
        "policy_digest": authorization["policy_digest"],
        "external_side_effects": False,
    }


def _transport_skill_root(policy: dict[str, Any]) -> str:
    transport = policy.get("transport")
    if not isinstance(transport, dict) or set(transport) != {"kind", "skill_root"}:
        raise ValueError("delivery policy transport must contain kind and skill_root")
    if transport.get("kind") != "clawemail":
        raise ValueError("delivery policy transport must be clawemail")
    return bounded_text(transport.get("skill_root"), "ClawEmail skill_root", 4096)


def _validate_clawemail_install(skill_root: Path) -> Path:
    resolved = skill_root.expanduser().resolve(strict=True)
    if not resolved.is_dir():
        raise ValueError("ClawEmail skill_root must be a directory")
    skill_file = resolved / "SKILL.md"
    manager = resolved / "bin" / "clawemail-manager"
    state_dir = resolved / ".clawemail"
    settings = state_dir / "skill.json"
    auth = state_dir / "mail-cli.json"
    if not skill_file.is_file() or "name: clawemail" not in skill_file.read_text(encoding="utf-8")[:2048]:
        raise ValueError("configured ClawEmail skill_root is not a clawemail skill")
    if not manager.is_file() or manager.is_symlink() or not os.access(manager, os.X_OK):
        raise ValueError("configured ClawEmail manager is missing or unsafe")
    if state_dir.is_symlink():
        raise ValueError("ClawEmail private state directory must not be a symbolic link")
    for path, label in ((settings, "settings"), (auth, "authentication")):
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"ClawEmail {label} file is missing or unsafe")
        if path.stat().st_mode & 0o077:
            raise ValueError(f"ClawEmail {label} file must have mode 0600")
    return manager


def _private_state_path(workspace: Path, name: str) -> Path:
    state_dir = workspace / ".pi"
    if state_dir.is_symlink():
        raise ValueError("workspace .pi directory must not be a symbolic link")
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / name


def _refuse_existing_private_state(*paths: Path) -> None:
    existing = [str(path) for path in paths if path.exists()]
    if existing:
        raise ValueError(f"email delivery policy state already exists: {', '.join(existing)}")


def _load_private_json(path: Path, schema: str, label: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"{label} is missing or unsafe: {path}")
    if path.stat().st_mode & 0o077:
        raise ValueError(f"{label} must have mode 0600: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != schema:
        raise ValueError(f"{label} must use {schema}")
    return value


def _write_private_json(path: Path, value: dict[str, Any], *, exclusive: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink() or path.is_symlink():
        raise ValueError(f"private email state path is unsafe: {path}")
    flags = os.O_WRONLY | os.O_CREAT | (os.O_EXCL if exclusive else os.O_TRUNC)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
    except Exception:
        if exclusive:
            path.unlink(missing_ok=True)
        raise


def _bounded_error(error: Exception) -> str:
    text = str(error).replace("\x00", "").strip()
    return text[:2000] or type(error).__name__


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
