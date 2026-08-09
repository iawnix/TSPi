"""Private fixed-scope policy and idempotent ClawEmail delivery."""

from __future__ import annotations

import hmac
import json
import os
import secrets
import subprocess
import tempfile
from dataclasses import dataclass
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


@dataclass(frozen=True)
class _PolicyState:
    root: Path
    state: str
    policy: dict[str, Any] | None
    policy_digest: str | None
    authorization: dict[str, Any] | None


@dataclass(frozen=True)
class _PolicyResolution:
    effective: _PolicyState
    local: _PolicyState
    scope: str


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
    resolution = _resolve_delivery_policy(workspace)
    effective = resolution.effective
    result = {
        "operation": "policy_status",
        "state": effective.state,
        "policy_ref": POLICY_REF,
        "authorization_ref": AUTHORIZATION_REF,
        "policy_scope": resolution.scope,
        "policy_source_root": str(effective.root),
        "local_policy_state": resolution.local.state,
        "external_side_effects": False,
    }
    if effective.policy is not None:
        result.update(
            {
                "policy_id": effective.policy.get("policy_id"),
                "policy_digest": effective.policy_digest,
                "recipients": effective.policy.get("recipients"),
                "template_id": effective.policy.get("template_id"),
                "attachment_names": effective.policy.get("attachment_names"),
            }
        )
    if resolution.local.policy is not None:
        result["local_policy_id"] = resolution.local.policy.get("policy_id")
        result["local_policy_digest"] = resolution.local.policy_digest
    return result


def send_draft(root: Path, draft_ref_value: str) -> dict[str, Any]:
    workspace = workspace_root(root)
    draft_ref, draft_path = workspace_path(workspace, draft_ref_value, must_exist=True)
    if draft_path.suffix.lower() != ".json":
        raise ValueError("draft_ref must select a JSON artifact")
    draft = json.loads(draft_path.read_text(encoding="utf-8"))
    validate_draft_artifact(workspace, draft)

    resolution = _resolve_delivery_policy(workspace)
    if resolution.effective.state != "active":
        _raise_inactive_policy(resolution)
    policy = resolution.effective.policy
    authorization = resolution.effective.authorization
    policy_digest = resolution.effective.policy_digest
    if policy is None or authorization is None or policy_digest is None:
        raise ValueError("active delivery policy resolution is incomplete")
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
        "policy_scope": resolution.scope,
        "policy_source_root": str(resolution.effective.root),
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
        "policy_scope": resolution.scope,
        "policy_source_root": str(resolution.effective.root),
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
        "policy_scope": receipt.get("policy_scope", "local"),
        "policy_source_root": receipt.get("policy_source_root"),
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


def _resolve_delivery_policy(workspace: Path) -> _PolicyResolution:
    local = _delivery_policy_state(workspace)
    if local.state not in {"not_configured", "pending_activation"}:
        return _PolicyResolution(effective=local, local=local, scope="local")

    policy_root = _configured_policy_root()
    if policy_root is None or policy_root == workspace or not _is_descendant(workspace, policy_root):
        return _PolicyResolution(effective=local, local=local, scope="local")

    inherited = _delivery_policy_state(policy_root)
    if inherited.state != "active":
        return _PolicyResolution(effective=local, local=local, scope="local")
    if local.policy is not None and not _same_policy_scope(local.policy, inherited.policy):
        return _PolicyResolution(effective=local, local=local, scope="local")
    return _PolicyResolution(effective=inherited, local=local, scope="inherited")


def _delivery_policy_state(root: Path) -> _PolicyState:
    policy_path = _private_state_path(root, POLICY_NAME, create_parent=False)
    authorization_path = _private_state_path(root, AUTHORIZATION_NAME, create_parent=False)
    policy_present = policy_path.exists() or policy_path.is_symlink()
    authorization_present = authorization_path.exists() or authorization_path.is_symlink()
    if not policy_present:
        authorization = None
        state = "not_configured"
        if authorization_present:
            authorization = _load_private_json(
                authorization_path,
                AUTHORIZATION_SCHEMA,
                "delivery authorization",
            )
            state = "policy_mismatch"
        return _PolicyState(root, state, None, None, authorization)

    policy = _load_private_json(policy_path, POLICY_SCHEMA, "delivery policy")
    policy_digest = sha256_json(policy)
    if not authorization_present:
        return _PolicyState(root, "pending_activation", policy, policy_digest, None)

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
    elif authorization.get("approval_method") != "exact_activation_token":
        state = "authorization_invalid"
    else:
        state = "active"
    return _PolicyState(root, state, policy, policy_digest, authorization)


def _configured_policy_root() -> Path | None:
    value = os.environ.get("TS_EMAIL_POLICY_ROOT") or os.environ.get("TS_WORKSPACE_ROOT")
    if not value:
        return None
    lexical = Path(os.path.abspath(Path(value).expanduser()))
    current = Path(lexical.anchor)
    for part in lexical.parts[1:]:
        current /= part
        if current.is_symlink():
            raise ValueError(f"configured email policy root must not contain symbolic links: {lexical}")
    resolved = lexical.resolve(strict=True)
    if not resolved.is_dir():
        raise ValueError(f"configured email policy root must be a directory: {lexical}")
    return resolved


def _is_descendant(workspace: Path, policy_root: Path) -> bool:
    try:
        workspace.relative_to(policy_root)
    except ValueError:
        return False
    return workspace != policy_root


def _same_policy_scope(local: dict[str, Any], inherited: dict[str, Any] | None) -> bool:
    if inherited is None:
        return False
    return _policy_scope(local) == _policy_scope(inherited)


def _policy_scope(policy: dict[str, Any]) -> tuple[Any, ...]:
    skill_root = Path(_transport_skill_root(policy)).expanduser().resolve(strict=True)
    template_id = bounded_text(policy.get("template_id"), "delivery policy template_id", 128)
    return (
        "clawemail",
        str(skill_root),
        tuple(validate_recipients(policy.get("recipients"))),
        template_id,
        tuple(validate_attachment_names(policy.get("attachment_names"))),
    )


def _raise_inactive_policy(resolution: _PolicyResolution) -> None:
    local = resolution.local
    if local.policy is None:
        _load_private_json(
            _private_state_path(local.root, POLICY_NAME, create_parent=False),
            POLICY_SCHEMA,
            "delivery policy",
        )
    if local.authorization is None:
        _load_private_json(
            _private_state_path(local.root, AUTHORIZATION_NAME, create_parent=False),
            AUTHORIZATION_SCHEMA,
            "delivery authorization",
        )
    if local.policy_digest is None:
        raise ValueError("delivery policy digest is unavailable")
    _validate_active_authorization(local.policy, local.policy_digest, local.authorization)
    raise ValueError("fixed delivery policy is not active")


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


def _private_state_path(workspace: Path, name: str, *, create_parent: bool = True) -> Path:
    state_dir = workspace / ".pi"
    if state_dir.is_symlink():
        raise ValueError("workspace .pi directory must not be a symbolic link")
    if create_parent:
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
