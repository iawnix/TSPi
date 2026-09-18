from __future__ import annotations

import json
from pathlib import Path

import pytest

from ts_agent.io import append_jsonl, append_markdown, read_json, write_json, write_text_atomic


def test_read_json_rejects_symbolic_link(tmp_path: Path) -> None:
    target = tmp_path / "outside.json"
    target.write_text('{"outside": true}\n', encoding="utf-8")
    linked = tmp_path / "linked.json"
    linked.symlink_to(target)

    with pytest.raises(OSError):
        read_json(linked)


@pytest.mark.parametrize("writer", [write_json, write_text_atomic])
def test_atomic_writers_do_not_replace_symbolic_link(
    tmp_path: Path,
    writer,
) -> None:
    target = tmp_path / "outside.txt"
    target.write_text("outside\n", encoding="utf-8")
    linked = tmp_path / "linked.txt"
    linked.symlink_to(target)

    with pytest.raises(OSError):
        if writer is write_json:
            writer(linked, {"inside": True})
        else:
            writer(linked, "inside\n")

    assert target.read_text(encoding="utf-8") == "outside\n"
    assert linked.is_symlink()


def test_append_jsonl_rejects_symbolic_link(tmp_path: Path) -> None:
    target = tmp_path / "outside.jsonl"
    target.write_text("outside\n", encoding="utf-8")
    linked = tmp_path / "linked.jsonl"
    linked.symlink_to(target)

    with pytest.raises(OSError):
        append_jsonl(linked, {"inside": True})

    assert target.read_text(encoding="utf-8") == "outside\n"


def test_atomic_writer_keeps_json_contract_and_uses_private_file(tmp_path: Path) -> None:
    path = tmp_path / "record.json"
    write_json(path, {"value": 1})

    assert json.loads(path.read_text(encoding="utf-8")) == {"value": 1}
    assert path.stat().st_mode & 0o077 == 0
    assert not list(tmp_path.glob("record.json.tmp"))


def test_append_markdown_rejects_symbolic_link(tmp_path: Path) -> None:
    target = tmp_path / "outside.md"
    target.write_text("outside\n", encoding="utf-8")
    linked = tmp_path / "linked.md"
    linked.symlink_to(target)

    with pytest.raises(OSError):
        append_markdown(linked, "Title", "Body")

    assert target.read_text(encoding="utf-8") == "outside\n"
