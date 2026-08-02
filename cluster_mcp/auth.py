"""Per-client authentication context and fail-closed scope authorization."""

from __future__ import annotations

import os
import re
import stat
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 compatibility
    import tomli as tomllib

from .config import AuthSettings
from .errors import ConfigurationError, SecurityError

PRINCIPAL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
VALID_SCOPES = frozenset(
    {
        "cluster:read",
        "jobs:read:own",
        "jobs:read",
        "jobs:submit",
        "jobs:control:own",
        "jobs:control",
        "files:read",
        "files:write",
        "files:overwrite",
        "ts:read",
        "ts:submit",
        "ts:control",
        "admin",
    }
)
LEGACY_SCOPES = frozenset(
    {
        "cluster:read",
        "jobs:read:own",
        "jobs:read",
        "jobs:submit",
        "jobs:control:own",
        "jobs:control",
        "files:read",
        "files:write",
    }
)
AUTH_METHODS = frozenset({"none", "local", "ssh-key", "oauth", "http-bearer"})


@dataclass(frozen=True)
class Principal:
    name: str
    enabled: bool
    scopes: frozenset[str]
    workspace_prefix: Path | None


@dataclass(frozen=True)
class AuthContext:
    principal: str
    auth_method: str
    session_id: str
    system: bool = False


class AuthRegistry:
    """Reload the principal registry at every authorization decision."""

    def __init__(self, settings: AuthSettings, workspace_root: Path) -> None:
        self.settings = settings
        self.workspace_root = workspace_root.resolve(strict=False)

    def _read_registry(self) -> dict[str, Principal]:
        path = self.settings.principals_file
        if path is None:
            return {}
        try:
            metadata = path.lstat()
        except FileNotFoundError as exc:
            if self.settings.required:
                raise ConfigurationError("Authentication configuration is unavailable") from exc
            return {}
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise ConfigurationError("Authentication configuration must be a regular file")
        if metadata.st_uid != os.geteuid():
            raise ConfigurationError(
                "Authentication configuration must be owned by the server user"
            )
        if stat.S_IMODE(metadata.st_mode) & 0o077:
            raise ConfigurationError("Authentication configuration permissions must be 0600")

        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(path, flags)
        try:
            with os.fdopen(descriptor, "rb", closefd=False) as handle:
                raw = tomllib.load(handle)
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise ConfigurationError("Authentication configuration is unreadable") from exc
        finally:
            os.close(descriptor)
        if not isinstance(raw, dict):
            raise ConfigurationError("Authentication configuration must be a TOML document")
        principals_raw = raw.get("principals", {})
        if not isinstance(principals_raw, dict) or not principals_raw:
            raise ConfigurationError("Authentication configuration needs at least one principal")

        principals: dict[str, Principal] = {}
        prefixes: list[tuple[str, Path]] = []
        for name, value in principals_raw.items():
            if not isinstance(name, str) or not PRINCIPAL_PATTERN.fullmatch(name):
                raise ConfigurationError("Authentication configuration has an invalid principal")
            if not isinstance(value, dict):
                raise ConfigurationError(f"Principal {name!r} must be a TOML table")
            enabled = value.get("enabled", True)
            if not isinstance(enabled, bool):
                raise ConfigurationError(f"Principal {name!r} enabled must be true or false")
            scopes_value = value.get("scopes")
            if (
                not isinstance(scopes_value, list)
                or not scopes_value
                or not all(isinstance(scope, str) and scope for scope in scopes_value)
            ):
                raise ConfigurationError(f"Principal {name!r} scopes must be a non-empty array")
            scopes = frozenset(scopes_value)
            unknown_scopes = scopes - VALID_SCOPES
            if unknown_scopes:
                raise ConfigurationError(
                    f"Principal {name!r} has unsupported scopes: "
                    f"{', '.join(sorted(unknown_scopes))}"
                )
            prefix_value = value.get("workspace_prefix")
            if not isinstance(prefix_value, str) or not prefix_value:
                raise ConfigurationError(f"Principal {name!r} needs workspace_prefix")
            prefix = self._validate_prefix(prefix_value, principal=name)
            principals[name] = Principal(
                name=name,
                enabled=enabled,
                scopes=scopes,
                workspace_prefix=prefix,
            )
            prefixes.append((name, (self.workspace_root / prefix).resolve(strict=False)))

        for index, (name, prefix) in enumerate(prefixes):
            for other_name, other_prefix in prefixes[index + 1 :]:
                if (
                    prefix == other_prefix
                    or prefix in other_prefix.parents
                    or other_prefix in prefix.parents
                ):
                    raise ConfigurationError(
                        f"Principal workspace prefixes overlap: {name!r} and {other_name!r}"
                    )
        return principals

    def _validate_prefix(self, value: str, *, principal: str) -> Path:
        prefix = Path(value)
        if prefix.is_absolute() or any(part in {"", ".", ".."} for part in prefix.parts):
            raise ConfigurationError(f"Principal {principal!r} workspace_prefix is unsafe")
        if prefix.parts and prefix.parts[0] == ".cluster_mcp":
            raise ConfigurationError(f"Principal {principal!r} workspace_prefix is reserved")
        resolved = (self.workspace_root / prefix).resolve(strict=False)
        try:
            resolved.relative_to(self.workspace_root)
        except ValueError as exc:
            raise ConfigurationError(
                f"Principal {principal!r} workspace_prefix leaves the workspace"
            ) from exc
        return prefix

    def authenticate(
        self,
        principal: str | None,
        *,
        auth_method: str,
        system: bool = False,
    ) -> AuthContext:
        if auth_method not in AUTH_METHODS:
            raise ConfigurationError("Unsupported authentication method")
        if system:
            self.validate()
            return AuthContext(
                principal="health-check",
                auth_method="local",
                session_id=uuid.uuid4().hex,
                system=True,
            )
        if principal is None and not self.settings.required:
            return AuthContext(
                principal="local-legacy",
                auth_method="none",
                session_id=uuid.uuid4().hex,
            )
        if principal is None or not PRINCIPAL_PATTERN.fullmatch(principal):
            raise SecurityError("Client authentication failed")
        selected = self._read_registry().get(principal)
        if selected is None or not selected.enabled:
            raise SecurityError("Client authentication failed")
        if self.settings.required and auth_method == "none":
            raise SecurityError("Client authentication failed")
        return AuthContext(
            principal=selected.name,
            auth_method=auth_method,
            session_id=uuid.uuid4().hex,
        )

    def validate(self) -> None:
        if self.settings.required or self.settings.principals_file is not None:
            self._read_registry()

    def current(self, context: AuthContext) -> Principal:
        if context.system:
            return Principal(
                name=context.principal,
                enabled=True,
                scopes=VALID_SCOPES,
                workspace_prefix=None,
            )
        if context.principal == "local-legacy" and not self.settings.required:
            return Principal(
                name=context.principal,
                enabled=True,
                scopes=LEGACY_SCOPES,
                workspace_prefix=None,
            )
        selected = self._read_registry().get(context.principal)
        if selected is None or not selected.enabled:
            raise SecurityError("Client authentication is no longer valid")
        return selected

    def require_any(self, context: AuthContext, *required_scopes: str) -> Principal:
        principal = self.current(context)
        if not principal.scopes.intersection(required_scopes):
            raise SecurityError("Client is not authorized for this operation")
        return principal

    def details(self, context: AuthContext) -> dict[str, Any]:
        principal = self.current(context)
        return {
            "required": self.settings.required,
            "principal": principal.name,
            "auth_method": context.auth_method,
            "audit_context_id": context.session_id,
            "scopes": sorted(principal.scopes),
        }
