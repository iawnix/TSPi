"""Bounded, read-only phone access to scientific workspace materials.

Every component is opened relative to an already opened directory, without
following links. No session databases, control directories or hidden files are
part of this public projection.
"""
from __future__ import annotations
import base64
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import PurePosixPath
import stat
import secrets

ROOTS = frozenset({"inputs", "artifacts", "runs", "reports", "outputs"})
EXTENSIONS = frozenset({".xyz", ".mol", ".sdf", ".mol2", ".pdb", ".cif", ".mmcif", ".csv", ".tsv", ".txt", ".md", ".log", ".out", ".err", ".inp", ".gjf", ".com", ".cube", ".cub", ".png", ".jpg", ".jpeg", ".pdf"})
CHUNK = 65536
MAX_PREVIEW = 8 * 1024 * 1024

class FileAccessError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code

def fail(code, message):
    raise FileAccessError(code, message)

def parts(path):
    if not isinstance(path, str) or len(path) > 2048 or "\\" in path or "\0" in path:
        fail("invalid_file_path", "Invalid workspace file path")
    if path == "":
        return []
    items = path.split("/")
    if items[0] not in ROOTS or any(not x or x.startswith(".") for x in items):
        fail("file_access_denied", "File is outside the material roots")
    return items

@contextmanager
def opened(root, path, *, directory=False):
    components = parts(path)
    handles = []
    try:
        fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        handles.append(fd)
        for index, component in enumerate(components):
            is_directory = directory or index < len(components) - 1
            flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
            if is_directory:
                flags |= os.O_DIRECTORY
            fd = os.open(component, flags, dir_fd=fd)
            handles.append(fd)
        info = os.fstat(fd)
        if directory:
            if not stat.S_ISDIR(info.st_mode):
                fail("file_access_denied", "Not a directory")
        elif not components or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or PurePosixPath(path).suffix.lower() not in EXTENSIONS:
            fail("file_access_denied", "Unsupported material file")
        yield fd, info
    except OSError as error:
        code = "file_not_found" if error.errno == 2 else "file_access_denied"
        raise FileAccessError(code, "Material is missing or inaccessible") from error
    finally:
        for handle in reversed(handles):
            os.close(handle)

def version(info):
    return hashlib.sha256(f"{info.st_dev}:{info.st_ino}:{info.st_size}:{info.st_mtime_ns}:{info.st_ctime_ns}".encode()).hexdigest()

def entry(path, info):
    return {"path": path, "name": PurePosixPath(path).name, "kind": "directory" if stat.S_ISDIR(info.st_mode) else "file",
            "size": info.st_size, "version": version(info)}

def dispatch(root, request):
    operation = request.get("operation")
    path = request.get("path", "")
    parts(path)
    if operation == "list":
        limit = request.get("limit", 50)
        if type(limit) is not int or not 1 <= limit <= 100:
            fail("invalid_params", "Invalid page size")
        with opened(root, path, directory=True) as (fd, info):
            stamp = version(info)
            names = []
            with os.scandir(fd) as scan:
                for scanned, item in enumerate(scan):
                    if scanned >= 10000:
                        fail("file_listing_limit", "Directory is too large to browse")
                    if item.name.startswith(".") or (not path and item.name not in ROOTS):
                        continue
                    names.append(item.name)
            start = 0
            cursor = request.get("cursor")
            if cursor is not None:
                try:
                    old_path, old_stamp, start = json.loads(base64.urlsafe_b64decode(cursor).decode())
                    if old_path != path or old_stamp != stamp or type(start) is not int or start < 0:
                        raise ValueError()
                except Exception as error:
                    raise FileAccessError("file_changed", "Directory changed; reload it") from error
            result = []
            ordered = sorted(names)
            index = start
            while index < len(ordered) and len(result) < limit:
                name = ordered[index]
                index += 1
                target = f"{path}/{name}" if path else name
                try:
                    item = os.stat(name, dir_fd=fd, follow_symlinks=False)
                    if stat.S_ISDIR(item.st_mode) or (stat.S_ISREG(item.st_mode) and item.st_nlink == 1 and PurePosixPath(name).suffix.lower() in EXTENSIONS):
                        result.append(entry(target, item))
                except OSError:
                    continue
            if version(os.fstat(fd)) != stamp:
                fail("file_changed", "Directory changed; reload it")
            next_cursor = base64.urlsafe_b64encode(json.dumps([path, stamp, index]).encode()).decode() if index < len(ordered) else None
            return {"schema_version": "coragent-files/1", "items": result, "next_cursor": next_cursor}
    if operation == "pin":
        with opened(root, path) as (fd, info):
            if request.get("expected_version") != version(info):
                fail("file_changed", "File changed; reopen it")
            if info.st_size > MAX_PREVIEW:
                fail("file_too_large", "File exceeds the attachment limit")
            data = os.pread(fd, MAX_PREVIEW + 1, 0)
            if len(data) != info.st_size or version(os.fstat(fd)) != request["expected_version"]:
                fail("file_changed", "File changed during capture")
        digest = hashlib.sha256(data).hexdigest()
        suffix = PurePosixPath(path).suffix.lower()
        name = digest + suffix
        with opened(root, "inputs", directory=True) as (inputs_fd, _):
            try:
                os.mkdir("phone-references", mode=0o700, dir_fd=inputs_fd)
            except FileExistsError:
                pass
            refs = os.open("phone-references", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=inputs_fd)
            temporary = "." + secrets.token_hex(16)
            try:
                target = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=refs)
                try:
                    with os.fdopen(target, "wb", closefd=False) as output:
                        output.write(data)
                        output.flush()
                        os.fchmod(target, 0o444)
                        os.fsync(target)
                finally:
                    os.close(target)
                os.replace(temporary, name, src_dir_fd=refs, dst_dir_fd=refs)
                os.fsync(refs)
            finally:
                try:
                    os.unlink(temporary, dir_fd=refs)
                except FileNotFoundError:
                    pass
                os.close(refs)
        return {"path": f"inputs/phone-references/{name}", "source_path": path,
                "source_version": request["expected_version"], "sha256": digest, "size": len(data)}
    if operation in {"stat", "read"}:
        with opened(root, path) as (fd, info):
            meta = entry(path, info)
            if operation == "stat":
                return {"file": meta, "max_chunk_bytes": CHUNK, "max_preview_bytes": MAX_PREVIEW}
            expected = request.get("expected_version")
            if expected != meta["version"]:
                fail("file_changed", "File changed; reopen it")
            offset, length = request.get("offset", 0), request.get("length", CHUNK)
            if type(offset) is not int or offset < 0 or offset > info.st_size or type(length) is not int or not 1 <= length <= CHUNK:
                fail("invalid_params", "Invalid file range")
            data = os.pread(fd, length, offset)
            if version(os.fstat(fd)) != expected:
                fail("file_changed", "File changed during reading")
            return {"file": meta, "offset": offset, "data_base64": base64.b64encode(data).decode(),
                    "next_offset": offset + len(data), "eof": offset + len(data) >= info.st_size}
    fail("method_not_found", "Unsupported file operation")
