"""Installation-configured, idempotent ClawEmail notifications."""

from __future__ import annotations

import fcntl
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import tomllib
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ts_workspace.context import compile_context

from .artifacts import bounded_content, bounded_text, sha256_json, sha256_path, workspace_path, workspace_root
from .errors import NotificationError

CONFIG_ENV = "TS_NOTIFICATION_CONFIG"
CONFIG_SCHEMA = "ts-notification-config/1"
REQUEST_SCHEMA = "ts-user-notification/1"
RECEIPT_SCHEMA = "ts-user-notification-receipt/1"
DELIVERY_DIR_REF = "reports/email/deliveries"
EVENTS = frozenset(
    {
        "progress",
        "act_completed",
        "calculation_failed",
        "calculation_ambiguous",
        "study_completed",
    }
)


@dataclass(frozen=True)
class EmailNotificationConfig:
    source: Path
    enabled: bool
    recipient: str
    clawemail_root: Path
    digest: str


class _DeliveryNotStarted(RuntimeError):
    """The provider process was not started, so no message was sent."""


class _DeliveryAmbiguous(RuntimeError):
    """The provider process started, so delivery cannot be retried safely."""


def notify_user(root: Path, request_file: Path) -> dict[str, Any]:
    """Send one bounded research notification using installation-owned addressing."""

    workspace = workspace_root(root)
    config = load_notification_config()
    if not config.enabled:
        raise ValueError("email notifications are disabled by the installation configuration")
    manager = _validate_clawemail_install(config.clawemail_root)
    request = _load_request(request_file)
    event = _event(request.get("event"))
    subject = bounded_text(request.get("subject"), "notification subject", 300)
    summary = bounded_content(request.get("summary"), "notification summary", 20_000)
    attachment_refs, attachment_paths, attachment_records = _resolve_report_refs(
        workspace,
        request.get("report_refs", []),
    )
    workspace_report = compile_context(workspace, mode="frontier")
    workspace_id = bounded_text(workspace_report.get("workspace_id"), "workspace_id", 128)
    workspace_revision = bounded_text(
        workspace_report.get("workspace_revision"),
        "workspace_revision",
        128,
    )
    notification = {
        "schema_version": REQUEST_SCHEMA,
        "event": event,
        "subject": subject,
        "summary": summary,
        "workspace_id": workspace_id,
        "workspace_revision": workspace_revision,
        "report_artifacts": attachment_records,
        "notification_config_digest": config.digest,
    }
    notification_digest = sha256_json(notification)
    receipt_ref = f"{DELIVERY_DIR_REF}/{notification_digest.removeprefix('sha256:')}.json"
    _, receipt_path = workspace_path(workspace, receipt_ref, must_exist=False, allow_existing=True)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    with _delivery_lock(receipt_path):
        if receipt_path.stat().st_size:
            existing = _existing_delivery_result(receipt_ref, receipt_path, notification_digest)
            if existing is not None:
                return existing

        guard = {
            "schema_version": RECEIPT_SCHEMA,
            "state": "sending",
            "created_at": _now(),
            "event": event,
            "subject": subject,
            "workspace_id": workspace_id,
            "workspace_revision": workspace_revision,
            "notification_digest": notification_digest,
            "notification_config_digest": config.digest,
            "report_artifacts": attachment_records,
        }
        _write_private_json(receipt_path, guard, exclusive=False)

        try:
            _revalidate_notification_inputs(
                workspace,
                config,
                workspace_revision,
                attachment_records,
            )
            provider_output = _run_clawemail(
                manager,
                recipient=config.recipient,
                subject=subject,
                body=summary,
                attachments=list(zip(attachment_paths, attachment_records, strict=True)),
            )
        except (OSError, ValueError, _DeliveryNotStarted) as exc:
            failed = {
                **guard,
                "state": "failed",
                "updated_at": _now(),
                "error_class": "delivery_not_started",
                "error": _safe_error(exc),
            }
            _write_private_json(receipt_path, failed, exclusive=False)
            raise NotificationError(
                f"email notification was not started: {_safe_error(exc)}; receipt={receipt_ref}",
                code="NOTIFICATION_DELIVERY_NOT_STARTED",
                error_class="delivery_not_started",
                state="failed",
                retry_disposition="retry_after_fix",
                receipt_ref=receipt_ref,
            ) from exc
        except _DeliveryAmbiguous as exc:
            diagnostic = _safe_error(exc)
            unknown = {
                **guard,
                "state": "unknown",
                "updated_at": _now(),
                "error_class": "delivery_ambiguous",
                "error": diagnostic,
            }
            _write_private_json(receipt_path, unknown, exclusive=False)
            raise NotificationError(
                f"email notification result is ambiguous: {diagnostic}; "
                f"do not retry automatically; receipt={receipt_ref}",
                code="NOTIFICATION_DELIVERY_AMBIGUOUS",
                error_class="delivery_ambiguous",
                state="unknown",
                retry_disposition="reconcile_only",
                receipt_ref=receipt_ref,
            ) from exc

        receipt = {
            **guard,
            "state": "sent",
            "sent_at": _now(),
            "provider_result_digest": sha256_json({"stdout": provider_output}),
        }
        _write_private_json(receipt_path, receipt, exclusive=False)
        return _delivery_result(
            state="sent",
            event=event,
            subject=subject,
            workspace_id=workspace_id,
            workspace_revision=workspace_revision,
            notification_digest=notification_digest,
            attachment_refs=attachment_refs,
            receipt_ref=receipt_ref,
            external_side_effects=True,
        )


def load_notification_config(path: str | Path | None = None) -> EmailNotificationConfig:
    source = _configured_path(path)
    try:
        with source.open("rb") as handle:
            raw = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"invalid notification configuration: {source}: {exc}") from exc
    if set(raw) != {"notifications"}:
        raise ValueError("notification configuration must contain only [notifications]")
    notifications = _mapping(raw.get("notifications"), "notifications")
    if set(notifications) != {"email"}:
        raise ValueError("notification configuration must contain only [notifications.email]")
    email = _mapping(notifications.get("email"), "notifications.email")
    expected = {"enabled", "recipient", "clawemail_root"}
    unknown = sorted(set(email) - expected)
    missing = sorted(expected - set(email))
    if unknown or missing:
        details = []
        if unknown:
            details.append(f"unknown fields: {', '.join(unknown)}")
        if missing:
            details.append(f"missing fields: {', '.join(missing)}")
        raise ValueError(f"invalid notifications.email configuration ({'; '.join(details)})")
    enabled = email.get("enabled")
    if not isinstance(enabled, bool):
        raise ValueError("notifications.email.enabled must be true or false")
    recipient = _email_address(email.get("recipient"))
    clawemail_raw = bounded_text(email.get("clawemail_root"), "notifications.email.clawemail_root", 4096)
    clawemail_root = Path(clawemail_raw).expanduser()
    if not clawemail_root.is_absolute() or clawemail_root.is_symlink():
        raise ValueError("notifications.email.clawemail_root must be an absolute non-symbolic-link path")
    try:
        clawemail_root = clawemail_root.resolve(strict=True)
    except OSError as exc:
        raise ValueError("configured ClawEmail installation is unavailable") from exc
    canonical = {
        "schema_version": CONFIG_SCHEMA,
        "email": {
            "enabled": enabled,
            "recipient": recipient,
            "clawemail_root": str(clawemail_root),
        },
    }
    return EmailNotificationConfig(source, enabled, recipient, clawemail_root, sha256_json(canonical))


def _configured_path(path: str | Path | None) -> Path:
    raw = str(path) if path is not None else os.environ.get(CONFIG_ENV, "").strip()
    if not raw:
        raise ValueError(f"{CONFIG_ENV} is not configured")
    source = Path(raw).expanduser()
    if not source.is_absolute():
        raise ValueError(f"{CONFIG_ENV} must be an absolute path")
    if source.is_symlink() or not source.is_file():
        raise ValueError(f"{CONFIG_ENV} is not a regular file: {source}")
    if source.stat().st_mode & 0o077:
        raise ValueError(f"{CONFIG_ENV} must have mode 0600: {source}")
    return source.resolve(strict=True)


def _load_request(request_file: Path) -> dict[str, Any]:
    value = json.loads(request_file.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("notification request must be an object")
    allowed = {"schema_version", "event", "subject", "summary", "report_refs"}
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError(f"notification request contains unknown fields: {', '.join(unknown)}")
    if value.get("schema_version") != REQUEST_SCHEMA:
        raise ValueError(f"notification request schema_version must be {REQUEST_SCHEMA}")
    return value


def _resolve_report_refs(
    workspace: Path,
    value: Any,
) -> tuple[list[str], list[Path], list[dict[str, Any]]]:
    if not isinstance(value, list) or len(value) > 8:
        raise ValueError("report_refs must be an array with at most 8 entries")
    refs: list[str] = []
    paths: list[Path] = []
    records: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        ref, path = workspace_path(workspace, item, must_exist=True)
        if ref in refs:
            raise ValueError("report_refs contains duplicates")
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"report_refs[{index}] must select a regular file")
        manifest_binding = _report_manifest_binding(workspace, ref, path)
        refs.append(ref)
        paths.append(path)
        records.append({
            "ref": ref,
            "sha256": sha256_path(path),
            "size_bytes": path.stat().st_size,
            **manifest_binding,
        })
    return refs, paths, records


def _report_manifest_binding(workspace: Path, ref: str, path: Path) -> dict[str, Any]:
    parts = ref.split("/")
    if len(parts) < 3:
        raise ValueError("notification attachments must belong to a manifest-bound report package")
    package_ref = "/".join(parts[:2])
    member_ref = "/".join(parts[2:])
    manifest_ref = f"{package_ref}/package_manifest.json"
    _, manifest_path = workspace_path(workspace, manifest_ref, must_exist=True)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"report package manifest is invalid: {manifest_ref}") from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != "ts-report-package/3":
        raise ValueError(f"report package manifest has an unsupported schema: {manifest_ref}")
    files = manifest.get("files")
    if not isinstance(files, list):
        raise ValueError(f"report package manifest has no file index: {manifest_ref}")
    matches = [item for item in files if isinstance(item, dict) and item.get("ref") == member_ref]
    if len(matches) != 1:
        raise ValueError(f"notification attachment is not listed in its report manifest: {ref}")
    listed = matches[0]
    current_digest = sha256_path(path)
    current_size = path.stat().st_size
    if listed.get("sha256") != current_digest or listed.get("size_bytes") != current_size:
        raise ValueError(f"notification attachment does not match its report manifest: {ref}")
    return {
        "package_ref": package_ref,
        "manifest_ref": manifest_ref,
        "manifest_sha256": sha256_path(manifest_path),
    }


def _run_clawemail(
    manager: Path,
    *,
    recipient: str,
    subject: str,
    body: str,
    attachments: list[tuple[Path, dict[str, Any]]],
) -> str:
    try:
        with tempfile.TemporaryDirectory(prefix="ts-notify-user-") as temp_dir:
            body_path = Path(temp_dir) / "body.txt"
            body_path.write_text(body, encoding="utf-8")
            body_path.chmod(0o600)
            attachment_dir = Path(temp_dir) / "attachments"
            attachment_dir.mkdir(mode=0o700)
            staged_attachments: list[Path] = []
            for index, (source, record) in enumerate(attachments):
                staged = attachment_dir / f"{index:02d}-{source.name}"
                shutil.copyfile(source, staged)
                staged.chmod(0o600)
                if sha256_path(staged) != record.get("sha256") or staged.stat().st_size != record.get("size_bytes"):
                    raise _DeliveryNotStarted("notification attachment changed while staging")
                staged_attachments.append(staged)
            command = [
                str(manager),
                "--json",
                "send",
                "--to",
                recipient,
                "--subject",
                subject,
                "--body-file",
                str(body_path),
            ]
            for attachment in staged_attachments:
                command.extend(["--attach", str(attachment)])
            command.append("--yes")
            try:
                completed = subprocess.run(
                    command,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=120,
                    check=False,
                    env={**os.environ, "NO_COLOR": "1"},
                )
            except OSError as exc:
                raise _DeliveryNotStarted(str(exc)) from exc
            except subprocess.TimeoutExpired as exc:
                raise _DeliveryAmbiguous("ClawEmail timed out after the provider process started") from exc
    except _DeliveryNotStarted:
        raise
    except _DeliveryAmbiguous:
        raise
    except OSError as exc:
        raise _DeliveryNotStarted(str(exc)) from exc
    if completed.returncode != 0:
        raise _DeliveryAmbiguous(
            f"ClawEmail exited with {completed.returncode}: {_provider_diagnostic(completed)}"
        )
    return completed.stdout


def _revalidate_notification_inputs(
    workspace: Path,
    config: EmailNotificationConfig,
    workspace_revision: str,
    attachment_records: list[dict[str, Any]],
) -> None:
    current_config = load_notification_config(config.source)
    if current_config.digest != config.digest:
        raise ValueError("notification configuration changed after preflight")
    current_report = compile_context(workspace, mode="frontier")
    if current_report.get("workspace_revision") != workspace_revision:
        raise ValueError("workspace revision changed after notification preflight")
    for record in attachment_records:
        ref, path = workspace_path(workspace, record.get("ref"), must_exist=True)
        if sha256_path(path) != record.get("sha256") or path.stat().st_size != record.get("size_bytes"):
            raise ValueError(f"notification report artifact changed after preflight: {ref}")
        manifest_ref, manifest_path = workspace_path(workspace, record.get("manifest_ref"), must_exist=True)
        if sha256_path(manifest_path) != record.get("manifest_sha256"):
            raise ValueError(f"notification report manifest changed after preflight: {manifest_ref}")
        _report_manifest_binding(workspace, ref, path)


def _existing_delivery_result(
    receipt_ref: str,
    receipt_path: Path,
    notification_digest: str,
) -> dict[str, Any] | None:
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if not isinstance(receipt, dict) or receipt.get("schema_version") != RECEIPT_SCHEMA:
        raise ValueError("existing email notification receipt is invalid")
    if receipt.get("notification_digest") != notification_digest:
        raise ValueError("existing email notification receipt does not match the request")
    state = receipt.get("state")
    if state == "failed" and receipt.get("error_class") == "delivery_not_started":
        return None
    if state != "sent":
        raise ValueError(
            f"email notification remains {state}; do not retry automatically; receipt={receipt_ref}"
        )
    return _delivery_result(
        state="already_sent",
        event=str(receipt.get("event")),
        subject=str(receipt.get("subject")),
        workspace_id=str(receipt.get("workspace_id")),
        workspace_revision=str(receipt.get("workspace_revision")),
        notification_digest=notification_digest,
        attachment_refs=[
            str(record.get("ref"))
            for record in receipt.get("report_artifacts", [])
            if isinstance(record, dict) and isinstance(record.get("ref"), str)
        ],
        receipt_ref=receipt_ref,
        external_side_effects=False,
    )


def _delivery_result(
    *,
    state: str,
    event: str,
    subject: str,
    workspace_id: str,
    workspace_revision: str,
    notification_digest: str,
    attachment_refs: list[str],
    receipt_ref: str,
    external_side_effects: bool,
) -> dict[str, Any]:
    return {
        "ok": True,
        "operation": "send",
        "state": state,
        "event": event,
        "subject": subject,
        "workspace_id": workspace_id,
        "workspace_revision": workspace_revision,
        "notification_digest": notification_digest,
        "attachment_refs": attachment_refs,
        "receipt_ref": receipt_ref,
        "artifact_refs": [*attachment_refs, receipt_ref],
        "external_side_effects": external_side_effects,
    }


def _validate_clawemail_install(skill_root: Path) -> Path:
    try:
        resolved = skill_root.expanduser().resolve(strict=True)
        if not resolved.is_dir():
            raise ValueError("configured ClawEmail installation is not a directory")
        skill_file = resolved / "SKILL.md"
        manager = resolved / "bin" / "clawemail-manager"
        state_dir = resolved / ".clawemail"
        settings = state_dir / "skill.json"
        auth = state_dir / "mail-cli.json"
        if not skill_file.is_file() or "name: clawemail" not in skill_file.read_text(encoding="utf-8")[:2048]:
            raise ValueError("configured ClawEmail installation is invalid")
        if not manager.is_file() or manager.is_symlink() or not os.access(manager, os.X_OK):
            raise ValueError("configured ClawEmail manager is missing or unsafe")
        if state_dir.is_symlink():
            raise ValueError("ClawEmail private state directory must not be a symbolic link")
        for path, label in ((settings, "settings"), (auth, "authentication")):
            if not path.is_file() or path.is_symlink():
                raise ValueError(f"ClawEmail {label} file is missing or unsafe")
            if path.stat().st_mode & 0o077:
                raise ValueError(f"ClawEmail {label} file must have mode 0600")
    except OSError as exc:
        raise ValueError("configured ClawEmail installation is unavailable") from exc
    return manager


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a TOML table")
    return value


def _email_address(value: Any) -> str:
    address = bounded_text(value, "notifications.email.recipient", 320)
    if address.count("@") != 1 or any(character.isspace() for character in address):
        raise ValueError("notifications.email.recipient must be one email address")
    local, domain = address.split("@")
    if not local or "." not in domain or domain.startswith(".") or domain.endswith("."):
        raise ValueError("notifications.email.recipient must be one email address")
    return address


def _event(value: Any) -> str:
    event = bounded_text(value, "notification event", 64)
    if event not in EVENTS:
        raise ValueError(f"unsupported notification event: {event}")
    return event


@contextmanager
def _delivery_lock(path: Path):
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("email notification receipt must be a regular file")
        os.fchmod(descriptor, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _write_private_json(path: Path, value: dict[str, Any], *, exclusive: bool) -> None:
    payload = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | (os.O_EXCL if exclusive else os.O_TRUNC)
    descriptor = os.open(path, flags, 0o600)
    try:
        view = memoryview(payload)
        while view:
            view = view[os.write(descriptor, view):]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.chmod(path, 0o600)


def _safe_error(exc: BaseException) -> str:
    return bounded_text(str(exc) or exc.__class__.__name__, "delivery error", 2000)


def _provider_diagnostic(completed: subprocess.CompletedProcess[str]) -> str:
    # ClawEmail stdout can contain the compose preview, including body text.
    raw = (completed.stderr or "").strip()
    if not raw:
        return "no diagnostic output"
    normalized = " ".join(raw.split())
    normalized = re.sub(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [REDACTED]", normalized, flags=re.IGNORECASE)
    normalized = re.sub(
        r"([?&](?:token|api[_-]?key|password|secret|authorization)=)[^&\s]+",
        r"\1[REDACTED]",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(
        r"\b((?:token|api[_-]?key|password|secret|authorization)\s*[:=]\s*)"
        r"(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)",
        r"\1[REDACTED]",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(r"//([^/@\s]+)@", "//[REDACTED]@", normalized)
    return normalized[:1000]


def _now() -> str:
    return datetime.now(UTC).astimezone().isoformat(timespec="seconds")
