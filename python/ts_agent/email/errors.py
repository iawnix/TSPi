"""Structured notification failures shared by the CLI and host adapter."""

from __future__ import annotations

from typing import Any


ERROR_SCHEMA = "ts-user-notification-error/1"


class NotificationError(ValueError):
    """A notification failure with explicit side-effect and retry semantics."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        error_class: str,
        state: str,
        retry_disposition: str,
        receipt_ref: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.error_class = error_class
        self.state = state
        self.retry_disposition = retry_disposition
        self.receipt_ref = receipt_ref

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": ERROR_SCHEMA,
            "ok": False,
            "state": self.state,
            "retry_disposition": self.retry_disposition,
            "receipt_ref": self.receipt_ref,
            "error": {
                "code": self.code,
                "class": self.error_class,
                "message": _message(self),
            },
        }


def notification_error_payload(exc: BaseException) -> dict[str, Any]:
    if isinstance(exc, NotificationError):
        return exc.to_payload()
    return {
        "schema_version": ERROR_SCHEMA,
        "ok": False,
        "state": "rejected",
        "retry_disposition": "fix_request",
        "receipt_ref": None,
        "error": {
            "code": "NOTIFICATION_REQUEST_REJECTED",
            "class": exc.__class__.__name__,
            "message": _message(exc),
        },
    }


def _message(exc: BaseException) -> str:
    value = str(exc).strip() or exc.__class__.__name__
    return value[:2000]
