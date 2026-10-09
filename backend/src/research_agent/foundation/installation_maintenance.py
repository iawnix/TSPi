"""Durable installation maintenance boundary, independent of research state.

Before service activation an installer may restore its configuration snapshot.
Once a runtime can write new facts, failure requires forward repair. No research
data is migrated and no credentials live here.
"""
from __future__ import annotations

import fcntl
import os
from pathlib import Path
import stat
import uuid

from .io import now_iso, read_json, write_json
from .path_safety import lexical_path, path_has_symlink

_SCHEMA = "research-agent-installation-maintenance/1"
_TERMINAL = {"completed", "rolled_back"}
_STATES = _TERMINAL | {"preparing", "starting", "failed"}


def _paths(root):
    root = lexical_path(root)
    directory = root / "var/state/installation"
    if path_has_symlink(directory):
        raise ValueError("installation maintenance path cannot contain symbolic links")
    return root, directory / "maintenance.json", directory / "maintenance.lock"


def _read(root, path):
    if not path.exists() and not path.is_symlink():
        return None
    value = read_json(path)
    if (not isinstance(value, dict) or value.get("schema_version") != _SCHEMA
            or value.get("install_root") != str(root) or value.get("state") not in _STATES
            or not isinstance(value.get("activation_started"), bool)):
        raise ValueError("installation maintenance record is invalid")
    return value


def assert_installation_available(root):
    """Block runtime launch during maintenance, including an installer crash."""
    root, path, lock = _paths(root)
    value = _read(root, path)
    if value is None or value["state"] in _TERMINAL:
        return
    if value["state"] == "starting":
        descriptor = os.open(lock, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise ValueError("installation maintenance lock must be a regular file")
            try:
                fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError:
                # Only the live installer can open this activation window.
                return
        finally:
            os.close(descriptor)
    raise RuntimeError("installation_maintenance_required: rerun the installer to finish or repair this installation")


class InstallationMaintenance:
    def __init__(self, root):
        self.root, self.path, self.lock = _paths(root)
        self.descriptor = None
        self.record = None
        self.repairing = False

    def acquire(self):
        missing = []
        directory = self.path.parent
        while not directory.exists():
            missing.append(directory)
            directory = directory.parent
        for directory in reversed(missing):
            directory.mkdir(exist_ok=True, mode=0o700)
            parent = os.open(directory.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(parent)
            finally:
                os.close(parent)
        descriptor = os.open(self.lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise ValueError("installation maintenance lock must be a regular file")
            os.fchmod(descriptor, 0o600)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise RuntimeError("installation_maintenance_busy: another installer is active") from error
            previous = _read(self.root, self.path)
            self.repairing = previous is not None and previous["state"] not in _TERMINAL
            self.record = {"schema_version": _SCHEMA, "install_root": str(self.root),
                           "attempt_id": str(uuid.uuid4()), "state": "preparing",
                           "activation_started": bool(self.repairing and previous["activation_started"]),
                           "repairing": self.repairing, "started_at": now_iso()}
            write_json(self.path, self.record)
            self.descriptor = descriptor
        except BaseException:
            os.close(descriptor)
            raise
        return self

    @property
    def rollback_allowed(self):
        return self.record is not None and not self.repairing and not self.record["activation_started"]

    def transition(self, state, **fields):
        if self.descriptor is None or state not in _STATES:
            raise RuntimeError("installation maintenance is not held")
        if state == "rolled_back" and not self.rollback_allowed:
            raise RuntimeError("service activation requires forward repair")
        record = {**self.record, **fields, "state": state, "updated_at": now_iso()}
        if state == "starting":
            record["activation_started"] = True
        # Retain the conservative in-memory boundary even if publication fails.
        self.record = record
        write_json(self.path, record)

    def close(self):
        if self.descriptor is not None:
            os.close(self.descriptor)
            self.descriptor = None
