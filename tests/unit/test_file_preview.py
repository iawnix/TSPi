from __future__ import annotations

from pathlib import Path

import pytest

from ts_agent.projection.file_preview import preview_capability, read_text_preview


def test_preview_rejects_symbolic_link_source(tmp_path: Path) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("secret\n", encoding="utf-8")
    linked = tmp_path / "linked.txt"
    linked.symlink_to(outside)

    assert preview_capability(linked) == {"available": False, "reason": "File is not readable"}
    with pytest.raises(ValueError, match="not readable"):
        read_text_preview(linked)


def test_preview_reads_regular_utf8_file(tmp_path: Path) -> None:
    path = tmp_path / "record.txt"
    path.write_text("hello\n", encoding="utf-8")

    assert preview_capability(path) == {"available": True, "reason": None}
    assert read_text_preview(path) == "hello\n"
