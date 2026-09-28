from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ts_agent.workspace.doctor import inspect_workspace


def _manifest(root: Path, *, revision: int = 0, mode: str = "research") -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "workspace_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "research_agent_workspace_1",
                "workspace_id": "workspace_one",
                "workspace_mode": mode,
                "state": "ready",
                "workspace_root": str(root),
                "research_kernel": {
                    "initialized": mode == "research",
                    "admission_required": False,
                    "revision": revision if mode == "research" else None,
                },
            }
        ),
        encoding="utf-8",
    )


def _context(root: Path, revision: int = 0) -> None:
    (root / "research_map").mkdir(parents=True, exist_ok=True)
    (root / "research_map" / "context.json").write_text(
        json.dumps(
            {
                "schema_version": "research_map_context_1",
                "workspace_id": "workspace_one",
                "workspace_mode": "research",
                "revision": revision,
                "lifecycle_state": "admitted",
            }
        ),
        encoding="utf-8",
    )


def _legacy_map(root: Path, revision: int = 0) -> None:
    (root / "research_map.json").write_text(
        json.dumps(
            {
                "schema_version": "research-map/1",
                "map_id": "workspace_one",
                "revision": revision,
            }
        ),
        encoding="utf-8",
    )


def _sqlite_map(root: Path, revision: int = 0, *, payload_revision: int | None = None) -> None:
    payload_revision = revision if payload_revision is None else payload_revision
    connection = sqlite3.connect(root / "research.db")
    connection.executescript(
        """
        CREATE TABLE research_map (
            singleton INTEGER PRIMARY KEY,
            map_id TEXT NOT NULL,
            revision INTEGER NOT NULL,
            payload TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )
    connection.execute(
        "INSERT INTO research_map VALUES (1, ?, ?, ?, ?)",
        (
            "workspace_one",
            revision,
            json.dumps({"schema_version": "research-map/1", "map_id": "workspace_one", "revision": payload_revision}),
            "2026-01-01T00:00:00Z",
        ),
    )
    connection.commit()
    connection.close()


def test_doctor_accepts_new_research_storage_without_writing(tmp_path: Path) -> None:
    _manifest(tmp_path)
    _context(tmp_path)

    result = inspect_workspace(tmp_path)

    assert result["valid"] is True
    assert result["status"] == "healthy"
    assert result["findings"] == []
    assert not (tmp_path / "research.db").exists()


def test_doctor_reports_same_revision_legacy_storage_as_transitional_warning(tmp_path: Path) -> None:
    _manifest(tmp_path, revision=2)
    _context(tmp_path, revision=2)
    _legacy_map(tmp_path, revision=2)
    _sqlite_map(tmp_path, revision=2)

    result = inspect_workspace(tmp_path)

    assert result["valid"] is True
    assert result["status"] == "compatibility"
    assert {finding["code"] for finding in result["findings"]} == {"dual_research_map_storage"}


def test_doctor_fails_closed_when_context_and_legacy_revisions_split(tmp_path: Path) -> None:
    _manifest(tmp_path, revision=0)
    _context(tmp_path, revision=0)
    _legacy_map(tmp_path, revision=4)
    _sqlite_map(tmp_path, revision=4)

    result = inspect_workspace(tmp_path)

    assert result["valid"] is False
    assert result["status"] == "blocked"
    assert "research_revision_mismatch" in {finding["code"] for finding in result["findings"]}


def test_doctor_fails_closed_when_manifest_context_revisions_split(tmp_path: Path) -> None:
    _manifest(tmp_path, revision=3)
    _context(tmp_path, revision=2)

    result = inspect_workspace(tmp_path)

    assert result["valid"] is False
    assert "manifest_context_revision_mismatch" in {finding["code"] for finding in result["findings"]}


def test_doctor_checks_sqlite_payload_revision_without_mutating_it(tmp_path: Path) -> None:
    _manifest(tmp_path, revision=1)
    _context(tmp_path, revision=1)
    _sqlite_map(tmp_path, revision=1, payload_revision=0)
    before = (tmp_path / "research.db").read_bytes()

    result = inspect_workspace(tmp_path)

    assert result["valid"] is False
    codes = {finding["code"] for finding in result["findings"]}
    assert "sqlite_revision_payload_mismatch" in codes
    assert (tmp_path / "research.db").read_bytes() == before


def test_doctor_allows_known_manifest_to_legacy_identity_translation(tmp_path: Path) -> None:
    _manifest(tmp_path, revision=1)
    _context(tmp_path, revision=1)
    (tmp_path / "research_map.json").write_text(
        json.dumps({"schema_version": "research-map/1", "map_id": "ws_0123456789abcdef01234567", "revision": 1}),
        encoding="utf-8",
    )

    result = inspect_workspace(tmp_path)

    assert result["valid"] is True
    assert "dual_identity_translation" in {finding["code"] for finding in result["findings"]}
