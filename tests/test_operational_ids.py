from __future__ import annotations

import json
import stat
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from ts_workspace import init_workspace
from ts_workspace.operational import operational_snapshot
from ts_workspace.operational_ids import allocate_operational_id


def test_operational_ids_are_workspace_wide_monotonic_and_private(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace)

    assert allocate_operational_id(workspace, "calc")["identifier"] == "calc_1"
    assert allocate_operational_id(workspace, "sub")["identifier"] == "sub_1"
    assert allocate_operational_id(workspace, "op")["identifier"] == "op_1"
    assert allocate_operational_id(workspace, "calc")["identifier"] == "calc_2"

    state_path = workspace / ".ts-operational-ids.json"
    lock_path = workspace / ".ts-operational-ids.lock"
    assert stat.S_IMODE(state_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(lock_path.stat().st_mode) == 0o600
    assert json.loads(state_path.read_text(encoding="utf-8")) == {
        "schema_version": "ts-operational-id-state/1",
        "high_water": {"calc": 2, "op": 1, "sub": 1},
    }


def test_operational_allocator_reconciles_human_ids_and_ignores_uuid_history(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace)
    (workspace / "acts" / "act_1" / "attempts" / "calc_7").mkdir(parents=True)
    (workspace / "acts" / "act_1" / "attempts" / "calc_7" / "runs" / "sub_9").mkdir(parents=True)
    (workspace / "reviews" / "claim_1" / "runs" / "sub_028def15-cbb5-42b4-bbfc-cfbd256c4a0b").mkdir(parents=True)
    (workspace / "operations" / "activities" / "op_5").mkdir(parents=True)

    assert allocate_operational_id(workspace, "calc")["identifier"] == "calc_8"
    assert allocate_operational_id(workspace, "sub")["identifier"] == "sub_10"
    assert allocate_operational_id(workspace, "op")["identifier"] == "op_6"


def test_operational_allocator_never_reuses_reserved_ordinals(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace)

    assert allocate_operational_id(workspace, "sub")["identifier"] == "sub_1"
    assert allocate_operational_id(workspace, "sub")["identifier"] == "sub_2"
    assert allocate_operational_id(workspace, "sub")["identifier"] == "sub_3"


def test_operational_id_state_is_part_of_the_operational_revision(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace)
    before = operational_snapshot(workspace)

    allocate_operational_id(workspace, "op")
    after = operational_snapshot(workspace)

    assert after["operational_revision"] != before["operational_revision"]
    assert after["operational_summary"]["tracked_file_count"] == 1


def test_operational_allocator_serializes_concurrent_callers(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace)

    with ThreadPoolExecutor(max_workers=8) as executor:
        identifiers = list(executor.map(lambda _: allocate_operational_id(workspace, "op")["identifier"], range(24)))

    assert sorted(identifiers, key=lambda value: int(value.split("_")[1])) == [
        f"op_{ordinal}" for ordinal in range(1, 25)
    ]


def test_operational_allocator_rejects_invalid_kind_and_symlink_state(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace)
    with pytest.raises(ValueError, match="unsupported operational ID kind"):
        allocate_operational_id(workspace, "review")

    target = tmp_path / "state.json"
    target.write_text("{}\n", encoding="utf-8")
    (workspace / ".ts-operational-ids.json").symlink_to(target)
    with pytest.raises(ValueError, match="state must be a regular file"):
        allocate_operational_id(workspace, "sub")
