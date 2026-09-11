"""Thin client for the TSPi JSON-lines projection provider."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, Sequence


class ProviderClientError(RuntimeError):
    """The core provider returned an invalid or failed response."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class ProviderClient:
    """Call the core provider without importing any TSPi private module."""

    def __init__(
        self,
        command: str | Path | Sequence[str],
        state_dir: str | Path,
        *,
        workspace_roots: Sequence[str | Path] | None = None,
        timeout: float = 20.0,
    ) -> None:
        if timeout <= 0:
            raise ValueError("provider timeout must be positive")
        self.command = _command(command)
        self.state_dir = Path(state_dir).expanduser()
        self.workspace_roots = tuple(Path(root).expanduser() for root in (workspace_roots or ()))
        self.timeout = timeout

    def request(
        self,
        operation: str,
        *,
        workspace_id: str | None = None,
        route: str | None = None,
        query: dict[str, str] | None = None,
    ) -> Any:
        request = {
            "schema_version": "ts-web-provider-request/1",
            "request_id": uuid.uuid4().hex,
            "operation": operation,
            "workspace_id": workspace_id,
            "route": route,
            "query": query or {},
        }
        command = [*self.command, "--state-dir", str(self.state_dir)]
        for root in self.workspace_roots:
            command.extend(("--workspace-root", str(root)))
        try:
            completed = subprocess.run(
                command,
                input=json.dumps(request, ensure_ascii=False) + "\n",
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
        except subprocess.TimeoutExpired as error:
            raise ProviderClientError("projection provider timed out", retryable=True) from error
        except OSError as error:
            raise ProviderClientError("projection provider is unavailable", retryable=True) from error
        if completed.returncode != 0:
            raise ProviderClientError("projection provider failed", retryable=True)
        lines = [line for line in completed.stdout.splitlines() if line.strip()]
        if len(lines) != 1:
            raise ProviderClientError("projection provider returned an invalid response", retryable=True)
        try:
            response = json.loads(lines[0])
        except json.JSONDecodeError as error:
            raise ProviderClientError("projection provider returned invalid JSON", retryable=True) from error
        if not isinstance(response, dict) or response.get("schema_version") != "ts-web-provider/1":
            raise ProviderClientError("projection provider protocol version is incompatible")
        if response.get("request_id") != request["request_id"]:
            raise ProviderClientError("projection provider response identity is invalid")
        if response.get("ok") is True:
            return response.get("payload")
        error = response.get("error") if isinstance(response.get("error"), dict) else {}
        message = error.get("error") if isinstance(error.get("error"), str) else "projection provider rejected the request"
        raise ProviderClientError(message, retryable=error.get("retryable") is True)

    def register(self, source_roots: Sequence[str | Path], labels: Sequence[str] | None = None) -> Any:
        labels = tuple(labels or ())
        command = [*self.command, "--state-dir", str(self.state_dir), "--register"]
        for root in source_roots:
            command.extend(("--source-root", str(root)))
        for label in labels:
            command.extend(("--label", label))
        try:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=self.timeout, check=False)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ProviderClientError("projection provider registration is unavailable", retryable=True) from error
        if completed.returncode != 0:
            raise ProviderClientError("projection provider registration failed")
        try:
            return json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            raise ProviderClientError("projection provider registration returned invalid JSON") from error


def _command(value: str | Path | Sequence[str]) -> list[str]:
    if isinstance(value, (str, Path)):
        path = str(value)
        return [sys.executable, path] if path.endswith(".py") else [path]
    command = [str(item) for item in value]
    if not command:
        raise ValueError("provider command cannot be empty")
    return command
