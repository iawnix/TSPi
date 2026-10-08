from pathlib import Path

import pytest

import research_state.transactions as transactions
from research_state.transactions import TransactionCoordinator, TransactionError, _atomic_json, _digest


def test_commit_files_is_idempotent_and_replays_same_result(tmp_path: Path) -> None:
    coordinator = TransactionCoordinator(tmp_path)
    first = coordinator.commit_files(
        "request-1", "research.change", {"value": 1},
        writes={"research_map/context.json": {"revision": 1}}, result={"revision": 1},
    )
    second = coordinator.commit_files(
        "request-1", "research.change", {"value": 1},
        writes={"research_map/context.json": {"revision": 1}}, result={"revision": 1},
    )
    assert first["state"] == second["state"] == "committed"
    assert (tmp_path / "research_map/context.json").is_file()


def test_request_reuse_with_different_payload_is_rejected(tmp_path: Path) -> None:
    coordinator = TransactionCoordinator(tmp_path)
    coordinator.commit_files("request-1", "research.change", {"value": 1}, writes={"a.json": {}}, result={})
    try:
        coordinator.commit_files("request-1", "research.change", {"value": 2}, writes={"a.json": {}}, result={})
    except TransactionError as error:
        assert str(error) == "transaction_id_reused"
    else:
        raise AssertionError("request reuse must fail")


def test_read_path_recovers_a_durable_committing_decision(tmp_path: Path) -> None:
    coordinator = TransactionCoordinator(tmp_path)
    writes = {"recovered.json": {"ok": True}}
    _atomic_json(coordinator._receipt_path("request-1"), {
        "schema_version": "agent_transaction/1", "transaction_id": "txn_request-1",
        "request_id": "request-1", "operation": "test", "request_digest": _digest({"operation": "test", "payload": {}}),
        "state": "committing", "writes": writes, "writes_digest": _digest(writes), "result": {},
    })
    assert coordinator.get("request-1")["state"] == "committed"
    assert (tmp_path / "recovered.json").read_text().strip() == '{\n  "ok": true\n}'


def test_recovery_pointer_before_decision_does_not_commit(tmp_path: Path, monkeypatch) -> None:
    coordinator = TransactionCoordinator(tmp_path)
    coordinator.prepare("request-1", "test", {}, writes={"result.json": {"ok": True}}, result={"ok": True})
    receipt_path = coordinator._receipt_path("request-1")

    def interrupted_decision(path, value):
        if path == receipt_path and value.get("state") == "committing":
            raise OSError("simulated interruption before durable decision")
        _atomic_json(path, value)

    with monkeypatch.context() as patch:
        patch.setattr(transactions, "_atomic_json", interrupted_decision)
        with pytest.raises(OSError, match="before durable decision"):
            coordinator.commit("request-1")
    assert coordinator._recovery_pointer(receipt_path).is_file()
    restarted = TransactionCoordinator(tmp_path)
    assert restarted.get("request-1")["state"] == "prepared"
    assert not (tmp_path / "result.json").exists()
    assert not coordinator._recovery_pointer(receipt_path).exists()
    assert restarted.commit("request-1")["state"] == "committed"
    assert (tmp_path / "result.json").is_file()


def test_recovery_replays_partially_applied_decision(tmp_path: Path, monkeypatch) -> None:
    coordinator = TransactionCoordinator(tmp_path)
    writes = {"first.json": {"revision": 1}, "second.json": {"revision": 1}}
    coordinator.prepare("request-1", "test", {}, writes=writes, result={"revision": 1})

    def interrupted_write(path, value):
        if path == tmp_path / "second.json":
            raise OSError("simulated interruption after first write")
        _atomic_json(path, value)

    with monkeypatch.context() as patch:
        patch.setattr(transactions, "_atomic_json", interrupted_write)
        with pytest.raises(OSError, match="after first write"):
            coordinator.commit("request-1")
    assert (tmp_path / "first.json").is_file()
    assert not (tmp_path / "second.json").exists()
    restarted = TransactionCoordinator(tmp_path)
    receipt = restarted.get("request-1")
    assert receipt["state"] == "committed"
    assert transactions.read_json(tmp_path / "second.json") == {"revision": 1}
    assert not restarted._recovery_pointer(restarted._receipt_path("request-1")).exists()
    assert restarted.commit("request-1") == receipt


def test_recovery_removes_stale_pointer_without_reapplying_committed_files(tmp_path: Path, monkeypatch) -> None:
    coordinator = TransactionCoordinator(tmp_path)
    coordinator.prepare("request-1", "test", {}, writes={"result.json": {"ok": True}}, result={})
    with monkeypatch.context() as patch:
        patch.setattr(coordinator, "_clear_recovery_pointer", lambda _path: None)
        coordinator.commit("request-1")
    pointer = coordinator._recovery_pointer(coordinator._receipt_path("request-1"))
    assert pointer.is_file()
    original_mtime = (tmp_path / "result.json").stat().st_mtime_ns
    TransactionCoordinator(tmp_path).recover()
    assert not pointer.exists()
    assert (tmp_path / "result.json").stat().st_mtime_ns == original_mtime


def test_interrupted_recovery_index_bootstrap_can_resume(tmp_path: Path, monkeypatch) -> None:
    coordinator = TransactionCoordinator(tmp_path)
    index_path = tmp_path / transactions._RECOVERY_INDEX

    def interrupted_bootstrap(path, value):
        if path == index_path:
            raise OSError("simulated interruption before index publication")
        _atomic_json(path, value)

    with monkeypatch.context() as patch:
        patch.setattr(transactions, "_atomic_json", interrupted_bootstrap)
        with pytest.raises(OSError, match="before index publication"):
            coordinator.recover()
    assert (tmp_path / transactions._WRITER_MARKER).is_file()
    assert not index_path.exists()
    assert TransactionCoordinator(tmp_path).recover()["recovered"] is True
    assert transactions.read_json(index_path)["writer_version"] == 2


def test_indexed_recovery_does_not_parse_committed_history(tmp_path: Path, monkeypatch) -> None:
    coordinator = TransactionCoordinator(tmp_path)
    # Bootstrap old history once; later reads must scale with unfinished work.
    for index in range(500):
        _atomic_json(coordinator._receipt_path(f"history-{index}"), {
            "schema_version": "agent_transaction/1", "state": "committed", "result": {"index": index},
        })
    coordinator.recover()
    parsed_paths = []
    original_read = coordinator._read

    def counted_read(path):
        parsed_paths.append(path)
        return original_read(path)

    monkeypatch.setattr(coordinator, "_read", counted_read)
    assert coordinator.get("history-499")["result"] == {"index": 499}
    assert parsed_paths == [tmp_path / transactions._WRITER_MARKER, coordinator._receipt_path("history-499")]
    # Old v1 writers scan the root journal and reject this schema, so they
    # cannot publish unindexed committing decisions after migration.
    assert original_read(tmp_path / transactions._WRITER_MARKER)["schema_version"] == "agent_transaction/2"


def test_recovery_pointer_without_receipt_fails_closed(tmp_path: Path) -> None:
    coordinator = TransactionCoordinator(tmp_path)
    coordinator.recover()
    path = coordinator._receipt_path("missing-request")
    _atomic_json(coordinator._recovery_pointer(path), {
        "schema_version": "transaction-recovery-pointer/1", "receipt": path.name,
    })
    with pytest.raises(TransactionError, match="transaction_recovery_receipt_missing"):
        coordinator.recover()
