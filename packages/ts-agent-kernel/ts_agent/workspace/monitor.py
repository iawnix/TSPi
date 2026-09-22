"""Durable compute monitors for the Host control plane.

Monitors observe an already-submitted calculation Attempt.  They never mutate
ResearchMap and never decide whether a calculation is scientifically valid.
The only side effect of a tick is a durable event and a delivery outbox row.
"""

from __future__ import annotations

import hashlib
import fcntl
import os
import re
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
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
_OBSERVABLE_STATES = {"prepared", "submitted", "queued", "running", "completed", "parsed", "failed", "stopped", "unknown"}
_CHANNELS = ("wake", "notify")
_LEASE_SECONDS = 180


@contextmanager
def _monitor_lock(workspace: Path):
    base = _ensure_monitor_base(workspace)
    descriptor = os.open(base / ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


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
    with _monitor_lock(workspace):
        return _register_monitor(workspace, node_id=node_id, intent_id=intent_id, intent_digest=intent_digest,
                                 session_id=session_id, wake_policy=wake_policy, notify_policy=notify_policy,
                                 monitor_id=monitor_id)


def _register_monitor(workspace: Path, *, node_id: str, intent_id: str, intent_digest: str,
                      session_id: str | None = None, wake_policy: str = "next_run",
                      notify_policy: str = "none", monitor_id: str | None = None) -> dict[str, Any]:
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
        comparable = {key: existing.get(key) for key in registration if key not in {"created_at", "enabled"}}
        expected = {key: registration[key] for key in registration if key not in {"created_at", "enabled"}}
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
            "last_changed_at": None,
            "last_sequence": 0,
            "last_error": None,
        })
    return {
        "schema_version": "ts-compute-monitor-registration/1",
        "monitor_id": resolved_id,
        "registration": registration,
        "state": _read_object(state_path, "monitor state"),
    }


def stage_registration(root: str | Path, **binding: Any) -> dict[str, Any]:
    """Persist the wake binding BEFORE submission, so a later tick can finish registration."""
    workspace = _workspace_root(root)
    node_id, intent_id, digest = binding.get("node_id"), binding.get("intent_id"), binding.get("intent_digest")
    if not isinstance(node_id, str) or not re.fullmatch(r"node_[1-9][0-9]*", node_id):
        raise ValueError("monitor node_id is invalid")
    if not isinstance(intent_id, str) or not re.fullmatch(r"calc_[1-9][0-9]*", intent_id):
        raise ValueError("monitor intent_id is invalid")
    if not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ValueError("monitor intent_digest is invalid")
    if not _nonempty(binding.get("session_id")):
        raise ValueError("automatic monitor registration requires the owning session_id")
    monitor_id = _monitor_id(intent_id, digest)
    with _monitor_lock(workspace):
        directory = workspace / "operations" / "monitors" / "pending_registrations"
        _ensure_directory(directory)
        path = directory / f"{monitor_id}.json"
        if path.exists():
            previous = _read_object(path, "pending monitor registration")
            if previous["binding"] != binding:
                raise ValueError("pending monitor already belongs to another session or intent")
            return previous
        record = {"monitor_id": monitor_id, "binding": binding, "status": "waiting_submission",
                  "created_at": now_iso(), "last_error": None, "attempts": 0, "next_attempt_at": None}
        write_json(path, record)
        return record


def _pending_registrations(workspace: Path) -> list[tuple[Path, dict[str, Any]]]:
    directory = workspace / "operations" / "monitors" / "pending_registrations"
    if path_has_symlink(directory):
        raise ValueError("pending monitor registration path contains a symbolic link")
    return [(path, _read_object(path, "pending monitor registration")) for path in sorted(directory.glob("mon_*.json"))]


def reconcile_registrations(root: str | Path, *, force: bool = False, at: str | None = None) -> dict[str, Any]:
    workspace = _workspace_root(root)
    rows = []
    timestamp = at or now_iso()
    for path, record in _pending_registrations(workspace):
        if record["status"] == "registered":
            continue
        if not force and _timestamp(record.get("next_attempt_at")) > _timestamp(timestamp):
            rows.append(record)
            continue
        try:
            # Use the same verified intent/receipt binding as submission, never
            # infer scheduler acceptance from an unbound file or from the model.
            from ts_agent.compute.control import _load_prepared, _read_control_result, _read_control_guard
            binding = record["binding"]
            _, intent, _ = _load_prepared(workspace, binding["intent_id"], binding["intent_digest"])
            if intent["node_id"] != binding["node_id"]:
                raise ValueError("staged monitor node does not match calculation intent")
            result = _read_control_result(workspace, intent, "submit")
            attempted = _read_control_guard(workspace, intent, "submit")
            if result is None and attempted is None:
                continue
            if result is not None and result.get("state") == "failed":
                # Failed submissions do not need polling; a later retry may
                # still succeed, so keep the staged binding available.
                continue
            register_monitor(workspace, **binding)
            record.update(status="registered", last_error=None, next_attempt_at=None)
        except Exception as exc:
            attempts = int(record.get("attempts") or 0) + 1
            delay = min(3600, 5 * 2 ** min(attempts - 1, 10))
            record.update(status="registration_pending", last_error=str(exc), attempts=attempts,
                          next_attempt_at=(_timestamp(timestamp) + timedelta(seconds=delay)).isoformat())
        with _monitor_lock(workspace):
            current = _read_object(path, "pending monitor registration")
            if current.get("status") == "registered":
                record = current
            else:
                write_json(path, record)
        rows.append(record)
    return {"registrations": rows}


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
    registration_results = reconcile_registrations(workspace)
    registration_errors = [row["last_error"] for row in registration_results["registrations"] if row.get("last_error")]
    registrations = list_monitors(workspace)
    if not registrations:
        return {
            "schema_version": TICK_SCHEMA,
            "workspace_id": _workspace_id(workspace),
            "observed_at": tick_time,
            "monitors": [],
            "registration_errors": registration_errors,
        }
    # Keep registration/listing dependency-neutral. Compute backends include
    # optional native packages (NumPy/RDKit) that are only needed while polling.
    from ts_agent.compute.control import calculation_status

    rows: list[dict[str, Any]] = []
    for registration in registrations:
        monitor_id = registration["monitor_id"]
        state_path = _monitor_dir(workspace, monitor_id) / "state.json"
        with _monitor_lock(workspace):
            previous = _recover_monitor(workspace, registration)
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
        with _monitor_lock(workspace):
            previous = _recover_monitor(workspace, registration)
            changed = previous.get("last_status_digest") != digest
            event_id = previous.get("last_event_id")
            sequence = int(previous.get("last_sequence") or 0)
            if changed:
                sequence += 1
                event_id = _event_id(monitor_id, f"{sequence}:{digest}")
                event = {
                    "schema_version": EVENT_SCHEMA,
                    "event_id": event_id,
                    "sequence": sequence,
                    "status_digest": digest,
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
                write_json(event_path, event)
                _ensure_event_delivery(workspace, event)
            write_json(state_path, {
                "schema_version": STATE_SCHEMA,
                "monitor_id": monitor_id,
                "last_state": current,
                "last_program_status": observed.get("program_status"),
                "last_status_digest": digest,
                "last_event_id": event_id,
                "last_observed_at": tick_time,
                "last_changed_at": tick_time if changed else previous.get("last_changed_at"),
                "last_sequence": sequence,
                "last_error": error,
            })
        rows.append(_tick_row(registration, previous, current, changed=changed, event_id=event_id, error=error))
    return {
        "schema_version": TICK_SCHEMA,
        "workspace_id": _workspace_id(workspace),
        "observed_at": tick_time,
        "monitors": rows,
        "registration_errors": registration_errors,
    }


def _new_channel(enabled: bool) -> dict[str, Any]:
    return {"status": "pending" if enabled else "disabled", "attempts": 0,
            "claimed_at": None, "lease_until": None, "claim_token": None,
            "delivered_at": None, "next_attempt_at": None, "last_error": None}


def _normalize_delivery(delivery: dict[str, Any]) -> dict[str, Any]:
    delivery.setdefault("sequence", 0)
    if "channels" not in delivery:
        channels = {"wake": _new_channel(delivery.get("wake_policy") == "next_run"),
                    "notify": _new_channel(delivery.get("notify_policy") == "user")}
        for row in channels.values():
            if row["status"] != "disabled" and delivery.get("status") == "delivered":
                row.update(status="delivered", delivered_at=delivery.get("delivered_at"))
        delivery["channels"] = channels
    active = [row for row in delivery["channels"].values() if row["status"] != "disabled"]
    delivery["status"] = ("delivered" if all(row["status"] == "delivered" for row in active)
                          else "delivering" if any(row["status"] == "delivering" for row in active) else "pending")
    delivery["attempts"] = sum(row["attempts"] for row in active)
    delivery["last_error"] = next((row["last_error"] for row in active if row["last_error"]), None)
    delivery["claimed_at"] = max((row["claimed_at"] for row in active if row["claimed_at"]), default=None)
    delivery["delivered_at"] = (max((row["delivered_at"] for row in active if row["delivered_at"]), default=delivery["created_at"])
                               if delivery["status"] == "delivered" else None)
    return delivery


def _ensure_event_delivery(workspace: Path, event: dict[str, Any]) -> None:
    path = _monitor_dir(workspace, event["monitor_id"]) / "deliveries" / f"{event['event_id']}.json"
    _ensure_directory(path.parent)
    if path.exists():
        return
    write_json(path, _normalize_delivery({
        "schema_version": DELIVERY_SCHEMA, "event_id": event["event_id"],
        "monitor_id": event["monitor_id"], "session_id": event.get("session_id"),
        "sequence": event.get("sequence", 0),
        "wake_policy": event["wake_policy"], "notify_policy": event["notify_policy"],
        "request_id": f"monitor:{event['event_id']}", "created_at": event["observed_at"],
    }))


def _recover_monitor(workspace: Path, registration: dict[str, Any]) -> dict[str, Any]:
    """Finish event -> outbox -> state commits interrupted by process death."""
    directory = _monitor_dir(workspace, registration["monitor_id"])
    state_path = directory / "state.json"
    state = _read_object(state_path, "monitor state") if state_path.exists() else {}
    events = [_read_object(path, "monitor event") for path in (directory / "events").glob("evt_*.json")]
    events.sort(key=lambda event: (int(event.get("sequence") or 0), event["observed_at"], event["event_id"]))
    for event in events:
        _ensure_event_delivery(workspace, event)
    if events:
        latest = events[-1]
        sequence = max(len(events), int(latest.get("sequence") or 0))
        if state.get("last_event_id") != latest["event_id"] or not state.get("last_sequence"):
            semantic = {key: latest.get(key) for key in ("state", "program_status", "error_class", "job_id", "exit_status", "error")}
            state.update(schema_version=STATE_SCHEMA, monitor_id=registration["monitor_id"],
                         last_state=latest["state"], last_program_status=latest.get("program_status"),
                         last_status_digest=latest.get("status_digest") or sha256_json(semantic),
                         last_event_id=latest["event_id"], last_sequence=sequence,
                         last_observed_at=latest["observed_at"], last_changed_at=latest["observed_at"],
                         last_error=latest.get("error"))
            write_json(state_path, state)
    return state


def _timestamp(value: str | None) -> datetime:
    return datetime.fromisoformat(value).astimezone(timezone.utc) if value else datetime.min.replace(tzinfo=timezone.utc)


def _channel_due(channel: dict[str, Any], at: str) -> bool:
    if channel["status"] == "delivering":
        return _timestamp(channel["lease_until"]) <= _timestamp(at)
    return channel["status"] == "pending" and _timestamp(channel["next_attempt_at"]) <= _timestamp(at)


def list_pending_deliveries(root: str | Path, *, at: str | None = None) -> list[dict[str, Any]]:
    workspace = _workspace_root(root)
    rows: list[dict[str, Any]] = []
    for registration in list_monitors(workspace):
        if not registration.get("enabled"):
            continue
        directory = _monitor_dir(workspace, registration["monitor_id"]) / "deliveries"
        if not directory.is_dir() or directory.is_symlink():
            continue
        for path in sorted(directory.glob("evt_*.json"), key=lambda item: item.name):
            if path.is_file() and not path.is_symlink():
                delivery = _normalize_delivery(_read_object(path, "monitor delivery"))
                if any(_channel_due(channel, at or now_iso()) for channel in delivery["channels"].values()):
                    rows.append(delivery)
    return sorted(rows, key=lambda row: (row["created_at"], row["monitor_id"], row["sequence"], row["event_id"]))


def claim_delivery(root: str | Path, event_id: str, *, channel: str = "wake", at: str | None = None) -> dict[str, Any]:
    if channel not in _CHANNELS:
        raise ValueError("monitor channel must be wake or notify")
    workspace = _workspace_root(root)
    timestamp = at or now_iso()
    with _monitor_lock(workspace):
        path = _find_delivery(workspace, event_id)
        delivery = _normalize_delivery(_read_object(path, "monitor delivery"))
        registration = _read_object(path.parent.parent / "registration.json", "monitor registration")
        row = delivery["channels"][channel]
        if not registration.get("enabled") or not _channel_due(row, timestamp):
            return {**delivery, "claimed": False, "claim_token": None}
        token = uuid.uuid4().hex
        row.update(status="delivering", attempts=row["attempts"] + 1, claimed_at=timestamp,
                   lease_until=(_timestamp(timestamp) + timedelta(seconds=_LEASE_SECONDS)).isoformat(),
                   claim_token=token, last_error=None)
        write_json(path, _normalize_delivery(delivery))
        return {**delivery, "claimed": True, "claim_token": token}


def complete_delivery(
    root: str | Path,
    event_id: str,
    *,
    delivered: bool,
    error: str | None = None,
    channel: str = "wake",
    claim_token: str | None = None,
    at: str | None = None,
) -> dict[str, Any]:
    if channel not in _CHANNELS:
        raise ValueError("monitor channel must be wake or notify")
    workspace = _workspace_root(root)
    timestamp = at or now_iso()
    with _monitor_lock(workspace):
        path = _find_delivery(workspace, event_id)
        delivery = _normalize_delivery(_read_object(path, "monitor delivery"))
        row = delivery["channels"][channel]
        if row["status"] != "delivering" or not claim_token or row["claim_token"] != claim_token:
            raise ValueError("monitor delivery claim is stale")
        retry_seconds = min(3600, 5 * 2 ** min(row["attempts"] - 1, 10))
        row.update(status="delivered" if delivered else "pending", delivered_at=timestamp if delivered else None,
                   last_error=None if delivered else (error or "delivery failed"), claim_token=None, lease_until=None,
                   next_attempt_at=None if delivered else (_timestamp(timestamp) + timedelta(seconds=retry_seconds)).isoformat())
        write_json(path, _normalize_delivery(delivery))
        return delivery


def set_monitor_enabled(root: str | Path, monitor_id: str, enabled: bool) -> dict[str, Any]:
    workspace = _workspace_root(root)
    with _monitor_lock(workspace):
        path = _monitor_dir(workspace, monitor_id) / "registration.json"
        registration = _read_object(path, "monitor registration")
        registration["enabled"] = enabled
        write_json(path, registration)
    return monitor_status(workspace, monitor_id=monitor_id)["monitors"][0]


def record_worker_health(root: str | Path, *, error: str | None = None) -> dict[str, Any]:
    workspace = _workspace_root(root)
    with _monitor_lock(workspace):
        record = {"last_tick_at": now_iso(), "last_error": error}
        write_json(workspace / "operations" / "monitors" / "worker_health.json", record)
        return record


def monitor_status(root: str | Path, *, monitor_id: str | None = None) -> dict[str, Any]:
    workspace = _workspace_root(root)
    rows = []
    for registration in list_monitors(workspace):
        if monitor_id is not None and monitor_id != registration["monitor_id"]:
            continue
        directory = _monitor_dir(workspace, registration["monitor_id"])
        state = _read_object(directory / "state.json", "monitor state")
        deliveries = [_normalize_delivery(_read_object(path, "monitor delivery")) for path in sorted((directory / "deliveries").glob("evt_*.json"))]
        channels = [channel for delivery in deliveries for channel in delivery["channels"].values()]
        rows.append({**registration, "state": state, "delivery": {
            "pending_count": sum(row["status"] in {"pending", "delivering"} for row in channels),
            "delivered_count": sum(row["status"] == "delivered" for row in channels),
            "last_error": next((row["last_error"] for row in reversed(channels) if row["last_error"]), None),
            "next_attempt_at": min((row["next_attempt_at"] for row in channels if row["next_attempt_at"]), default=None),
        }})
    if monitor_id is not None and not rows:
        raise ValueError("monitor does not exist")
    health_path = workspace / "operations" / "monitors" / "worker_health.json"
    return {"schema_version": "ts-compute-monitor-status/1", "workspace_id": _workspace_id(workspace), "monitors": rows,
            "worker_health": _read_object(health_path, "monitor worker health") if health_path.exists() else None,
            "pending_registrations": [row for _, row in _pending_registrations(workspace) if row["status"] != "registered"]}


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
