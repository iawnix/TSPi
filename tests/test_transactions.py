from __future__ import annotations

import json
from pathlib import Path

import pytest

from ts_agent.workspace.errors import ContractError
from ts_agent.workspace import transactions as transaction_module
from ts_agent.workspace.transactions import (
    commit_transaction,
    decision_log_result,
    recover_incomplete_transactions,
    transaction_status,
    workspace_lock,
)


def test_workspace_lock_rejects_symbolic_link(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    outside = tmp_path / "outside-lock"
    outside.write_text("", encoding="utf-8")
    (root / ".ts-workspace.lock").symlink_to(outside)

    with pytest.raises(ContractError, match="workspace lock contains a symbolic link"):
        with workspace_lock(root):
            pass


def test_transaction_recovery_rejects_symbolic_link_child(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    transaction_root = root / ".ts-transactions"
    transaction_root.mkdir(parents=True)
    outside = tmp_path / "outside-transaction"
    outside.mkdir()
    (transaction_root / "dec_1").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ContractError, match="transaction child contains a symbolic link"):
        recover_incomplete_transactions(root)


def test_transaction_recovery_wraps_invalid_prepare_json(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    transaction = root / ".ts-transactions" / "dec_1"
    transaction.mkdir(parents=True)
    (transaction / "prepare.json").write_text("not-json", encoding="utf-8")

    with pytest.raises(ContractError, match="dec_1 has an invalid prepare record"):
        recover_incomplete_transactions(root)


def test_transaction_recovery_rejects_mismatched_prepare_identity(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    transaction = root / ".ts-transactions" / "dec_1"
    transaction.mkdir(parents=True)
    (transaction / "prepare.json").write_text(
        json.dumps({"decision_id": "dec_2"}),
        encoding="utf-8",
    )

    with pytest.raises(ContractError, match="mismatched decision_id"):
        recover_incomplete_transactions(root)


def test_transaction_status_rejects_non_object_log_rows(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "transaction_log.jsonl").write_text("[]\n", encoding="utf-8")

    with pytest.raises(ContractError, match="transaction log row 1 must be a JSON object"):
        transaction_status(root, "dec_1")


def test_decision_log_result_rejects_non_object_log_rows(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "decision_log.jsonl").write_text("[]\n", encoding="utf-8")

    with pytest.raises(ContractError, match="decision log row 1 must be a JSON object"):
        decision_log_result(root, "dec_1")


def test_commit_rejects_unsafe_decision_id_before_creating_paths(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()

    with pytest.raises(ContractError, match="decision_id must match"):
        commit_transaction(root, {"decision_id": "dec_../outside"}, {}, {})


def test_commit_does_not_silently_remove_raced_transaction_symlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    original_append = transaction_module.append_jsonl

    def append_and_replace(path: Path, row: dict) -> None:
        original_append(path, row)
        if row.get("stage") == "committed":
            transaction = root / ".ts-transactions" / "dec_1"
            transaction.rename(root / ".ts-transactions" / "dec_1-real")
            transaction.symlink_to(outside, target_is_directory=True)

    monkeypatch.setattr(transaction_module, "append_jsonl", append_and_replace)

    with pytest.raises(ContractError, match="cleanup refused"):
        commit_transaction(
            root,
            {"decision_id": "dec_1", "operations": []},
            {root / "state.json": {"ok": True}},
            {"ok": True},
        )

    assert (root / "state.json").is_file()
    assert (root / ".ts-transactions" / "dec_1").is_symlink()
