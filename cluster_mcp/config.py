"""TOML configuration loading with explicit, portable defaults."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 compatibility
    import tomli as tomllib

from .errors import ConfigurationError


@dataclass(frozen=True)
class CommandSettings:
    qstat: str = "/opt/pbs/bin/qstat"
    qsub: str = "/opt/pbs/bin/qsub"
    qdel: str = "/opt/pbs/bin/qdel"
    qhold: str = "/opt/pbs/bin/qhold"
    qrls: str = "/opt/pbs/bin/qrls"
    qalter: str = "/opt/pbs/bin/qalter"
    pbsnodes: str = "/opt/pbs/bin/pbsnodes"

    def as_dict(self) -> dict[str, str]:
        return {
            "qstat": self.qstat,
            "qsub": self.qsub,
            "qdel": self.qdel,
            "qhold": self.qhold,
            "qrls": self.qrls,
            "qalter": self.qalter,
            "pbsnodes": self.pbsnodes,
        }


@dataclass(frozen=True)
class SchedulerSettings:
    backend: str = "openpbs"
    allowed_queues: tuple[str, ...] = ("amd192q", "gpuq")
    gpu_queues: tuple[str, ...] = ("gpuq",)
    max_nodes: int = 1
    allow_other_users: bool = False
    allow_submission: bool = True
    allow_job_control: bool = True
    require_gpu_devices: bool = True
    command_timeout_seconds: int = 30
    max_command_output_bytes: int = 16 * 1024 * 1024
    commands: CommandSettings = field(default_factory=CommandSettings)


@dataclass(frozen=True)
class WorkspaceSettings:
    root: Path
    max_upload_bytes: int = 20 * 1024 * 1024 * 1024
    max_chunk_bytes: int = 4 * 1024 * 1024
    max_listing_entries: int = 2000
    min_free_bytes: int = 1024 * 1024 * 1024
    upload_expiry_hours: int = 24


@dataclass(frozen=True)
class AuditSettings:
    enabled: bool
    path: Path


@dataclass(frozen=True)
class AuthSettings:
    required: bool
    principals_file: Path | None


@dataclass(frozen=True)
class HTTPSettings:
    host: str = "127.0.0.1"
    port: int = 8765
    path: str = "/mcp"
    public_url: str = "http://127.0.0.1:8765/mcp"
    principal: str | None = None
    token_env_var: str = "CLUSTER_MCP_HTTP_TOKEN"  # noqa: S105 - variable name, not a secret
    allowed_client_networks: tuple[str, ...] = ("127.0.0.1/32", "::1/128")
    tls_cert_file: Path | None = None
    tls_key_file: Path | None = None
    stateless: bool = True
    json_response: bool = True


@dataclass(frozen=True)
class SoftwareProfile:
    name: str
    description: str
    command: tuple[str, ...]
    activation_script: Path | None
    default_queue: str
    allowed_queues: tuple[str, ...]
    requires_gpu: bool = False
    environment: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class AppConfig:
    source_path: Path
    workspace: WorkspaceSettings
    scheduler: SchedulerSettings
    audit: AuditSettings
    auth: AuthSettings
    http: HTTPSettings
    software: dict[str, SoftwareProfile]


def _absolute_path(value: str, *, base: Path) -> Path:
    expanded = Path(os.path.expandvars(os.path.expanduser(value)))
    if not expanded.is_absolute():
        expanded = base / expanded
    return expanded.resolve(strict=False)


def _require_mapping(value: Any, name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigurationError(f"{name} must be a TOML table")
    return value


def _string_tuple(
    value: Any,
    *,
    name: str,
    default: tuple[str, ...],
    allow_empty: bool = False,
) -> tuple[str, ...]:
    if value is None:
        return default
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ConfigurationError(f"{name} must be a non-empty string array")
    result = tuple(dict.fromkeys(value))
    if not result and not allow_empty:
        raise ConfigurationError(f"{name} may not be empty")
    return result


def _positive_int(value: Any, *, name: str, default: int, allow_zero: bool = False) -> int:
    if value is None:
        return default
    minimum = 0 if allow_zero else 1
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        qualifier = "non-negative" if allow_zero else "positive"
        raise ConfigurationError(f"{name} must be a {qualifier} integer")
    return value


def _bool(value: Any, *, name: str, default: bool) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ConfigurationError(f"{name} must be true or false")
    return value


def load_config(path: str | Path) -> AppConfig:
    source_path = Path(path).expanduser().resolve(strict=True)
    with source_path.open("rb") as handle:
        raw = tomllib.load(handle)
    base = source_path.parent

    workspace_raw = _require_mapping(raw.get("workspace"), "workspace")
    root_value = workspace_raw.get("root", "./workspace")
    if not isinstance(root_value, str) or not root_value:
        raise ConfigurationError("workspace.root must be a path string")
    workspace = WorkspaceSettings(
        root=_absolute_path(root_value, base=base),
        max_upload_bytes=_positive_int(
            workspace_raw.get("max_upload_bytes"),
            name="workspace.max_upload_bytes",
            default=20 * 1024 * 1024 * 1024,
        ),
        max_chunk_bytes=_positive_int(
            workspace_raw.get("max_chunk_bytes"),
            name="workspace.max_chunk_bytes",
            default=4 * 1024 * 1024,
        ),
        max_listing_entries=_positive_int(
            workspace_raw.get("max_listing_entries"),
            name="workspace.max_listing_entries",
            default=2000,
        ),
        min_free_bytes=_positive_int(
            workspace_raw.get("min_free_bytes"),
            name="workspace.min_free_bytes",
            default=1024 * 1024 * 1024,
            allow_zero=True,
        ),
        upload_expiry_hours=_positive_int(
            workspace_raw.get("upload_expiry_hours"),
            name="workspace.upload_expiry_hours",
            default=24,
        ),
    )
    if workspace.max_chunk_bytes > workspace.max_upload_bytes:
        raise ConfigurationError("workspace.max_chunk_bytes may not exceed max_upload_bytes")

    scheduler_raw = _require_mapping(raw.get("scheduler"), "scheduler")
    commands_raw = _require_mapping(scheduler_raw.get("commands"), "scheduler.commands")
    command_defaults = CommandSettings()
    command_values: dict[str, str] = {}
    for name, default in command_defaults.as_dict().items():
        value = commands_raw.get(name, default)
        if not isinstance(value, str) or not value:
            raise ConfigurationError(f"scheduler.commands.{name} must be a path string")
        command_values[name] = value
    allowed_queues = _string_tuple(
        scheduler_raw.get("allowed_queues"),
        name="scheduler.allowed_queues",
        default=("amd192q", "gpuq"),
    )
    gpu_queues = _string_tuple(
        scheduler_raw.get("gpu_queues"),
        name="scheduler.gpu_queues",
        default=("gpuq",),
        allow_empty=True,
    )
    if not set(gpu_queues).issubset(allowed_queues):
        raise ConfigurationError("scheduler.gpu_queues must be a subset of allowed_queues")
    backend = scheduler_raw.get("backend", "openpbs")
    if backend not in {"openpbs", "torque"}:
        raise ConfigurationError("scheduler.backend must be openpbs or torque")
    scheduler = SchedulerSettings(
        backend=backend,
        allowed_queues=allowed_queues,
        gpu_queues=gpu_queues,
        max_nodes=_positive_int(
            scheduler_raw.get("max_nodes"), name="scheduler.max_nodes", default=1
        ),
        allow_other_users=_bool(
            scheduler_raw.get("allow_other_users"),
            name="scheduler.allow_other_users",
            default=False,
        ),
        allow_submission=_bool(
            scheduler_raw.get("allow_submission"),
            name="scheduler.allow_submission",
            default=True,
        ),
        allow_job_control=_bool(
            scheduler_raw.get("allow_job_control"),
            name="scheduler.allow_job_control",
            default=True,
        ),
        require_gpu_devices=_bool(
            scheduler_raw.get("require_gpu_devices"),
            name="scheduler.require_gpu_devices",
            default=True,
        ),
        command_timeout_seconds=_positive_int(
            scheduler_raw.get("command_timeout_seconds"),
            name="scheduler.command_timeout_seconds",
            default=30,
        ),
        max_command_output_bytes=_positive_int(
            scheduler_raw.get("max_command_output_bytes"),
            name="scheduler.max_command_output_bytes",
            default=16 * 1024 * 1024,
        ),
        commands=CommandSettings(**command_values),
    )

    audit_raw = _require_mapping(raw.get("audit"), "audit")
    audit_path = audit_raw.get("path", "./workspace/.cluster_mcp/audit.jsonl")
    if not isinstance(audit_path, str) or not audit_path:
        raise ConfigurationError("audit.path must be a path string")
    audit = AuditSettings(
        enabled=_bool(audit_raw.get("enabled"), name="audit.enabled", default=True),
        path=_absolute_path(audit_path, base=base),
    )

    auth_raw = _require_mapping(raw.get("auth"), "auth")
    auth_required = _bool(auth_raw.get("required"), name="auth.required", default=False)
    principals_file_value = auth_raw.get("principals_file")
    if principals_file_value is None:
        principals_file = _absolute_path("./auth.toml", base=base) if auth_required else None
    elif not isinstance(principals_file_value, str) or not principals_file_value:
        raise ConfigurationError("auth.principals_file must be a path string")
    else:
        principals_file = _absolute_path(principals_file_value, base=base)
    auth = AuthSettings(required=auth_required, principals_file=principals_file)

    http_raw = _require_mapping(raw.get("http"), "http")
    http_host = http_raw.get("host", "127.0.0.1")
    if (
        not isinstance(http_host, str)
        or not http_host
        or any(character.isspace() for character in http_host)
        or any(character in "/?#\x00" for character in http_host)
    ):
        raise ConfigurationError("http.host must be a hostname or IP address")
    http_port = _positive_int(http_raw.get("port"), name="http.port", default=8765)
    if http_port > 65535:
        raise ConfigurationError("http.port must not exceed 65535")
    http_path = http_raw.get("path", "/mcp")
    if (
        not isinstance(http_path, str)
        or not http_path.startswith("/")
        or any(character in "?#\x00" for character in http_path)
    ):
        raise ConfigurationError("http.path must be an absolute URL path")
    tls_cert_value = http_raw.get("tls_cert_file")
    tls_key_value = http_raw.get("tls_key_file")
    if (tls_cert_value is None) != (tls_key_value is None):
        raise ConfigurationError("http.tls_cert_file and http.tls_key_file must be set together")
    if tls_cert_value is not None and (not isinstance(tls_cert_value, str) or not tls_cert_value):
        raise ConfigurationError("http.tls_cert_file must be a path string")
    if tls_key_value is not None and (not isinstance(tls_key_value, str) or not tls_key_value):
        raise ConfigurationError("http.tls_key_file must be a path string")
    scheme = "https" if tls_cert_value is not None else "http"
    default_url_host = f"[{http_host}]" if ":" in http_host else http_host
    public_url = http_raw.get("public_url", f"{scheme}://{default_url_host}:{http_port}{http_path}")
    if not isinstance(public_url, str) or not public_url:
        raise ConfigurationError("http.public_url must be an absolute HTTP(S) URL")
    http_principal = http_raw.get("principal")
    if http_principal is not None and (
        not isinstance(http_principal, str)
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", http_principal) is None
    ):
        raise ConfigurationError("http.principal is invalid")
    token_env_var = http_raw.get("token_env_var", "CLUSTER_MCP_HTTP_TOKEN")
    if (
        not isinstance(token_env_var, str)
        or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", token_env_var) is None
    ):
        raise ConfigurationError("http.token_env_var must be an environment variable name")
    http = HTTPSettings(
        host=http_host,
        port=http_port,
        path=http_path,
        public_url=public_url,
        principal=http_principal,
        token_env_var=token_env_var,
        allowed_client_networks=_string_tuple(
            http_raw.get("allowed_client_networks"),
            name="http.allowed_client_networks",
            default=("127.0.0.1/32", "::1/128"),
            allow_empty=True,
        ),
        tls_cert_file=(
            _absolute_path(tls_cert_value, base=base) if tls_cert_value is not None else None
        ),
        tls_key_file=(
            _absolute_path(tls_key_value, base=base) if tls_key_value is not None else None
        ),
        stateless=_bool(http_raw.get("stateless"), name="http.stateless", default=True),
        json_response=_bool(http_raw.get("json_response"), name="http.json_response", default=True),
    )

    software_raw = _require_mapping(raw.get("software"), "software")
    software: dict[str, SoftwareProfile] = {}
    for profile_name, profile_value in software_raw.items():
        profile_raw = _require_mapping(profile_value, f"software.{profile_name}")
        command = profile_raw.get("command")
        if (
            not isinstance(command, list)
            or not command
            or not all(isinstance(item, str) and item and "\x00" not in item for item in command)
        ):
            raise ConfigurationError(
                f"software.{profile_name}.command must be a non-empty string array"
            )
        activation_value = profile_raw.get("activation_script")
        if activation_value is not None and not isinstance(activation_value, str):
            raise ConfigurationError(
                f"software.{profile_name}.activation_script must be a path string"
            )
        default_queue = profile_raw.get("default_queue")
        if not isinstance(default_queue, str) or default_queue not in scheduler.allowed_queues:
            raise ConfigurationError(
                f"software.{profile_name}.default_queue must be one of the scheduler allowed queues"
            )
        profile_queues = _string_tuple(
            profile_raw.get("allowed_queues"),
            name=f"software.{profile_name}.allowed_queues",
            default=(default_queue,),
        )
        if not set(profile_queues).issubset(scheduler.allowed_queues):
            raise ConfigurationError(
                f"software.{profile_name}.allowed_queues must be a subset of "
                "scheduler.allowed_queues"
            )
        environment_raw = _require_mapping(
            profile_raw.get("environment"), f"software.{profile_name}.environment"
        )
        if not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in environment_raw.items()
        ):
            raise ConfigurationError(
                f"software.{profile_name}.environment must contain string values"
            )
        software[profile_name] = SoftwareProfile(
            name=profile_name,
            description=str(profile_raw.get("description", "")),
            command=tuple(command),
            activation_script=(
                _absolute_path(activation_value, base=base)
                if activation_value is not None
                else None
            ),
            default_queue=default_queue,
            allowed_queues=profile_queues,
            requires_gpu=_bool(
                profile_raw.get("requires_gpu"),
                name=f"software.{profile_name}.requires_gpu",
                default=False,
            ),
            environment=dict(environment_raw),
        )

    return AppConfig(
        source_path=source_path,
        workspace=workspace,
        scheduler=scheduler,
        audit=audit,
        auth=auth,
        http=http,
        software=software,
    )
