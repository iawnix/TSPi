"""Installation-configured, idempotent ClawEmail notifications."""

from __future__ import annotations

import fcntl
import json
import mimetypes
import os
import re
import shutil
import smtplib
import ssl
import stat
import subprocess
import tempfile
import tomllib
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import formatdate
from pathlib import Path
from typing import Any

from ts_agent.workspace.context import compile_context

from .artifacts import bounded_content, bounded_text, sha256_json, sha256_path, workspace_path, workspace_root
from .errors import NotificationError

CONFIG_ENV = "TS_NOTIFICATION_CONFIG"
CONFIG_SCHEMA = "ts-notification-config/1"
SMTP_CONFIG_SCHEMA = "ts-notification-config/2"
REQUEST_SCHEMA = "ts-user-notification/1"
RECEIPT_SCHEMA = "ts-user-notification-receipt/1"
DELIVERY_DIR_REF = "reports/email/deliveries"
SMTP_PRESETS: dict[str, dict[str, Any]] = {
    "163": {"host": "smtp.163.com", "port": 465, "security": "ssl"},
    "qq": {"host": "smtp.qq.com", "port": 465, "security": "ssl"},
}
SMTP_SECURITY = frozenset({"ssl", "starttls"})
ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
EVENTS = frozenset(
    {
        "progress",
        "node_completed",
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
    clawemail_root: Path | None = None
    digest: str = ""
    provider: str = "clawemail"
    from_address: str | None = None
    smtp_preset: str | None = None
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_security: str | None = None
    smtp_username: str | None = None
    smtp_password_env: str | None = None
    smtp_password_file: Path | None = None


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
    manager = (
        _validate_clawemail_install(config.clawemail_root)
        if config.provider == "clawemail"
        else None
    )
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
            "provider": config.provider,
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
            provider_output = _run_provider(
                config,
                manager=manager,
                notification_digest=notification_digest,
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
            provider=config.provider,
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
    enabled = email.get("enabled")
    if not isinstance(enabled, bool):
        raise ValueError("notifications.email.enabled must be true or false")
    recipient = _email_address(email.get("recipient"))
    provider = email.get("provider", "clawemail")
    if not isinstance(provider, str) or provider not in {"clawemail", "smtp"}:
        raise ValueError("notifications.email.provider must be clawemail or smtp")

    if provider == "clawemail":
        expected = {"enabled", "recipient", "clawemail_root"}
        if "provider" in email:
            expected.add("provider")
        _validate_config_fields(email, expected)
        clawemail_root = _private_install_path(
            email.get("clawemail_root"),
            "notifications.email.clawemail_root",
            must_exist=True,
        )
        canonical = {
            "schema_version": CONFIG_SCHEMA,
            "email": {
                "enabled": enabled,
                "recipient": recipient,
                "clawemail_root": str(clawemail_root),
            },
        }
        return EmailNotificationConfig(
            source=source,
            enabled=enabled,
            recipient=recipient,
            provider=provider,
            digest=sha256_json(canonical),
            clawemail_root=clawemail_root,
        )

    return _load_smtp_config(source, email, enabled=enabled, recipient=recipient)


def _load_smtp_config(
    source: Path,
    email: dict[str, Any],
    *,
    enabled: bool,
    recipient: str,
) -> EmailNotificationConfig:
    allowed = {
        "enabled",
        "provider",
        "preset",
        "recipient",
        "from_address",
        "username",
        "password_env",
        "password_file",
        "host",
        "port",
        "security",
    }
    _validate_config_fields(email, allowed, required={"provider", "preset", "username"})
    preset = bounded_text(email.get("preset"), "notifications.email.preset", 32).lower()
    if preset not in SMTP_PRESETS:
        raise ValueError(
            "notifications.email.preset must be one of: "
            + ", ".join(sorted(SMTP_PRESETS))
        )
    defaults = SMTP_PRESETS[preset]
    host = bounded_text(email.get("host", defaults["host"]), "notifications.email.host", 255)
    if any(character.isspace() for character in host) or "/" in host or "@" in host:
        raise ValueError("notifications.email.host must be a hostname")
    if host != defaults["host"]:
        raise ValueError(f"notifications.email.host must be {defaults['host']} for preset {preset}")
    port = email.get("port", defaults["port"])
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        raise ValueError("notifications.email.port must be an integer from 1 to 65535")
    security = bounded_text(
        email.get("security", defaults["security"]),
        "notifications.email.security",
        16,
    ).lower()
    if security not in SMTP_SECURITY:
        raise ValueError("notifications.email.security must be ssl or starttls")
    username = _email_address(email.get("username"))
    from_address = _email_address(email.get("from_address", username))
    password_env, password_file = _secret_source(email)
    canonical = {
        "schema_version": SMTP_CONFIG_SCHEMA,
        "email": {
            "enabled": enabled,
            "provider": "smtp",
            "preset": preset,
            "recipient": recipient,
            "from_address": from_address,
            "username": username,
            "host": host,
            "port": port,
            "security": security,
            "credential": {
                "env": password_env,
                "file": str(password_file) if password_file is not None else None,
            },
        },
    }
    return EmailNotificationConfig(
        source=source,
        enabled=enabled,
        recipient=recipient,
        provider="smtp",
        digest=sha256_json(canonical),
        from_address=from_address,
        smtp_preset=preset,
        smtp_host=host,
        smtp_port=port,
        smtp_security=security,
        smtp_username=username,
        smtp_password_env=password_env,
        smtp_password_file=password_file,
    )


def _validate_config_fields(
    value: dict[str, Any],
    allowed: set[str],
    *,
    required: set[str] | None = None,
) -> None:
    unknown = sorted(set(value) - allowed)
    missing = sorted((required or allowed) - set(value))
    if unknown or missing:
        details = []
        if unknown:
            details.append(f"unknown fields: {', '.join(unknown)}")
        if missing:
            details.append(f"missing fields: {', '.join(missing)}")
        raise ValueError(f"invalid notifications.email configuration ({'; '.join(details)})")


def _private_install_path(
    value: Any,
    label: str,
    *,
    must_exist: bool,
    directory: bool = True,
) -> Path:
    raw = bounded_text(value, label, 4096)
    path = Path(raw).expanduser()
    if not path.is_absolute() or path.is_symlink():
        raise ValueError(f"{label} must be an absolute non-symbolic-link path")
    try:
        resolved = path.resolve(strict=must_exist)
    except OSError as exc:
        raise ValueError(f"{label} is unavailable") from exc
    if must_exist and directory and not resolved.is_dir():
        raise ValueError(f"{label} must be a directory")
    return resolved


def _secret_source(email: dict[str, Any]) -> tuple[str | None, Path | None]:
    password_env = email.get("password_env")
    password_file_raw = email.get("password_file")
    if (password_env is None) == (password_file_raw is None):
        raise ValueError(
            "notifications.email must set exactly one of password_env or password_file"
        )
    if password_env is not None:
        name = bounded_text(password_env, "notifications.email.password_env", 128)
        if not ENV_NAME.fullmatch(name):
            raise ValueError("notifications.email.password_env must be an environment variable name")
        return name, None
    path = _private_install_path(
        password_file_raw,
        "notifications.email.password_file",
        must_exist=True,
        directory=False,
    )
    if not path.is_file():
        raise ValueError("notifications.email.password_file must be a regular file")
    if path.stat().st_mode & 0o077:
        raise ValueError("notifications.email.password_file must have mode 0600")
    return None, path


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
    if not isinstance(manifest, dict) or manifest.get("schema_version") != "ts-report-package/4":
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


def _run_provider(
    config: EmailNotificationConfig,
    *,
    manager: Path | None,
    notification_digest: str,
    recipient: str,
    subject: str,
    body: str,
    attachments: list[tuple[Path, dict[str, Any]]],
) -> str:
    if config.provider == "clawemail":
        if manager is None:
            raise _DeliveryNotStarted("ClawEmail manager is unavailable")
        return _run_clawemail(
            manager,
            recipient=recipient,
            subject=subject,
            body=body,
            attachments=attachments,
        )
    if config.provider == "smtp":
        return _run_smtp(
            config,
            notification_digest=notification_digest,
            recipient=recipient,
            subject=subject,
            body=body,
            attachments=attachments,
        )
    raise _DeliveryNotStarted(f"unsupported email provider: {config.provider}")


def _run_smtp(
    config: EmailNotificationConfig,
    *,
    notification_digest: str,
    recipient: str,
    subject: str,
    body: str,
    attachments: list[tuple[Path, dict[str, Any]]],
) -> str:
    if not config.smtp_host or not config.smtp_port or not config.smtp_security:
        raise _DeliveryNotStarted("SMTP configuration is incomplete")
    if "\r" in subject or "\n" in subject:
        raise _DeliveryNotStarted("SMTP subject must not contain line breaks")
    password = _smtp_password(config)
    message = EmailMessage()
    message["From"] = config.from_address or config.smtp_username or ""
    message["To"] = recipient
    message["Subject"] = subject
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = (
        f"<tspi-{notification_digest.removeprefix('sha256:')}"
        f"@{message['From'].split('@', 1)[-1]}>"
    )
    message["X-TSPi-Notification-Digest"] = notification_digest
    message.set_content(body)
    for source, record in attachments:
        try:
            payload = source.read_bytes()
        except OSError as exc:
            raise _DeliveryNotStarted(f"unable to read notification attachment: {source.name}") from exc
        if sha256_path(source) != record.get("sha256") or len(payload) != record.get("size_bytes"):
            raise _DeliveryNotStarted(f"notification attachment changed while composing: {source.name}")
        mime_type, _ = mimetypes.guess_type(source.name, strict=False)
        maintype, subtype = (mime_type or "application/octet-stream").split("/", 1)
        message.add_attachment(
            payload,
            maintype=maintype,
            subtype=subtype,
            filename=source.name,
        )

    client: smtplib.SMTP | smtplib.SMTP_SSL | None = None
    connected = False
    authenticated = False
    try:
        context = ssl.create_default_context()
        if config.smtp_security == "ssl":
            client = smtplib.SMTP_SSL(
                config.smtp_host,
                config.smtp_port,
                timeout=120,
                context=context,
            )
        else:
            client = smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=120)
            client.ehlo()
            client.starttls(context=context)
            client.ehlo()
        connected = True
        client.login(config.smtp_username, password)
        authenticated = True
        refused = client.send_message(message)
        if refused:
            raise _DeliveryNotStarted(
                "SMTP refused recipient(s): " + ", ".join(sorted(refused))
            )
        return "smtp message accepted"
    except _DeliveryNotStarted:
        raise
    except (smtplib.SMTPAuthenticationError, smtplib.SMTPRecipientsRefused) as exc:
        raise _DeliveryNotStarted(_smtp_exception_text(exc)) from exc
    except smtplib.SMTPResponseException as exc:
        raise _DeliveryNotStarted(_smtp_exception_text(exc)) from exc
    except (smtplib.SMTPServerDisconnected, TimeoutError, OSError) as exc:
        if connected and authenticated:
            raise _DeliveryAmbiguous(
                "SMTP connection ended before delivery was confirmed: "
                + _smtp_exception_text(exc)
            ) from exc
        raise _DeliveryNotStarted(_smtp_exception_text(exc)) from exc
    except smtplib.SMTPException as exc:
        if connected and authenticated:
            raise _DeliveryAmbiguous(_smtp_exception_text(exc)) from exc
        raise _DeliveryNotStarted(_smtp_exception_text(exc)) from exc
    finally:
        if client is not None:
            try:
                client.quit()
            except (OSError, smtplib.SMTPException):
                pass


def _smtp_password(config: EmailNotificationConfig) -> str:
    if config.smtp_password_env is not None:
        value = os.environ.get(config.smtp_password_env, "")
    elif config.smtp_password_file is not None:
        try:
            value = config.smtp_password_file.read_text(encoding="utf-8")
        except OSError as exc:
            raise _DeliveryNotStarted("SMTP password file is unavailable") from exc
    else:
        raise _DeliveryNotStarted("SMTP password source is not configured")
    value = value.strip()
    if not value:
        raise _DeliveryNotStarted("SMTP password source is empty")
    return value


def _smtp_exception_text(exc: BaseException) -> str:
    if isinstance(exc, smtplib.SMTPResponseException):
        detail = exc.smtp_error.decode("utf-8", "replace") if isinstance(exc.smtp_error, bytes) else str(exc.smtp_error)
        detail = " ".join(detail.split())
        return f"SMTP server returned {exc.smtp_code}: {detail[:500]}"
    detail = " ".join(str(exc).split())
    return detail[:500] or exc.__class__.__name__


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
        provider=str(receipt.get("provider", "clawemail")),
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
    provider: str,
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
        "provider": provider,
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
