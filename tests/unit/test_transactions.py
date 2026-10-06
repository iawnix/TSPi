from pathlib import Path

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
