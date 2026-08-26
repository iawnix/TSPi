"""Shared capability checks for bounded TS Web text previews."""

from __future__ import annotations

from pathlib import Path
from typing import Any


MAX_TEXT_BYTES = 1_000_000
SNIFF_BYTES = 8192
BINARY_SUFFIXES = frozenset(
    {
        ".7z",
        ".a",
        ".bin",
        ".bmp",
        ".bz2",
        ".chk",
        ".db",
        ".exe",
        ".gif",
        ".gz",
        ".jpeg",
        ".jpg",
        ".npy",
        ".npz",
        ".o",
        ".pdf",
        ".pickle",
        ".pkl",
        ".png",
        ".rwf",
        ".so",
        ".sqlite",
        ".tar",
        ".tif",
        ".tiff",
        ".webp",
        ".xz",
        ".zip",
    }
)


def preview_capability(path: Path, *, size: int | None = None) -> dict[str, Any]:
    """Describe whether ``path`` can be rendered by the text preview endpoint."""

    try:
        file_size = path.stat().st_size if size is None else size
    except OSError:
        return _unavailable("File is not readable")
    if file_size > MAX_TEXT_BYTES:
        return _unavailable("File exceeds the 1 MB text preview limit")
    if path.suffix.lower() in BINARY_SUFFIXES:
        return _unavailable("File type is binary, not UTF-8 text")
    try:
        with path.open("rb") as handle:
            sample = handle.read(SNIFF_BYTES)
    except OSError:
        return _unavailable("File is not readable")
    return _classify_text(sample, complete=file_size <= len(sample))


def read_text_preview(path: Path) -> str:
    """Read one UTF-8 text file without crossing the preview byte limit."""

    if path.suffix.lower() in BINARY_SUFFIXES:
        raise ValueError("file preview unavailable: file type is binary, not UTF-8 text")
    try:
        with path.open("rb") as handle:
            content = handle.read(MAX_TEXT_BYTES + 1)
    except OSError as exc:
        raise ValueError("file preview unavailable: file is not readable") from exc
    if len(content) > MAX_TEXT_BYTES:
        raise ValueError("file preview unavailable: file exceeds the 1 MB text preview limit")
    capability = _classify_text(content)
    if not capability["available"]:
        raise ValueError(f"file preview unavailable: {str(capability['reason']).lower()}")
    return content.decode("utf-8")


def _classify_text(content: bytes, *, complete: bool = True) -> dict[str, Any]:
    if b"\x00" in content:
        return _unavailable("File is binary, not UTF-8 text")
    try:
        content.decode("utf-8")
    except UnicodeDecodeError as exc:
        if not complete and exc.reason == "unexpected end of data" and exc.end == len(content):
            return {"available": True, "reason": None}
        return _unavailable("File is binary or not UTF-8 text")
    return {"available": True, "reason": None}


def _unavailable(reason: str) -> dict[str, Any]:
    return {"available": False, "reason": reason}
