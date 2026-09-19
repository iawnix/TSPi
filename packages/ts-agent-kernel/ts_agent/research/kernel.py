"""Persistence and transaction boundary for the canonical ResearchMap."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable

import fcntl

from .model import (
    ClaimGate,
    ClaimStatus,
    FactFinding,
    FindingKind,
    FindingStatus,
    GateScope,
    GateVerdict,
    IssueFinding,
    NodeGate,
    NodeOutcome,
    NodeState,
    ResearchClaim,
    ResearchMap,
    ResearchModelError,
    ResearchNode,
    ResearchPhase,
)


MAP_FILE = "research_map.json"
TRANSACTION_FILE = "transactions.jsonl"
LOCK_FILE = ".research-map.lock"


class ResearchKernelError(RuntimeError):
    """Raised when a ResearchMap cannot be loaded or committed."""


class ResearchKernel:
    """Own one canonical ResearchMap snapshot on disk.

    Execution systems may write Attempt and Artifact records under a Node's
    directory, but only this boundary changes the scientific map.
    """

    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().absolute()
        self.path = self.root / MAP_FILE

    def load(self) -> ResearchMap:
        with self._lock():
            return self._load_unlocked()

    def _load_unlocked(self) -> ResearchMap:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ResearchKernelError("research_map.json must contain an object")
            return ResearchMap.from_dict(value)
        except FileNotFoundError as exc:
            raise ResearchKernelError(f"ResearchMap does not exist: {self.path}") from exc
        except (OSError, json.JSONDecodeError, ResearchModelError) as exc:
            raise ResearchKernelError(f"cannot load ResearchMap: {exc}") from exc

    def save(self, research_map: ResearchMap) -> ResearchMap:
        with self._lock():
            return self._save_unlocked(research_map)

    def _save_unlocked(self, research_map: ResearchMap) -> ResearchMap:
        research_map.validate()
        self.root.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(research_map.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        fd, temporary_name = tempfile.mkstemp(prefix="research-map-", suffix=".json", dir=self.root)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, self.path)
        except OSError as exc:
            try:
                os.unlink(temporary_name)
            except OSError:
                pass
            raise ResearchKernelError(f"cannot save ResearchMap: {exc}") from exc
        return research_map

    def transact(self, change: Callable[[ResearchMap], Any]) -> ResearchMap:
        with self._lock():
            research_map = self._load_unlocked()
            change(research_map)
            research_map.revision += 1
            saved = self._save_unlocked(research_map)
            self._append_transaction_unlocked({"kind": "transact", "revision": saved.revision})
            return saved

    def apply(self, change_set: dict[str, Any]) -> dict[str, Any]:
        """Apply one small, explicit ChangeSet to the canonical ResearchMap."""

        if not isinstance(change_set, dict):
            raise ResearchKernelError("ChangeSet must be an object")
        allowed_fields = {"schema_version", "rationale", "basis_refs", "expected_revision", "operations"}
        unknown_fields = sorted(set(change_set) - allowed_fields)
        if unknown_fields:
            raise ResearchKernelError("ChangeSet contains unsupported fields: " + ", ".join(unknown_fields))
        operations = change_set.get("operations")
        if not isinstance(operations, list) or not operations:
            raise ResearchKernelError("ChangeSet.operations must be a non-empty list")
        expected_revision = change_set.get("expected_revision")
        with self._lock():
            current = self._load_unlocked()
            if expected_revision is not None and expected_revision != current.revision:
                raise ResearchKernelError(
                    f"ResearchMap revision mismatch: expected {expected_revision}, current {current.revision}"
                )
            # Work on a detached copy so a failed operation never mutates the loaded map.
            draft = ResearchMap.from_dict(current.to_dict())
            created: list[str] = []
            for operation in operations:
                if not isinstance(operation, dict):
                    raise ResearchKernelError("ChangeSet operations must be objects")
                try:
                    created.extend(_apply_operation(draft, operation))
                except ResearchKernelError:
                    raise
                except (ResearchModelError, TypeError, ValueError) as exc:
                    raise ResearchKernelError(str(exc)) from exc
            draft.revision = current.revision + 1
            self._save_unlocked(draft)
            result = {
                "schema_version": "research-change-result/1",
                "map_id": draft.map_id,
                "revision": draft.revision,
                "created_ids": created,
                "operation_count": len(operations),
            }
            self._append_transaction_unlocked({"kind": "change_set", **result})
            return result

    def _append_transaction_unlocked(self, record: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / TRANSACTION_FILE
        payload = json.dumps({**record, "schema_version": "research-transaction/1"}, ensure_ascii=False, sort_keys=True) + "\n"
        try:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as exc:
            raise ResearchKernelError(f"cannot append ResearchMap transaction: {exc}") from exc

    @contextmanager
    def _lock(self):
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / LOCK_FILE
        handle = path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            yield
        except OSError as exc:
            raise ResearchKernelError(f"ResearchMap lock failed: {exc}") from exc
        finally:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                handle.close()


def _apply_operation(research_map: ResearchMap, operation: dict[str, Any]) -> list[str]:
    from ts_agent.workspace.operation_registry import validate_input_operation_keys

    try:
        validate_input_operation_keys(operation)
    except Exception as exc:
        raise ResearchKernelError(str(exc)) from exc
    kind = operation.get("type")
    created_at = str(operation.get("created_at") or _now())
    if kind == "create_phase":
        phase = ResearchPhase(
            id=_string(operation, "id"),
            created_at=created_at,
            title=_string(operation, "title"),
            objective=str(operation.get("objective", "")),
            metadata=dict(operation.get("metadata", {})),
        )
        research_map.add_phase(phase)
        return [phase.id]
    if kind == "create_claim":
        claim = ResearchClaim(
            id=_string(operation, "id"),
            created_at=created_at,
            statement=_string(operation, "statement"),
            status=ClaimStatus(operation.get("status", ClaimStatus.PROPOSED)),
            predictions=_strings(operation.get("predictions", []), "predictions"),
            falsifiers=_strings(operation.get("falsifiers", []), "falsifiers"),
            metadata=dict(operation.get("metadata", {})),
        )
        research_map.add_claim(claim)
        return [claim.id]
    if kind == "create_node":
        node = ResearchNode(
            id=_string(operation, "id"),
            created_at=created_at,
            title=_string(operation, "title"),
            objective=_string(operation, "objective"),
            phase_id=operation.get("phase_id"),
            claim_ids=_strings(operation.get("claim_ids", []), "claim_ids"),
            dependency_ids=_strings(operation.get("dependency_ids", []), "dependency_ids"),
            metadata=dict(operation.get("metadata", {})),
        )
        research_map.add_node(node)
        return [node.id]
    if kind == "create_finding":
        finding_id = _string(operation, "id")
        common = {
            "id": finding_id,
            "created_at": created_at,
            "node_id": _string(operation, "node_id"),
            "statement": _string(operation, "statement"),
            "claim_ids": _strings(operation.get("claim_ids", []), "claim_ids"),
            "source_refs": _strings(operation.get("source_refs", []), "source_refs"),
            "metadata": dict(operation.get("metadata", {})),
        }
        kind_value = FindingKind(operation.get("kind"))
        if kind_value is FindingKind.FACT:
            finding = FactFinding(
                **common,
                value=operation.get("value"),
                datatype=str(operation.get("datatype", "json")),
                unit=operation.get("unit"),
                provenance=dict(operation.get("provenance", {})),
            )
        else:
            finding = IssueFinding(
                **common,
                status=FindingStatus(operation.get("status", FindingStatus.OPEN)),
                severity=str(operation.get("severity", "warning")),
                resolution=operation.get("resolution"),
            )
        research_map.add_finding(finding)
        return [finding.id]
    if kind == "create_gate":
        gate_id = _string(operation, "id")
        scope = GateScope(operation.get("scope"))
        gate_type = NodeGate if scope is GateScope.NODE else ClaimGate
        gate = gate_type(
            id=gate_id,
            created_at=created_at,
            target_id=_string(operation, "target_id"),
            criteria=list(operation.get("criteria", [])),
            metadata=dict(operation.get("metadata", {})),
        )
        research_map.add_gate(gate)
        return [gate.id]
    if kind == "evaluate_gate":
        research_map.evaluate_gate(
            _string(operation, "gate_id"),
            GateVerdict(operation.get("verdict")),
            checked_at=created_at,
            message=str(operation.get("message", "")),
            evidence_refs=_strings(operation.get("evidence_refs", []), "evidence_refs"),
        )
        return []
    if kind == "set_node_state":
        outcome = operation.get("outcome")
        research_map.transition_node(
            _string(operation, "node_id"),
            NodeState(operation.get("state")),
            outcome=NodeOutcome(outcome) if outcome is not None else None,
            summary=operation.get("summary"),
        )
        return []
    if kind == "set_claim_status":
        claim_id = _string(operation, "claim_id")
        try:
            research_map.claims[claim_id].status = ClaimStatus(operation.get("status"))
        except KeyError as exc:
            raise ResearchKernelError(f"unknown claim {claim_id}") from exc
        return []
    if kind == "relate_claims":
        research_map.add_claim_relation(
            _string(operation, "source_id"),
            _string(operation, "target_id"),
            _string(operation, "relation"),
        )
        return []
    if kind == "set_focus":
        claim_ids = _strings(operation.get("claim_ids", []), "claim_ids")
        node_ids = _strings(operation.get("node_ids", []), "node_ids")
        _require_existing(claim_ids, research_map.claims, "focus claim_ids")
        _require_existing(node_ids, research_map.nodes, "focus node_ids")
        research_map.focus_claim_ids = claim_ids
        research_map.focus_node_ids = node_ids
        return []
    raise ResearchKernelError(f"unsupported ResearchMap operation: {kind}")


def _string(value: dict[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise ResearchKernelError(f"operation field {key} must be a non-empty string")
    return item.strip()


def _strings(value: Any, key: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ResearchKernelError(f"operation field {key} must be a list of non-empty strings")
    return [item.strip() for item in value]


def _require_existing(refs: list[str], collection: dict[str, Any], label: str) -> None:
    missing = sorted(set(refs) - set(collection))
    if missing:
        raise ResearchKernelError(f"{label} references unknown ids: {', '.join(missing)}")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
