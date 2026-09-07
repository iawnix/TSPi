"""Pre-open guards for workspace-local Pi history, independent of research state."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
import uuid
from pathlib import Path

CONTRACT = "tspi-session-guard/1"
SESSION_ID = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,158}[A-Za-z0-9])?$")
HEADER_LIMIT = 64 * 1024


class SessionGuardError(RuntimeError):
    pass


def guard_directory(installation: Path, workspace: Path) -> Path:
    key = hashlib.sha256(os.fsencode(workspace)).hexdigest()
    return installation / ".pi" / "session-host" / "guards" / key


def session_lock_path(installation: Path, workspace: Path, session_id: str) -> Path:
    return guard_directory(installation, workspace) / (
        "session-" + hashlib.sha256(session_id.encode("utf-8")).hexdigest() + ".lock"
    )


def acquire_directory_guard(installation: Path, workspace: Path, *, exclusive: bool = False) -> int:
    directory = guard_directory(installation, workspace)
    current = installation
    for part in directory.relative_to(installation).parts:
        current = current / part
        if current.is_symlink():
            raise SessionGuardError("session guard directory cannot be a symbolic link")
        current.mkdir(mode=0o700, exist_ok=True)
        if not current.is_dir():
            raise SessionGuardError("invalid session guard directory")
    return _acquire(directory / "directory.lock", exclusive=exclusive)


def acquire_session_guard(installation: Path, workspace: Path, session_id: str, mode: str) -> int:
    if not SESSION_ID.fullmatch(session_id):
        raise SessionGuardError("invalid session ID")
    descriptor = _acquire(session_lock_path(installation, workspace, session_id), exclusive=True)
    try:
        identity = {
            "contract": CONTRACT,
            "pid": os.getpid(),
            "workspace": str(workspace),
            "sessionId": session_id,
            "accessMode": mode,
        }
        os.ftruncate(descriptor, 0)
        os.write(descriptor, json.dumps(identity).encode("ascii"))
        os.fsync(descriptor)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _acquire(path: Path, *, exclusive: bool) -> int:
    flags = os.O_RDWR | os.O_CREAT | os.O_NONBLOCK | os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise SessionGuardError(f"cannot open session guard: {path.name}") from exc
    try:
        opened = os.fstat(descriptor)
        current = path.lstat()
        if (not stat.S_ISREG(opened.st_mode) or opened.st_uid != os.getuid()
                or opened.st_mode & 0o077 or opened.st_nlink != 1
                or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)):
            raise SessionGuardError("session guard is not an owner-only regular file")
        try:
            fcntl.flock(descriptor, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise SessionGuardError(
                "session writer or lifecycle operation is active; close its runtime before reopening"
            ) from exc
        os.set_inheritable(descriptor, True)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def assert_no_unguarded_writers(workspace: Path) -> None:
    """Fail closed on old TSPi writers before enabling shared session guards."""
    proc = Path("/proc")
    if not proc.is_dir():
        raise SessionGuardError("session writer inspection requires Linux /proc")
    for process in proc.iterdir():
        if not process.name.isdecimal() or int(process.name) == os.getpid():
            continue
        try:
            if process.stat().st_uid != os.getuid():
                continue
            if (process / "cwd").resolve() != workspace:
                continue
            environment = (process / "environ").read_bytes().split(b"\0")
            values = dict(item.split(b"=", 1) for item in environment if b"=" in item)
            if values.get(b"TS_WORKSPACE_ROOT") != os.fsencode(workspace):
                continue
            if values.get(b"TS_SESSION_GUARD") == CONTRACT.encode():
                continue
            raise SessionGuardError(
                f"unguarded TSPi writer pid {process.name} is still open; exit it before using Session Host"
            )
        except (FileNotFoundError, ProcessLookupError):
            continue
        except PermissionError as exc:
            raise SessionGuardError("cannot verify existing workspace writers") from exc


def verify_session_writer(installation: Path, workspace: Path, session_id: str, mode: str, pid: int) -> None:
    """Bind Bridge identity to held OS guards, not just an occupied Root lock."""
    if pid <= 0 or not SESSION_ID.fullmatch(session_id) or mode not in {"controller", "observer"}:
        raise SessionGuardError("invalid session writer identity")
    process = Path("/proc") / str(pid)
    lock_path = session_lock_path(installation, workspace, session_id)
    expected = {
        guard_directory(installation, workspace) / "directory.lock": "READ",
        lock_path: "WRITE",
    }
    if mode == "controller":
        expected[workspace / ".pi" / "root-agent.lock"] = "WRITE"
    try:
        if process.stat().st_uid != os.getuid():
            raise SessionGuardError("session writer belongs to another account")
        for descriptor in (process / "fd").iterdir():
            try:
                path = Path(os.readlink(descriptor))
            except FileNotFoundError:
                continue
            lock_mode = expected.get(path)
            if lock_mode is None:
                continue
            info = (process / "fdinfo" / descriptor.name).read_text()
            if re.search(rf"^lock:\s+\d+: FLOCK\s+ADVISORY\s+{lock_mode}\s+{pid}\s", info, re.MULTILINE):
                del expected[path]
        if expected:
            raise SessionGuardError("session writer does not hold the required guards")
        descriptor = os.open(lock_path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "rb") as handle:
            identity = json.loads(handle.read(4097))
        if identity != {
            "contract": CONTRACT, "pid": pid, "workspace": str(workspace),
            "sessionId": session_id, "accessMode": mode,
        }:
            raise SessionGuardError("session writer guard identity mismatch")
    except (OSError, ValueError) as exc:
        raise SessionGuardError("session writer could not be verified") from exc


def select_session(workspace: Path, arguments: list[str], *, default_continue: bool = False) -> tuple[str, list[str]]:
    """Resolve an exact ID before Pi opens it; never let Pi select a second file."""
    selectors: list[tuple[str, str | None]] = []
    remaining: list[str] = []
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        option, _, inline = argument.partition("=")
        if option in {"--resume", "-r", "--fork", "--session-dir", "--no-session"}:
            raise SessionGuardError(f"{option} is not supported by guarded TSPi; reopen with --session-id <id>")
        if option in {"--session-id", "--session"}:
            if not inline:
                index += 1
                if index >= len(arguments):
                    raise SessionGuardError(f"{option} requires a value")
                inline = arguments[index]
            selectors.append((option, inline))
        elif option in {"--continue", "-c"}:
            selectors.append(("--continue", None))
        else:
            remaining.append(argument)
        index += 1
    if len(selectors) > 1:
        raise SessionGuardError("choose exactly one session selector")
    if not selectors and default_continue:
        selectors.append(("--continue", None))
    sessions = _session_headers(workspace)
    selected_id: str
    if not selectors:
        selected_id = str(uuid.uuid4())
    else:
        option, value = selectors[0]
        if option == "--continue":
            selected_id = max(sessions, key=lambda row: row[2])[0] if sessions else str(uuid.uuid4())
        elif option == "--session":
            candidate = Path(value or "").expanduser()
            if not candidate.is_absolute():
                candidate = workspace / candidate
            matches = [row for row in sessions if row[1] == candidate.absolute() or row[0] == value]
            if len(matches) != 1:
                raise SessionGuardError("--session requires one existing workspace-local file or exact ID")
            selected_id = matches[0][0]
        else:
            selected_id = value or ""
    if not SESSION_ID.fullmatch(selected_id):
        raise SessionGuardError("invalid session ID")
    return selected_id, [*remaining, "--session-id", selected_id]


def _session_headers(workspace: Path) -> list[tuple[str, Path, int]]:
    directory = workspace / ".pi" / "sessions"
    if directory.is_symlink() or directory.parent.is_symlink():
        raise SessionGuardError("Pi history directory cannot be a symbolic link")
    if not directory.exists():
        return []
    sessions: list[tuple[str, Path, int]] = []
    ids: set[str] = set()
    for path in directory.glob("*.jsonl"):
        try:
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except OSError as exc:
            raise SessionGuardError(f"cannot safely read Pi history: {path.name}") from exc
        with os.fdopen(descriptor, "rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise SessionGuardError("invalid Pi history file")
            try:
                header = json.loads(handle.readline(HEADER_LIMIT + 1))
            except (ValueError, UnicodeError) as exc:
                raise SessionGuardError(f"invalid Pi session header: {path.name}") from exc
        if not isinstance(header, dict) or header.get("type") != "session":
            raise SessionGuardError(f"invalid Pi session header: {path.name}")
        session_id = header.get("id")
        if not isinstance(session_id, str) or not SESSION_ID.fullmatch(session_id):
            raise SessionGuardError("invalid persisted session ID")
        if not isinstance(header.get("cwd"), str) or Path(header["cwd"]).resolve() != workspace:
            raise SessionGuardError("Pi session belongs to a different workspace")
        if session_id in ids:
            raise SessionGuardError("duplicate Pi session ID; inspect history before reopening")
        ids.add(session_id)
        sessions.append((session_id, path, info.st_mtime_ns))
    return sessions
