"""Durable compute monitors for the App Server control plane.

Monitors observe an already-submitted calculation Attempt.  They never mutate
ResearchMap and never decide whether a calculation is scientifically valid.
The only side effect of a tick is a durable event and a delivery outbox row.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from ts_agent.io import now_iso, read_json, sha256_json, write_json
from ts_agent.path_safety import lexical_path, path_has_symlink


REGISTRATION_SCHEMA = "ts-compute-monitor/1"
EVENT_SCHEMA = "ts-compute-monitor-event/1"
DELIVERY_SCHEMA = "ts-monitor-delivery/1"
STATE_SCHEMA = "ts-compute-monitor-state/1"
TICK_SCHEMA = "ts-compute-monitor-tick/1"
MONITOR_ID = re.compile(r"^mon_[a-f0-9]{24}$")
EVENT_ID = re.compile(r"^evt_[a-f0-9]{32}$")
_WAKE_POLICIES = {"none", "next_run"}
_NOTIFY_POLICIES = {"none", "user"}
_OBSERVABLE_STATES = {"prepared", "running", "completed", "parsed", "failed", "stopped", "unknown"}


def register_monitor(
    root: str | Path,
    *,
    node_id: str,
    intent_id: str,
    intent_digest: str,
    session_id: str | None = None,
    wake_policy: str = "next_run",
    notify_policy: str = "none",
    monitor_id: str | None = None,
) -> dict[str, Any]:
    """Create or verify one idempotent monitor registration."""

    workspace = _workspace_root(root)
    if not _nonempty(node_id) or not _nonempty(intent_id):
        raise ValueError("monitor registration requires node_id and intent_id")
    if not re.fullmatch(r"calc_[1-9][0-9]*", intent_id):
        raise ValueError("monitor intent_id is invalid")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", intent_digest):
        raise ValueError("monitor intent_digest is invalid")
    if wake_policy not in _WAKE_POLICIES:
        raise ValueError("monitor wake_policy must be none or next_run")
    if notify_policy not in _NOTIFY_POLICIES:
        raise ValueError("monitor notify_policy must be none or user")
    if session_id is not None and not _nonempty(session_id):
        raise ValueError("monitor session_id must be a non-empty string")
    resolved_id = monitor_id or _monitor_id(intent_id, intent_digest)
    if not MONITOR_ID.fullmatch(resolved_id):
        raise ValueError("monitor_id is invalid")
    registration = {
        "schema_version": REGISTRATION_SCHEMA,
        "monitor_id": resolved_id,
        "workspace_id": _workspace_id(workspace),
        "node_id": node_id,
        "intent_id": intent_id,
        "intent_digest": intent_digest,
        "session_id": session_id,
        "wake_policy": wake_policy,
        "notify_policy": notify_policy,
        "enabled": True,
        "created_at": now_iso(),
    }
    path = _monitor_dir(workspace, resolved_id) / "registration.json"
    _ensure_monitor_base(workspace)
    if path.is_file():
        existing = _read_object(path, "monitor registration")
        comparable = {key: existing.get(key) for key in registration if key != "created_at"}
        expected = {key: registration[key] for key in registration if key != "created_at"}
        if comparable != expected:
            raise ValueError("monitor registration already exists with different binding")
        registration = existing
    else:
        _ensure_directory(_monitor_dir(workspace, resolved_id))
        write_json(path, registration)
    state_path = _monitor_dir(workspace, resolved_id) / "state.json"
    if not state_path.exists():
        write_json(state_path, {
            "schema_version": STATE_SCHEMA,
            "monitor_id": resolved_id,
            "last_state": None,
            "last_program_status": None,
            "last_status_digest": None,
            "last_event_id": None,
            "last_observed_at": None,
        })
    return {
        "schema_version": "ts-compute-monitor-registration/1",
        "monitor_id": resolved_id,
        "registration": registration,
        "state": _read_object(state_path, "monitor state"),
    }


def list_monitors(root: str | Path) -> list[dict[str, Any]]:
    workspace = _workspace_root(root)
    base = workspace / "operations" / "monitors"
    if path_has_symlink(base):
        raise ValueError("monitor records contain a symbolic link")
    if not base.exists():
        return []
    if not base.is_dir() or base.is_symlink():
        raise ValueError("monitor records must be a physical directory")
    rows: list[dict[str, Any]] = []
    for directory in sorted(base.iterdir(), key=lambda item: item.name):
        if not directory.is_dir() or directory.is_symlink() or not MONITOR_ID.fullmatch(directory.name):
            continue
        registration = directory / "registration.json"
        if registration.is_file() and not registration.is_symlink():
            rows.append(_read_object(registration, "monitor registration"))
    return rows


def tick_monitors(root: str | Path, *, observed_at: str | None = None) -> dict[str, Any]:
    """Poll all enabled monitors and append only meaningful state changes."""

    workspace = _workspace_root(root)
    tick_time = observed_at or now_iso()
    registrations = list_monitors(workspace)
    if not registrations:
        return {
            "schema_version": TICK_SCHEMA,
            "workspace_id": _workspace_id(workspace),
            "observed_at": tick_time,
            "monitors": [],
        }
    # Keep registration/listing dependency-neutral. Compute backends include
    # optional native packages (NumPy/RDKit) that are only needed while polling.
    from ts_agent.compute.control import calculation_status

    rows: list[dict[str, Any]] = []
    for registration in registrations:
        monitor_id = registration["monitor_id"]
        state_path = _monitor_dir(workspace, monitor_id) / "state.json"
        previous = _read_object(state_path, "monitor state")
        if registration.get("enabled") is not True:
            rows.append(_tick_row(registration, previous, previous.get("last_state"), changed=False))
            continue
        try:
            observed = calculation_status(
                workspace,
                registration["intent_id"],
                registration["intent_digest"],
            )
            current = _effective_state(workspace, registration, observed)
            error = None
        except Exception as exc:  # Unknown is an explicit state, never failed.
            observed = {}
            current = "unknown"
            error = str(exc)
        semantic = {
            "state": current,
            "program_status": observed.get("program_status"),
            "error_class": observed.get("error_class"),
            "job_id": observed.get("job_id"),
            "exit_status": observed.get("exit_status"),
            "error": error,
        }
        digest = sha256_json(semantic)
        changed = previous.get("last_status_digest") != digest
        event_id = previous.get("last_event_id")
        if changed:
            event_id = _event_id(monitor_id, digest)
            event = {
                "schema_version": EVENT_SCHEMA,
                "event_id": event_id,
                "monitor_id": monitor_id,
                "workspace_id": registration["workspace_id"],
                "node_id": registration["node_id"],
                "intent_id": registration["intent_id"],
                "intent_digest": registration["intent_digest"],
                "session_id": registration.get("session_id"),
                "wake_policy": registration["wake_policy"],
                "notify_policy": registration["notify_policy"],
                "previous_state": previous.get("last_state"),
                "state": current,
                "program_status": observed.get("program_status"),
                "job_id": observed.get("job_id"),
                "exit_status": observed.get("exit_status"),
                "error_class": observed.get("error_class"),
                "error": error,
                "observed_at": tick_time,
                "status": observed,
            }
            event_path = _monitor_dir(workspace, monitor_id) / "events" / f"{event_id}.json"
            _ensure_directory(event_path.parent)
            if not event_path.exists():
                write_json(event_path, event)
            delivery_path = _monitor_dir(workspace, monitor_id) / "deliveries" / f"{event_id}.json"
            _ensure_directory(delivery_path.parent)
            if not delivery_path.exists():
                write_json(delivery_path, {
                    "schema_version": DELIVERY_SCHEMA,
                    "event_id": event_id,
                    "monitor_id": monitor_id,
                    "session_id": registration.get("session_id"),
                    "wake_policy": registration["wake_policy"],
                    "notify_policy": registration["notify_policy"],
                    "status": "pending",
                    "attempts": 0,
                    "request_id": f"monitor:{event_id}",
                    "created_at": tick_time,
                    "claimed_at": None,
                    "delivered_at": None,
                    "last_error": None,
                })
            write_json(state_path, {
                "schema_version": STATE_SCHEMA,
                "monitor_id": monitor_id,
                "last_state": current,
                "last_program_status": observed.get("program_status"),
                "last_status_digest": digest,
                "last_event_id": event_id,
                "last_observed_at": tick_time,
            })
        rows.append(_tick_row(registration, previous, current, changed=changed, event_id=event_id, error=error))
    return {
        "schema_version": TICK_SCHEMA,
        "workspace_id": _workspace_id(workspace),
        "observed_at": tick_time,
        "monitors": rows,
    }


def list_pending_deliveries(root: str | Path) -> list[dict[str, Any]]:
    workspace = _workspace_root(root)
    rows: list[dict[str, Any]] = []
    for registration in list_monitors(workspace):
        directory = _monitor_dir(workspace, registration["monitor_id"]) / "deliveries"
        if not directory.is_dir() or directory.is_symlink():
            continue
        for path in sorted(directory.glob("evt_*.json"), key=lambda item: item.name):
            if path.is_file() and not path.is_symlink():
                delivery = _read_object(path, "monitor delivery")
                if delivery.get("status") in {"pending", "delivering"}:
                    rows.append(delivery)
    return rows


def claim_delivery(root: str | Path, event_id: str) -> dict[str, Any]:
    delivery_path = _find_delivery(root, event_id)
    delivery = _read_object(delivery_path, "monitor delivery")
    if delivery.get("status") == "delivered":
        return delivery
    if delivery.get("status") not in {"pending", "delivering"}:
        raise ValueError("monitor delivery is not claimable")
    delivery["status"] = "delivering"
    delivery["attempts"] = int(delivery.get("attempts") or 0) + 1
    delivery["claimed_at"] = now_iso()
    delivery["last_error"] = None
    write_json(delivery_path, delivery)
    return delivery


def complete_delivery(
    root: str | Path,
    event_id: str,
    *,
    delivered: bool,
    error: str | None = None,
) -> dict[str, Any]:
    delivery_path = _find_delivery(root, event_id)
    delivery = _read_object(delivery_path, "monitor delivery")
    delivery["status"] = "delivered" if delivered else "pending"
    delivery["delivered_at"] = now_iso() if delivered else None
    delivery["last_error"] = None if delivered else (error or "delivery failed")
    write_json(delivery_path, delivery)
    return delivery


def read_event(root: str | Path, event_id: str) -> dict[str, Any]:
    return _read_object(_find_event(root, event_id), "monitor event")


def _effective_state(workspace: Path, registration: dict[str, Any], observed: dict[str, Any]) -> str:
    if observed.get("state") == "completed":
        for row in _attempt_rows(workspace, registration["intent_id"]):
            if row.get("intent_id") == registration["intent_id"] and row.get("state") == "parsed":
                return "parsed"
    state = observed.get("state")
    return state if state in _OBSERVABLE_STATES else "unknown"


def _attempt_rows(workspace: Path, intent_id: str) -> list[dict[str, Any]]:
    from .operational import calculation_attempt_index

    return [row for row in calculation_attempt_index(workspace) if row.get("intent_id") == intent_id]


def _tick_row(registration: dict[str, Any], previous: dict[str, Any], current: Any, *, changed: bool, event_id: str | None = None, error: str | None = None) -> dict[str, Any]:
    return {
        "monitor_id": registration["monitor_id"],
        "intent_id": registration["intent_id"],
        "previous_state": previous.get("last_state"),
        "state": current,
        "changed": changed,
        "event_id": event_id,
        "error": error,
    }


def _workspace_root(root: str | Path) -> Path:
    workspace = lexical_path(root)
    if path_has_symlink(workspace) or not (workspace / "workspace.json").is_file():
        raise ValueError("monitor operations require an initialized TS workspace")
    return workspace


def _workspace_id(workspace: Path) -> str:
    try:
        value = read_json(workspace / "workspace.json")
    except Exception as exc:
        raise ValueError(f"workspace identity is unreadable: {exc}") from exc
    workspace_id = value.get("workspace_id") if isinstance(value, dict) else None
    if not isinstance(workspace_id, str) or not workspace_id:
        raise ValueError("workspace identity is invalid")
    return workspace_id


def _monitor_id(intent_id: str, intent_digest: str) -> str:
    return "mon_" + hashlib.sha256(f"{intent_id}:{intent_digest}".encode()).hexdigest()[:24]


def _event_id(monitor_id: str, digest: str) -> str:
    return "evt_" + hashlib.sha256(f"{monitor_id}:{digest}".encode()).hexdigest()[:32]


def _monitor_dir(workspace: Path, monitor_id: str) -> Path:
    if not MONITOR_ID.fullmatch(monitor_id):
        raise ValueError("monitor_id is invalid")
    return workspace / "operations" / "monitors" / monitor_id


def _ensure_monitor_base(workspace: Path) -> Path:
    operations = workspace / "operations"
    if path_has_symlink(operations) or (operations.exists() and not operations.is_dir()):
        raise ValueError("workspace operations path must be a physical directory")
    operations.mkdir(parents=True, exist_ok=True)
    base = operations / "monitors"
    if path_has_symlink(base) or (base.exists() and not base.is_dir()):
        raise ValueError("monitor records path must be a physical directory")
    base.mkdir(exist_ok=True)
    return base


def _ensure_directory(path: Path) -> None:
    if path_has_symlink(path) or (path.exists() and not path.is_dir()):
        raise ValueError("monitor record path must be a physical directory")
    path.mkdir(parents=True, exist_ok=True)


def _find_delivery(root: str | Path, event_id: str) -> Path:
    if not EVENT_ID.fullmatch(event_id):
        raise ValueError("event_id is invalid")
    workspace = _workspace_root(root)
    for registration in list_monitors(workspace):
        path = _monitor_dir(workspace, registration["monitor_id"]) / "deliveries" / f"{event_id}.json"
        if path.is_file() and not path.is_symlink():
            return path
    raise ValueError(f"monitor event does not exist: {event_id}")


def _find_event(root: str | Path, event_id: str) -> Path:
    if not EVENT_ID.fullmatch(event_id):
        raise ValueError("event_id is invalid")
    workspace = _workspace_root(root)
    for registration in list_monitors(workspace):
        path = _monitor_dir(workspace, registration["monitor_id"]) / "events" / f"{event_id}.json"
        if path.is_file() and not path.is_symlink():
            return path
    raise ValueError(f"monitor event does not exist: {event_id}")


def _read_object(path: Path, label: str) -> dict[str, Any]:
    value = read_json(path)
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain an object")
    return value


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())
