"""Append-only local audit events without payload or secret logging."""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class AuditLogger:
    def __init__(
        self,
        *,
        enabled: bool,
        path: Path,
        actor: str,
        principal: str,
        auth_method: str,
        session_id: str,
    ) -> None:
        self.enabled = enabled
        self.path = path
        self.actor = actor
        self.principal = principal
        self.auth_method = auth_method
        self.session_id = session_id
        self._lock = threading.Lock()

    def write(self, action: str, *, success: bool, details: dict[str, Any] | None = None) -> None:
        if not self.enabled:
            return
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "actor": self.actor,
            "principal": self.principal,
            "auth_method": self.auth_method,
            "session_id": self.session_id,
            "action": action,
            "success": success,
            "details": details or {},
        }
        encoded = (json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
        with self._lock:
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            descriptor = os.open(self.path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
            try:
                os.write(descriptor, encoded)
            finally:
                os.close(descriptor)
