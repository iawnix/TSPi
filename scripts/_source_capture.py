"""Capture one immutable Git-visible source tree for release assembly."""

from __future__ import annotations

import hashlib
import io
import os
import shutil
import subprocess
import tarfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


GIT_OBJECT_ID_LENGTHS = {40, 64}
REQUIRED_SOURCE_PATHS = {
    b"README.md",
    b"package.json",
    b"pyproject.toml",
    b"scripts/build_release.py",
    b"scripts/check_package.py",
    b"scripts/package_inventory.py",
}


class SourceCaptureError(RuntimeError):
    """The release source could not be captured without ambiguity."""


@dataclass(frozen=True)
class CapturedSource:
    root: Path
    git_commit: str
    dirty: bool
    relative_names: tuple[bytes, ...]
    payload_sha256: str

    def verify(self) -> None:
        actual = source_tree_sha256(self.root, self.relative_names)
        if actual != self.payload_sha256:
            raise SourceCaptureError("captured release source changed during the build")


def capture_source_tree(root: Path, destination: Path, *, allow_dirty: bool) -> CapturedSource:
    repository = root.expanduser().resolve()
    target = destination.expanduser().resolve()
    if target.is_relative_to(repository):
        raise SourceCaptureError("captured source destination must be outside the source repository")
    commit, dirty, names, digest = inspect_source(repository)
    if dirty and not allow_dirty:
        raise SourceCaptureError(
            "release builds require a clean Git checkout; use --allow-dirty only for local validation"
        )
    if target.exists() or target.is_symlink():
        raise SourceCaptureError(f"captured source destination already exists: {target}")
    target.mkdir(mode=0o700, parents=True)
    if dirty:
        copy_source_entries(repository, target, names)
    else:
        export_git_source(repository, target, commit, names)
    captured_digest = source_tree_sha256(target, names)
    if captured_digest != digest:
        raise SourceCaptureError("source changed while it was being captured for the release build")
    return CapturedSource(target, commit, dirty, tuple(names), digest)


def inspect_source(root: Path) -> tuple[str, bool, list[bytes], str]:
    top_level = run_git(root, ["rev-parse", "--show-toplevel"], "locate source repository")
    if Path(os.fsdecode(top_level).strip()).resolve() != root:
        raise SourceCaptureError("source root must be the top level of the TSPi Git repository")
    revision = run_git(root, ["rev-parse", "--verify", "HEAD"], "read source commit")
    commit = revision.decode("ascii", errors="strict").strip()
    if len(commit) not in GIT_OBJECT_ID_LENGTHS or any(character not in "0123456789abcdef" for character in commit):
        raise SourceCaptureError("source commit is not a full Git object ID")

    flags = run_git(root, ["ls-files", "-v", "-z"], "inspect source index flags")
    if any(entry and not entry.startswith(b"H ") for entry in flags.split(b"\0")):
        raise SourceCaptureError("source index contains assume-unchanged, skip-worktree, or unresolved entries")
    listed = run_git(
        root,
        ["ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        "list source files",
    )
    names = sorted({name for name in listed.split(b"\0") if name})
    missing = sorted(REQUIRED_SOURCE_PATHS.difference(names))
    if missing:
        detail = ", ".join(os.fsdecode(name) for name in missing)
        raise SourceCaptureError(f"source repository is missing required paths: {detail}")
    status = run_git(
        root,
        ["status", "--porcelain=v1", "-z", "--untracked-files=normal"],
        "read source status",
    )
    return commit, bool(status), names, source_tree_sha256(root, names)


def source_tree_sha256(root: Path, relative_names: Iterable[bytes]) -> str:
    digest = hashlib.sha256()
    digest.update(b"tspi-release-source/1\0")
    for raw_name in relative_names:
        relative = safe_relative(os.fsdecode(raw_name))
        source = root.joinpath(*relative.parts)
        if source.is_symlink():
            raise SourceCaptureError(f"release source must not contain symlinks: {relative}")
        if source.is_file():
            executable = 0o111 if source.stat().st_mode & 0o111 else 0
            kind = f"file:{executable:03o}".encode("ascii")
            content = source.read_bytes()
        elif not source.exists():
            kind = b"missing"
            content = b""
        else:
            raise SourceCaptureError(f"source entry is not a regular file: {relative}")
        update_framed_digest(digest, raw_name)
        update_framed_digest(digest, kind)
        update_framed_digest(digest, content)
    return digest.hexdigest()


def copy_source_entries(root: Path, destination: Path, relative_names: Iterable[bytes]) -> None:
    for raw_name in relative_names:
        relative = safe_relative(os.fsdecode(raw_name))
        source = root.joinpath(*relative.parts)
        if source.is_symlink():
            raise SourceCaptureError(f"release source must not contain symlinks: {relative}")
        if not source.exists():
            continue
        if not source.is_file():
            raise SourceCaptureError(f"release source entry is not a regular file: {relative}")
        target = destination.joinpath(*relative.parts)
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        target.chmod(0o755 if source.stat().st_mode & 0o111 else 0o644)


def export_git_source(root: Path, destination: Path, commit: str, expected_names: Iterable[bytes]) -> None:
    encoded = run_git(root, ["archive", "--format=tar", commit], "capture committed source")
    extracted_names: set[bytes] = set()
    try:
        with tarfile.open(fileobj=io.BytesIO(encoded), mode="r:") as archive:
            for member in archive.getmembers():
                raw_name = member.name.rstrip("/")
                if not raw_name:
                    continue
                relative = safe_relative(raw_name)
                target = destination.joinpath(*relative.parts)
                if member.isdir():
                    target.mkdir(mode=0o700, parents=True, exist_ok=True)
                    continue
                if not member.isreg():
                    raise SourceCaptureError(f"committed release source contains a non-file: {relative}")
                encoded_name = os.fsencode(relative.as_posix())
                if encoded_name in extracted_names:
                    raise SourceCaptureError(f"committed release source contains a duplicate path: {relative}")
                extracted_names.add(encoded_name)
                extracted = archive.extractfile(member)
                if extracted is None:
                    raise SourceCaptureError(f"committed release source cannot be read: {relative}")
                with extracted:
                    content = extracted.read(member.size + 1)
                if len(content) != member.size:
                    raise SourceCaptureError(f"committed release source has an invalid size: {relative}")
                target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                with target.open("xb") as handle:
                    handle.write(content)
                target.chmod(0o755 if member.mode & 0o111 else 0o644)
    except (OSError, tarfile.TarError) as error:
        raise SourceCaptureError(f"could not capture committed release source: {error}") from error
    if extracted_names != set(expected_names):
        raise SourceCaptureError("committed source archive does not match the release source inventory")


def run_git(root: Path, arguments: list[str], label: str) -> bytes:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip() or label
        raise SourceCaptureError(f"could not {label}: {detail}")
    return completed.stdout


def safe_relative(value: str) -> PurePosixPath:
    relative = PurePosixPath(value)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts or any(not part for part in relative.parts):
        raise SourceCaptureError(f"unsafe source path: {value}")
    return relative


def update_framed_digest(digest: Any, value: bytes) -> None:
    digest.update(len(value).to_bytes(8, "big"))
    digest.update(value)
