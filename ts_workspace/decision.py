"""Draft and validate revision-bound v4 research Decisions."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from pathlib import Path
from typing import Any

from ts_validation import builtin_predicate_registry, compile_gate_spec, evaluate_gate_spec, load_acceptance_profile

from .acceptance import (
    AcceptanceError,
    acceptance_policy_violations,
    latest_results_for_specs,
    relevant_findings,
)
from .context import compile_context
from .errors import ContractError
from .io import now_iso, read_json, sha256_json
from .operational import operational_snapshot
from .refs import (
    WorkspaceRefError,
    decision_ordinal,
    next_act_ordinal,
    next_claim_ordinal,
    next_decision_ordinal,
)
from .revision import workspace_revision
from .schema_validation import SchemaValidationError, validate_contract
from .state import (
    CLAIMS_FILE,
    CLAIM_RELATIONS_FILE,
    OBSERVATIONS_FILE,
    FINDINGS_FILE,
    RESEARCH_ACTS_FILE,
    VALIDATION_RESULTS_FILE,
    VALIDATION_SPECS_FILE,
)
from .transactions import recorded_decision_ids


CREATOR_PREFIXES = {
    "create_claim": "claim",
    "relate_claims": "rel",
    "start_act": "act",
    "record_observation": "obs",
    "record_finding": "fnd",
    "freeze_validation_spec": "gsp",
    "evaluate_validation": "val",
    "accept_claim": "acc",
}
INPUT_OPERATIONS = frozenset({
    *CREATOR_PREFIXES,
    "update_claim",
    "complete_act",
    "resolve_finding",
    "set_focus",
})


def draft_decision(
    root: str | Path,
    request: dict[str, Any],
    *,
    decision_id: str | None = None,
) -> dict[str, Any]:
    if not isinstance(request, dict):
        raise ContractError("decision draft request must be an object")
    try:
        validate_contract("decision_draft.schema.json", request)
    except SchemaValidationError as exc:
        raise ContractError(str(exc)) from exc
    root_path = Path(root).expanduser().resolve()
    try:
        if decision_id is None:
            allocated_decision_id = f"dec_{next_decision_ordinal(recorded_decision_ids(root_path))}"
        else:
            decision_ordinal(decision_id)
            allocated_decision_id = decision_id
    except WorkspaceRefError as exc:
        raise ContractError(str(exc)) from exc
    created_at = now_iso()
    raw_operations = request["operations"]
    state = _DraftState.load(root_path, decision_id=allocated_decision_id)
    allocations = _allocate_aliases(
        raw_operations,
        allocated_decision_id,
        existing_claim_ids=state.claims,
        existing_act_ids=state.acts,
    )
    registry = builtin_predicate_registry()
    operations: list[dict[str, Any]] = []

    for index, raw in enumerate(raw_operations):
        if not isinstance(raw, dict):
            raise ContractError(f"operations[{index}] must be an object")
        name = raw.get("op")
        if name not in INPUT_OPERATIONS:
            raise ContractError(f"unsupported draft operation: {name}")
        normalized = _normalize_operation(
            raw,
            allocations=allocations,
            decision_id=allocated_decision_id,
            created_at=created_at,
            state=state,
            registry=registry,
        )
        operations.append(normalized)
        state.apply(normalized)

    frontier = compile_context(root_path, mode="frontier")
    decision = {
        "schema_version": "ts-research-decision/1",
        "decision_id": allocated_decision_id,
        "rationale": request["rationale"].strip(),
        "basis_refs": list(request.get("basis_refs", [])),
        "context_ref": {
            "projection_id": frontier["projection_id"],
            "mode": "frontier",
            "workspace_revision": frontier["workspace_revision"],
        },
        "base_revision": frontier["workspace_revision"],
        "allocations": allocations,
        "operations": operations,
        "created_at": created_at,
    }
    validate_decision(decision)
    return {"decision": decision, "allocated_refs": allocations}


def validate_decision(decision: Any) -> dict[str, Any]:
    if not isinstance(decision, dict):
        raise ContractError("decision must be an object")
    try:
        validate_contract("decision.schema.json", decision)
    except SchemaValidationError as exc:
        raise ContractError(str(exc)) from exc
    expected_allocations: set[str] = set()
    for operation in decision["operations"]:
        identifier = _created_identifier(operation)
        if identifier is not None:
            expected_allocations.add(identifier)
    if set(decision["allocations"].values()) != expected_allocations:
        raise ContractError("decision allocations do not match created records")
    return decision


def validate_decision_binding(root: str | Path, decision: dict[str, Any]) -> None:
    value = validate_decision(decision)
    root_path = Path(root).expanduser().resolve()
    current_revision = workspace_revision(root_path)
    if value["base_revision"] != current_revision or value["context_ref"]["workspace_revision"] != current_revision:
        raise ContractError("decision base_revision is stale")
    frontier = compile_context(root_path, mode="frontier")
    if value["context_ref"]["projection_id"] != frontier["projection_id"]:
        raise ContractError("decision context projection is stale")
    pending = operational_snapshot(root_path)["pending_review_dispositions"]
    if pending:
        task_ids = ", ".join(str(item.get("task_id") or "unknown") for item in pending)
        raise ContractError(f"completed advisory Review requires a Root response before mutation: {task_ids}")


def _allocate_aliases(
    operations: list[Any],
    decision_id: str,
    *,
    existing_claim_ids: Any,
    existing_act_ids: Any,
) -> dict[str, str]:
    allocations: dict[str, str] = {}
    try:
        claim_ordinal = next_claim_ordinal(existing_claim_ids)
        act_ordinal = next_act_ordinal(existing_act_ids)
    except WorkspaceRefError as exc:
        raise ContractError(str(exc)) from exc
    for index, operation in enumerate(operations):
        if not isinstance(operation, dict):
            continue
        name = operation.get("op")
        prefix = CREATOR_PREFIXES.get(str(name))
        if prefix is None:
            if "local_ref" in operation:
                raise ContractError(f"{name} does not allocate local_ref")
            continue
        alias = operation.get("local_ref")
        if not isinstance(alias, str) or not alias or len(alias) > 64 or not alias[0].isalpha() or any(
            not (char.isalnum() or char in "_.-") for char in alias
        ):
            raise ContractError(f"operations[{index}].local_ref is invalid")
        if alias in allocations:
            raise ContractError(f"duplicate local_ref: {alias}")
        if prefix == "claim":
            allocations[alias] = f"claim_{claim_ordinal}"
            claim_ordinal += 1
        elif prefix == "act":
            allocations[alias] = f"act_{act_ordinal}"
            act_ordinal += 1
        else:
            digest = hashlib.sha256(f"{decision_id}:{index}:{name}:{alias}".encode("utf-8")).hexdigest()[:24]
            allocations[alias] = f"{prefix}_{digest}"
    return allocations


def _normalize_operation(
    raw: dict[str, Any],
    *,
    allocations: dict[str, str],
    decision_id: str,
    created_at: str,
    state: "_DraftState",
    registry: Any,
) -> dict[str, Any]:
    name = str(raw["op"])
    if name == "create_claim":
        _keys(raw, required={"op", "local_ref", "claimType", "statement"}, optional={"createdByAct", "assumptions", "falsifiers", "tags"})
        record = {
            "schema_version": "ts-claim/2",
            "claim_id": allocations[raw["local_ref"]],
            "claim_type": _string(raw["claimType"], "claimType", 128),
            "statement": _string(raw["statement"], "statement", 12000),
            "status": "proposed",
            "assumptions": _strings(raw.get("assumptions", []), "assumptions", 64, 2000),
            "falsifiers": _strings(raw.get("falsifiers", []), "falsifiers", 64, 2000),
            "tags": _unique_strings(raw.get("tags", []), "tags", 64, 128),
            "created_by_act": _optional_ref(raw.get("createdByAct"), allocations),
            "observation_refs": [],
            "validation_spec_refs": [],
            "validation_result_refs": [],
            "history": [],
            "created_by_decision": decision_id,
            "created_at": created_at,
        }
        return {"op": "append_claim", "record": record}
    if name == "relate_claims":
        _keys(raw, required={"op", "local_ref", "sourceClaimRef", "targetClaimRef", "relationType", "rationale"})
        return {
            "op": "append_claim_relation",
            "record": {
                "schema_version": "ts-claim-relation/1",
                "relation_id": allocations[raw["local_ref"]],
                "source_claim_ref": _ref(raw["sourceClaimRef"], allocations),
                "target_claim_ref": _ref(raw["targetClaimRef"], allocations),
                "relation_type": _string(raw["relationType"], "relationType", 128),
                "rationale": _string(raw["rationale"], "relation rationale", 8000),
                "created_by_decision": decision_id,
                "created_at": created_at,
            },
        }
    if name == "start_act":
        _keys(raw, required={"op", "local_ref", "objective"}, optional={"dependencyRefs", "claimRefs", "hypothesis", "tags"})
        act_id = allocations[raw["local_ref"]]
        return {
            "op": "append_research_act",
            "record": {
                "schema_version": "ts-research-act/3",
                "act_id": act_id,
                "objective": _string(raw["objective"], "objective", 8000),
                "status": "open",
                "dependency_refs": _refs(raw.get("dependencyRefs", []), allocations),
                "claim_refs": _refs(raw.get("claimRefs", []), allocations),
                "hypothesis": _hypothesis(raw.get("hypothesis")),
                "tags": _unique_strings(raw.get("tags", []), "tags", 64, 128),
                "observation_refs": [],
                "finding_refs": [],
                "validation_spec_refs": [],
                "validation_result_refs": [],
                "artifact_root": f"acts/{act_id}",
                "result": None,
                "created_by_decision": decision_id,
                "created_at": created_at,
            },
        }
    if name == "record_observation":
        _keys(
            raw,
            required={"op", "local_ref", "actRef", "conceptId", "subjectRef", "value", "datatype", "summary", "provenance"},
            optional={"unit", "qualifiers", "artifacts"},
        )
        provenance = raw["provenance"]
        if not isinstance(provenance, dict):
            raise ContractError("Observation provenance must be an object")
        _keys(provenance, required={"producer"}, optional={"producerVersion"}, label="Observation provenance")
        artifacts = _artifact_bindings(raw.get("artifacts", []))
        return {
            "op": "append_observation",
            "record": {
                "schema_version": "ts-observation/1",
                "observation_id": allocations[raw["local_ref"]],
                "created_by_act": _ref(raw["actRef"], allocations),
                "concept_id": _string(raw["conceptId"], "conceptId", 256),
                "subject_ref": _string(raw["subjectRef"], "subjectRef", 512),
                "value": deepcopy(raw["value"]),
                "datatype": raw["datatype"],
                "unit": raw.get("unit"),
                "qualifiers": deepcopy(raw.get("qualifiers", {})),
                "summary": _string(raw["summary"], "Observation summary", 4000),
                "artifact_refs": [item["artifactId"] for item in artifacts],
                "provenance": {
                    "producer": _string(provenance["producer"], "producer", 256),
                    "producer_version": provenance.get("producerVersion"),
                    "source_digests": {item["artifactId"]: item["sha256"] for item in artifacts},
                },
                "created_by_decision": decision_id,
                "created_at": created_at,
            },
        }
    if name == "record_finding":
        _keys(
            raw,
            required={"op", "local_ref", "findingType", "severity", "statement"},
            optional={"claimRefs", "actRefs", "basisObservationRefs"},
        )
        return {
            "op": "append_finding",
            "record": {
                "schema_version": "ts-finding/1",
                "finding_id": allocations[raw["local_ref"]],
                "finding_type": _string(raw["findingType"], "findingType", 128),
                "severity": raw["severity"],
                "status": "open",
                "statement": _string(raw["statement"], "Finding statement", 12000),
                "claim_refs": _refs(raw.get("claimRefs", []), allocations),
                "act_refs": _refs(raw.get("actRefs", []), allocations),
                "basis_observation_refs": _refs(raw.get("basisObservationRefs", []), allocations),
                "resolution": None,
                "created_by_decision": decision_id,
                "created_at": created_at,
            },
        }
    if name == "freeze_validation_spec":
        _keys(
            raw,
            required={"op", "local_ref", "actRef", "targetClaimRef", "dimension", "title"},
            optional={"template", "definition"},
        )
        request = {
            "dimension": raw["dimension"],
            "title": raw["title"],
            **({"template": _template_binding(raw["template"])} if "template" in raw else {}),
            **({"definition": deepcopy(raw["definition"])} if "definition" in raw else {}),
        }
        record = compile_gate_spec(
            request,
            spec_id=allocations[raw["local_ref"]],
            target_claim_ref=_ref(raw["targetClaimRef"], allocations),
            registry=registry,
            created_by_act=_ref(raw["actRef"], allocations),
            created_by_decision=decision_id,
            frozen_at=created_at,
        )
        return {"op": "append_validation_spec", "record": record}
    if name == "evaluate_validation":
        _keys(raw, required={"op", "local_ref", "actRef", "specRef", "observationRefs"})
        spec_ref = _ref(raw["specRef"], allocations)
        observation_refs = _refs(raw["observationRefs"], allocations)
        spec = state.specs.get(spec_ref)
        if spec is None:
            raise ContractError(f"evaluate_validation references an unavailable GateSpec: {spec_ref}")
        missing = sorted(set(observation_refs) - set(state.observations))
        if missing:
            raise ContractError("evaluate_validation references unavailable Observations: " + ", ".join(missing))
        record = evaluate_gate_spec(
            spec,
            [state.observations[ref] for ref in observation_refs],
            result_id=allocations[raw["local_ref"]],
            evaluated_by_act=_ref(raw["actRef"], allocations),
            evaluated_by_decision=decision_id,
            registry=registry,
            evaluated_at=created_at,
        )
        return {"op": "append_validation_result", "record": record}
    if name == "update_claim":
        _keys(raw, required={"op", "claimRef", "status", "summary"}, optional={"observationRefs", "validationResultRefs"})
        return {
            "op": "update_claim",
            "claim_ref": _ref(raw["claimRef"], allocations),
            "status": raw["status"],
            "summary": _string(raw["summary"], "Claim update summary", 8000),
            "observation_refs": _refs(raw.get("observationRefs", []), allocations),
            "validation_result_refs": _refs(raw.get("validationResultRefs", []), allocations),
            "updated_at": created_at,
        }
    if name == "complete_act":
        _keys(raw, required={"op", "actRef", "outcome", "summary"}, optional={"openQuestions"})
        return {
            "op": "complete_research_act",
            "act_ref": _ref(raw["actRef"], allocations),
            "outcome": raw["outcome"],
            "summary": _string(raw["summary"], "Act completion summary", 12000),
            "open_questions": _strings(raw.get("openQuestions", []), "openQuestions", 128, 2000),
            "completed_at": created_at,
        }
    if name == "resolve_finding":
        _keys(raw, required={"op", "findingRef", "status", "summary"}, optional={"basisObservationRefs"})
        return {
            "op": "resolve_finding",
            "finding_ref": _ref(raw["findingRef"], allocations),
            "status": raw["status"],
            "summary": _string(raw["summary"], "Finding resolution summary", 8000),
            "basis_observation_refs": _refs(raw.get("basisObservationRefs", []), allocations),
            "resolved_at": created_at,
        }
    if name == "set_focus":
        _keys(raw, required={"op", "claimRefs", "actRefs"})
        return {"op": "set_focus", "claim_refs": _refs(raw["claimRefs"], allocations), "act_refs": _refs(raw["actRefs"], allocations)}
    if name == "accept_claim":
        _keys(raw, required={"op", "local_ref", "claimRef", "profile", "summary"})
        claim_ref = _ref(raw["claimRef"], allocations)
        claim = state.claims.get(claim_ref)
        if claim is None:
            raise ContractError(f"accept_claim references an unavailable Claim: {claim_ref}")
        profile_binding = raw["profile"]
        if not isinstance(profile_binding, dict):
            raise ContractError("acceptance profile must be an object")
        _keys(profile_binding, required={"profileId", "version"}, label="acceptance profile")
        profile = load_acceptance_profile(str(profile_binding["profileId"]), str(profile_binding["version"]))
        attached_specs = sorted(
            spec_id for spec_id, spec in state.specs.items() if spec.get("target_claim_ref") == claim_ref
        )
        if not attached_specs:
            raise ContractError("accept_claim requires at least one attached GateSpec")
        try:
            selected_results = latest_results_for_specs(attached_specs, state.results)
        except AcceptanceError as exc:
            raise ContractError(f"accept_claim has {exc}") from exc
        finding_snapshot = relevant_findings(claim_ref, state.findings)
        selected_specs = [state.specs[spec_id] for spec_id in attached_specs]
        violations = acceptance_policy_violations(
            claim_snapshot=claim,
            profile=profile,
            specs=selected_specs,
            results=selected_results,
            findings=finding_snapshot,
        )
        if violations:
            raise ContractError("accept_claim policy failed: " + "; ".join(message for _, message in violations))
        latest_result_refs = [str(result["result_id"]) for result in selected_results]
        record = {
            "schema_version": "ts-acceptance-record/1",
            "acceptance_id": allocations[raw["local_ref"]],
            "claim_ref": claim_ref,
            "claim_snapshot": deepcopy(claim),
            "claim_digest": sha256_json(claim),
            "profile_ref": {"profile_id": profile["profile_id"], "version": profile["version"]},
            "profile_digest": sha256_json(profile),
            "validation_spec_refs": attached_specs,
            "validation_spec_digests": {spec["spec_id"]: sha256_json(spec) for spec in selected_specs},
            "validation_result_refs": latest_result_refs,
            "validation_result_digests": {result["result_id"]: sha256_json(result) for result in selected_results},
            "finding_snapshot": finding_snapshot,
            "finding_snapshot_digest": sha256_json(finding_snapshot),
            "summary": _string(raw["summary"], "acceptance summary", 12000),
            "decision_id": decision_id,
            "accepted_at": created_at,
        }
        record["acceptance_digest"] = sha256_json(record)
        return {"op": "accept_claim", "record": record}
    raise ContractError(f"unsupported draft operation: {name}")


class _DraftState:
    def __init__(self, *, decision_id: str, claims: dict[str, dict[str, Any]], relations: dict[str, dict[str, Any]], acts: dict[str, dict[str, Any]], observations: dict[str, dict[str, Any]], specs: dict[str, dict[str, Any]], results: dict[str, dict[str, Any]], findings: dict[str, dict[str, Any]]) -> None:
        self.decision_id = decision_id
        self.claims = claims
        self.relations = relations
        self.acts = acts
        self.observations = observations
        self.specs = specs
        self.results = results
        self.findings = findings

    @classmethod
    def load(cls, root: Path, *, decision_id: str) -> "_DraftState":
        return cls(
            decision_id=decision_id,
            claims=_map(read_json(root / CLAIMS_FILE)["claims"], "claim_id"),
            relations=_map(read_json(root / CLAIM_RELATIONS_FILE)["relations"], "relation_id"),
            acts=_map(read_json(root / RESEARCH_ACTS_FILE)["acts"], "act_id"),
            observations=_map(read_json(root / OBSERVATIONS_FILE)["observations"], "observation_id"),
            specs=_map(read_json(root / VALIDATION_SPECS_FILE)["specs"], "spec_id"),
            results=_map(read_json(root / VALIDATION_RESULTS_FILE)["results"], "result_id"),
            findings=_map(read_json(root / FINDINGS_FILE)["findings"], "finding_id"),
        )

    def apply(self, operation: dict[str, Any]) -> None:
        name = operation["op"]
        if name == "append_claim":
            record = deepcopy(operation["record"])
            self.claims[record["claim_id"]] = record
        elif name == "append_claim_relation":
            record = deepcopy(operation["record"])
            self.relations[record["relation_id"]] = record
        elif name == "append_research_act":
            record = deepcopy(operation["record"])
            self.acts[record["act_id"]] = record
        elif name == "append_observation":
            record = deepcopy(operation["record"])
            self.observations[record["observation_id"]] = record
            _append_unique(self.acts.get(record["created_by_act"], {}).get("observation_refs"), record["observation_id"])
        elif name == "append_finding":
            record = deepcopy(operation["record"])
            self.findings[record["finding_id"]] = record
            for act_ref in record["act_refs"]:
                _append_unique(self.acts.get(act_ref, {}).get("finding_refs"), record["finding_id"])
        elif name == "append_validation_spec":
            record = deepcopy(operation["record"])
            self.specs[record["spec_id"]] = record
            _append_unique(self.claims.get(record["target_claim_ref"], {}).get("validation_spec_refs"), record["spec_id"])
            _append_unique(self.acts.get(record["created_by_act"], {}).get("validation_spec_refs"), record["spec_id"])
        elif name == "append_validation_result":
            record = deepcopy(operation["record"])
            self.results[record["result_id"]] = record
            _append_unique(self.claims.get(record["target_claim_ref"], {}).get("validation_result_refs"), record["result_id"])
            _append_unique(self.acts.get(record["evaluated_by_act"], {}).get("validation_result_refs"), record["result_id"])
        elif name == "update_claim":
            claim = self.claims.get(operation["claim_ref"])
            if claim:
                claim["status"] = operation["status"]
                for ref in operation["observation_refs"]:
                    _append_unique(claim["observation_refs"], ref)
                for ref in operation["validation_result_refs"]:
                    _append_unique(claim["validation_result_refs"], ref)
                claim["history"].append({
                    "status": operation["status"],
                    "summary": operation["summary"],
                    "observation_refs": list(operation["observation_refs"]),
                    "validation_result_refs": list(operation["validation_result_refs"]),
                    "decision_id": self.decision_id,
                    "created_at": operation["updated_at"],
                })
        elif name == "complete_research_act":
            act = self.acts.get(operation["act_ref"])
            if act:
                act["status"] = operation["outcome"]
        elif name == "resolve_finding":
            finding = self.findings.get(operation["finding_ref"])
            if finding:
                finding["status"] = operation["status"]
                finding["resolution"] = {
                    "status": operation["status"],
                    "summary": operation["summary"],
                    "basis_observation_refs": list(operation["basis_observation_refs"]),
                    "decision_id": self.decision_id,
                    "resolved_at": operation["resolved_at"],
                }


def _created_identifier(operation: dict[str, Any]) -> str | None:
    record = operation.get("record")
    if not isinstance(record, dict):
        return None
    for key in ("claim_id", "relation_id", "act_id", "observation_id", "finding_id", "spec_id", "result_id", "acceptance_id"):
        if isinstance(record.get(key), str):
            return str(record[key])
    return None


def _ref(value: Any, allocations: dict[str, str]) -> str:
    if not isinstance(value, str) or not value:
        raise ContractError("reference must be a non-empty string")
    if value.startswith("$"):
        alias = value[1:]
        if alias not in allocations:
            raise ContractError(f"unknown local reference: {value}")
        return allocations[alias]
    return value


def _optional_ref(value: Any, allocations: dict[str, str]) -> str | None:
    return None if value is None else _ref(value, allocations)


def _refs(value: Any, allocations: dict[str, str]) -> list[str]:
    if not isinstance(value, list):
        raise ContractError("reference collection must be an array")
    refs = [_ref(item, allocations) for item in value]
    if len(refs) != len(set(refs)):
        raise ContractError("reference collection contains duplicates")
    return refs


def _keys(value: dict[str, Any], *, required: set[str], optional: set[str] | None = None, label: str = "operation") -> None:
    optional = optional or set()
    missing = sorted(required - set(value))
    unknown = sorted(set(value) - required - optional)
    if missing:
        raise ContractError(f"{label} is missing fields: " + ", ".join(missing))
    if unknown:
        raise ContractError(f"{label} contains unsupported fields: " + ", ".join(unknown))


def _string(value: Any, label: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ContractError(f"{label} must be a non-empty string up to {maximum} characters")
    return value.strip()


def _strings(value: Any, label: str, maximum_items: int, maximum_length: int) -> list[str]:
    if not isinstance(value, list) or len(value) > maximum_items:
        raise ContractError(f"{label} must be an array with at most {maximum_items} entries")
    return [_string(item, label, maximum_length) for item in value]


def _unique_strings(value: Any, label: str, maximum_items: int, maximum_length: int) -> list[str]:
    values = _strings(value, label, maximum_items, maximum_length)
    if len(values) != len(set(values)):
        raise ContractError(f"{label} contains duplicates")
    return values


def _hypothesis(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ContractError("hypothesis must be an object or null")
    _keys(value, required={"statement"}, optional={"assumptions", "predictions", "falsifiers"}, label="hypothesis")
    return {
        "statement": _string(value["statement"], "hypothesis statement", 8000),
        "assumptions": _strings(value.get("assumptions", []), "hypothesis assumptions", 64, 2000),
        "predictions": _strings(value.get("predictions", []), "hypothesis predictions", 64, 2000),
        "falsifiers": _strings(value.get("falsifiers", []), "hypothesis falsifiers", 64, 2000),
    }


def _artifact_bindings(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list) or len(value) > 64:
        raise ContractError("Observation artifacts must be an array with at most 64 entries")
    bindings = []
    for item in value:
        if not isinstance(item, dict):
            raise ContractError("Observation artifact binding must be an object")
        _keys(item, required={"artifactId", "sha256"}, label="Observation artifact binding")
        artifact_id = item["artifactId"]
        digest = item["sha256"]
        if not isinstance(artifact_id, str) or len(artifact_id) != 28 or not artifact_id.startswith("art_"):
            raise ContractError("Observation artifactId is invalid")
        if not isinstance(digest, str) or len(digest) != 71 or not digest.startswith("sha256:"):
            raise ContractError("Observation artifact digest is invalid")
        bindings.append({"artifactId": artifact_id, "sha256": digest})
    if len({item["artifactId"] for item in bindings}) != len(bindings):
        raise ContractError("Observation artifacts contain duplicate IDs")
    return bindings


def _template_binding(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError("template binding must be an object")
    _keys(value, required={"templateId", "version", "parameters"}, label="template binding")
    return {
        "template_id": _string(value["templateId"], "templateId", 128),
        "version": _string(value["version"], "template version", 64),
        "parameters": deepcopy(value["parameters"]),
    }


def _map(rows: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    return {str(row[key]): deepcopy(row) for row in rows if isinstance(row, dict) and isinstance(row.get(key), str)}


def _append_unique(values: Any, value: str) -> None:
    if isinstance(values, list) and value not in values:
        values.append(value)
