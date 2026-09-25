"""Persistence and transaction boundary for the canonical ResearchMap."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterable

import fcntl

from .model import (
    ClaimGate,
    ClaimStatus,
    ContinuationAction,
    ContinuationRecord,
    ContinuationScope,
    ContinuationStatus,
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
from .decisions import AttemptInterpretation, StrategyPlan, StrategyReview, TurnCheckpoint
from .evidence import (
    ArtifactManifest,
    AttemptRecord,
    EvidenceLink,
    EvidenceModelError,
    validate_interpretation_evidence,
    validate_map_evidence,
)
from .sqlite import ResearchSqliteError, ResearchSqliteRepository


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
        self.sqlite = ResearchSqliteRepository(self.root)

    def load(self) -> ResearchMap:
        with self._lock():
            return self._load_unlocked()

    def load_read_only(self) -> ResearchMap:
        """Load a map without creating the workspace lock file.

        Read-only consumers, such as TS Web, may be given a filesystem view
        where the workspace cannot be modified.  Map writes use an atomic
        replace, so reading the canonical document directly is safe without
        acquiring the write-capable lock used by the mutation boundary.
        """

        return self._load_unlocked()

    def _load_unlocked(self) -> ResearchMap:
        if self.sqlite.path.is_file():
            try:
                return self.sqlite.load_map()
            except ResearchSqliteError as exc:
                raise ResearchKernelError(str(exc)) from exc
        return self._load_json_unlocked()

    def _load_json_unlocked(self) -> ResearchMap:
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
        if self.sqlite.path.is_file():
            try:
                artifacts, links = self.sqlite.load_evidence_index()
                validate_map_evidence(research_map, artifacts, links)
                self.sqlite.save_snapshot(research_map)
            except (ResearchSqliteError, EvidenceModelError) as exc:
                raise ResearchKernelError(str(exc)) from exc
            self._save_json_unlocked(research_map)
            return research_map
        return self._save_json_unlocked(research_map)

    def _save_json_unlocked(self, research_map: ResearchMap) -> ResearchMap:
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

    def ensure_sqlite(self) -> dict[str, Any]:
        """Migrate an existing JSON workspace to the SQLite Kernel backend."""

        with self._lock():
            if self.sqlite.path.is_file():
                current = self.sqlite.load_map()
                return {"schema_version": "research-sqlite-bootstrap/1", "created": False, "revision": current.revision}
            current = self._load_json_unlocked()
            try:
                result = self.sqlite.bootstrap_from_json(current)
            except ResearchSqliteError as exc:
                raise ResearchKernelError(str(exc)) from exc
            self._save_json_unlocked(current)
            return result

    def commit_decisions(
        self,
        *,
        expected_revision: int | None = None,
        event_id: str | None = None,
        request_digest: str | None = None,
        rationale: str | None = None,
        basis_refs: Iterable[str] = (),
        strategy_plans: Iterable[StrategyPlan] = (),
        strategy_reviews: Iterable[StrategyReview] = (),
        interpretations: Iterable[AttemptInterpretation] = (),
        checkpoint: TurnCheckpoint | None = None,
    ) -> dict[str, Any]:
        """Commit Claim decisions and the current map in one SQLite transaction."""

        basis = list(basis_refs)
        interpretation_rows = list(interpretations)
        with self._lock():
            if not self.sqlite.path.is_file():
                current = self._load_json_unlocked()
                try:
                    self.sqlite.bootstrap_from_json(current)
                except ResearchSqliteError as exc:
                    raise ResearchKernelError(str(exc)) from exc
            replayed = bool(event_id and self.sqlite.has_event(event_id))
            current = self.sqlite.load_map()
            if not replayed:
                try:
                    artifacts, links = self.sqlite.load_evidence_index()
                    validate_map_evidence(current, artifacts, links)
                    for interpretation in interpretation_rows:
                        validate_interpretation_evidence(interpretation, artifacts, links)
                except (EvidenceModelError, ResearchSqliteError) as exc:
                    raise ResearchKernelError(str(exc)) from exc
            try:
                result = self.sqlite.commit(
                    current,
                    expected_revision=expected_revision,
                    event_id=event_id,
                    request_digest=request_digest,
                    rationale=rationale,
                    basis_refs=basis,
                    strategy_plans=strategy_plans,
                    strategy_reviews=strategy_reviews,
                    interpretations=interpretation_rows,
                    checkpoint=checkpoint,
                )
                saved = self.sqlite.load_map()
            except ResearchSqliteError as exc:
                raise ResearchKernelError(str(exc)) from exc
            self._save_json_unlocked(saved)
            if not replayed:
                self._append_transaction_unlocked({
                    "kind": "claim_decision",
                    **result,
                    "event_id": event_id,
                    "rationale": rationale,
                    "basis_refs": basis,
                })
            return result

    def decision_records(self, *, claim_id: str | None = None, limit: int = 128) -> dict[str, Any]:
        """Return bounded Claim decision records from the active backend."""

        if type(limit) is not int or not 1 <= limit <= 2048:
            raise ResearchKernelError("decision record limit must be an integer between 1 and 2048")

        if not self.sqlite.path.is_file():
            return {
                "schema_version": "research-decisions/1",
                "backend": "json",
                "map_id": self.load_read_only().map_id,
                "records": {key: [] for key in ("strategy_plans", "strategy_reviews", "attempt_interpretations", "turn_checkpoints")},
            }
        try:
            snapshot = self.sqlite.export_snapshot()
        except ResearchSqliteError as exc:
            raise ResearchKernelError(str(exc)) from exc
        records = snapshot["claim_decisions"]
        if claim_id is not None:
            records = {
                key: [item for item in values if claim_id in item.get("claim_ids", [item.get("claim_id")])]
                for key, values in records.items()
            }
        records = {key: values[:limit] for key, values in records.items()}
        return {
            "schema_version": "research-decisions/1",
            "backend": "sqlite",
            "map_id": snapshot["research_map"]["map_id"],
            "map_revision": snapshot["research_map"]["revision"],
            "records": records,
        }

    def register_evidence(
        self,
        *,
        attempts: Iterable[AttemptRecord] = (),
        artifacts: Iterable[ArtifactManifest] = (),
        links: Iterable[EvidenceLink] = (),
        event_id: str | None = None,
        request_digest: str | None = None,
    ) -> dict[str, Any]:
        """Admit Attempt/Artifact metadata and evidence links to the Kernel.

        The Kernel owns evidence identity and provenance; raw payloads remain
        in the workspace or object store.  Registration is deliberately
        separate from scientific interpretation and cannot create Findings.
        """

        attempt_rows = list(attempts)
        artifact_rows = list(artifacts)
        link_rows = list(links)
        with self._lock():
            if not self.sqlite.path.is_file():
                current = self._load_json_unlocked()
                try:
                    self.sqlite.bootstrap_from_json(current)
                except ResearchSqliteError as exc:
                    raise ResearchKernelError(str(exc)) from exc
            current = self.sqlite.load_map()
            try:
                for record in (*attempt_rows, *artifact_rows, *link_rows):
                    record.validate(current)
            except EvidenceModelError as exc:
                raise ResearchKernelError(str(exc)) from exc
            replayed = bool(event_id and self.sqlite.has_event(event_id))
            try:
                result = self.sqlite.register_evidence(
                    attempts=attempt_rows,
                    artifacts=artifact_rows,
                    links=link_rows,
                    event_id=event_id,
                    request_digest=request_digest,
                )
            except ResearchSqliteError as exc:
                raise ResearchKernelError(str(exc)) from exc
            if not replayed:
                self._append_transaction_unlocked({
                    "kind": "evidence_registration",
                    **result,
                    "event_id": event_id,
                })
            return result

    def evidence_records(
        self,
        *,
        record_type: str | None = None,
        node_id: str | None = None,
        artifact_id: str | None = None,
        subject_id: str | None = None,
        limit: int = 128,
    ) -> dict[str, Any]:
        """Return bounded Kernel-owned evidence metadata."""

        if not self.sqlite.path.is_file():
            return {
                "schema_version": "research-evidence/1",
                "backend": "json",
                "records": {key: [] for key in ([record_type] if record_type else ("attempt", "artifact", "link"))},
            }
        try:
            result = self.sqlite.list_evidence(
                record_type=record_type,
                node_id=node_id,
                artifact_id=artifact_id,
                subject_id=subject_id,
                limit=limit,
            )
        except ResearchSqliteError as exc:
            raise ResearchKernelError(str(exc)) from exc
        research_map = self.load_read_only()
        result["map_id"] = research_map.map_id
        result["map_revision"] = research_map.revision
        return result

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
            if self.sqlite.path.is_file():
                try:
                    artifacts, links = self.sqlite.load_evidence_index()
                    validate_map_evidence(draft, artifacts, links)
                except (EvidenceModelError, ResearchSqliteError) as exc:
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
    if kind == "set_continuation":
        continuation_id = _string(operation, "id")
        scope = ContinuationScope(operation.get("scope"))
        target_id = _string(operation, "target_id")
        action = ContinuationAction(_string(operation, "action"))
        request_id = operation.get("request_id")
        if request_id is not None and (not isinstance(request_id, str) or not request_id):
            raise ResearchKernelError("operation field request_id must be a non-empty string")
        existing = research_map.continuations.get(continuation_id)
        if existing is not None:
            if request_id is not None and existing.request_id == request_id:
                if (
                    existing.scope is scope
                    and existing.target_id == target_id
                    and existing.action == action
                ):
                    # A retried request must not create a second obligation or
                    # reset a resolution that was committed after the first
                    # request returned.
                    return []
            raise ResearchKernelError(f"continuation {continuation_id} already exists")
        if request_id is not None:
            for candidate in research_map.continuations.values():
                if candidate.request_id == request_id:
                    if (
                        candidate.scope is scope
                        and candidate.target_id == target_id
                        and candidate.action == action
                    ):
                        return []
                    raise ResearchKernelError(f"request_id {request_id} is already bound to another continuation")
        continuation = ContinuationRecord(
            id=continuation_id,
            created_at=created_at,
            scope=scope,
            target_id=target_id,
            action=action,
            status=ContinuationStatus(operation.get("status", ContinuationStatus.REQUIRED)),
            reason=operation.get("reason"),
            request_id=request_id,
            metadata=dict(operation.get("metadata", {})),
        )
        research_map.add_continuation(continuation)
        return [continuation.id]
    if kind == "resolve_continuation":
        continuation_id = _string(operation, "id")
        continuation = research_map.continuations.get(continuation_id)
        if continuation is None:
            raise ResearchKernelError(f"unknown continuation {continuation_id}")
        reason = operation["reason"] if "reason" in operation else continuation.reason
        request_id = operation["request_id"] if "request_id" in operation else continuation.request_id
        research_map.resolve_continuation(
            continuation_id,
            ContinuationStatus(operation.get("status")),
            reason=reason,
            request_id=request_id,
        )
        return []
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
