"""Domain-neutral checks shared by validation, checkpoints and writes."""
from __future__ import annotations
from .operation_registry import GATE_CONTRACT


def _validate_gate_shape(value, kind):
    from jsonschema import Draft202012Validator
    error = next(Draft202012Validator(GATE_CONTRACT[kind]).iter_errors(value), None)
    if error:
        raise ValueError(f"gate_{kind}_invalid: {error.message}")

TERMINAL_ATTEMPTS = frozenset({"succeeded", "failed", "timed_out", "cancelled"})


def active_attempts(context):
    return [a["id"] for a in context.get("attempts", []) if a.get("state") not in TERMINAL_ATTEMPTS or a.get("metadata", {}).get("execution_conflict")]


def validate_context(context):
    issues = []
    active = active_attempts(context)
    if context.get("disposition") == "terminal" and active:
        issues.append({"code": "terminal_with_active_attempts", "refs": active})
    attempts = {a["id"]: a for a in context.get("attempts", [])}
    for attempt in attempts.values():
        if attempt.get("metadata", {}).get("execution_conflict"):
            issues.append({"code": "job_terminal_conflict", "refs": [attempt["id"]], "recovery": "job_reconcile"})
    artifacts = {a["id"]: a for a in context.get("artifacts", [])}
    gates = {g["id"]: g for g in context.get("gates", [])}
    for node in context.get("nodes", []):
        if node.get("state") != "closed":
            continue
        pending = [a["id"] for a in attempts.values() if a.get("node_id") == node["id"] and a["id"] in active]
        if pending:
            issues.append({"code": "closed_node_with_active_attempts", "refs": [node["id"], *pending]})
        if node.get("outcome") == "completed":
            if not node.get("gate_ids") and not node.get("completion_exemption"):
                issues.append({"code": "completion_conditions_required", "refs": [node["id"]]})
            for gate_id in node.get("gate_ids", []):
                if gate_id not in gates or not gate_evaluation_current(context, gates[gate_id]):
                    issues.append({"code": "completed_gate_not_current", "refs": [node["id"], gate_id],
                                   "recovery": "reassess the Gate against current receipts, or correct the closed outcome to inconclusive with a summary"})
    for record in context.get("attempt_interpretations", []):
        attempt = attempts.get(record.get("attempt_ref"))
        if attempt is None:
            issues.append({"code": "interpretation_attempt_missing", "refs": [record["id"]]})
            continue
        if record.get("review_state") == "needs_review":
            issues.append({"code": "interpretation_stale", "refs": [record["id"]]})
        for ref in record.get("direct_evidence_refs", []):
            if not belongs_to_attempt(artifacts, ref, attempt["id"]):
                issues.append({"code": "evidence_producer_mismatch", "refs": [record["id"], ref, attempt["id"]]})
    return {"schema_version": "research-validation/2", "valid": not issues,
            "revision": context.get("revision", 0), "issues": issues}


def belongs_to_attempt(artifacts, artifact_id, attempt_id, seen=None):
    """Follow only executed derivations; descriptors are not results."""
    seen = set() if seen is None else seen
    if artifact_id in seen:
        return False
    seen.add(artifact_id)
    artifact = artifacts.get(artifact_id)
    if artifact is None:
        return False
    if artifact.get("producer_attempt_id") == attempt_id:
        return True
    if not artifact.get("metadata", {}).get("derivation_executed"):
        return False
    return any(belongs_to_attempt(artifacts, ref, attempt_id, seen)
               for ref in artifact.get("input_artifact_ids", []))


def gate_evaluation_current(context, gate):
    if not gate.get('evaluations'):
        return False
    evaluation = gate['evaluations'][-1]
    if evaluation.get('gate_version') != gate.get('version') or evaluation.get('verdict') != 'pass':
        return False
    attempts = {a['id']: a for a in context.get('attempts', [])}
    artifacts = {a['id']: a for a in context.get('artifacts', [])}
    if any(artifacts.get(ref, {}).get('sha256') != digest for ref, digest in evaluation.get('artifact_versions', {}).items()):
        return False
    return all(not attempts.get(attempt_id, {}).get('metadata', {}).get('execution_conflict') and attempts.get(attempt_id, {}).get('metadata', {}).get('latest_result_receipt_ref') == receipt_id
               for attempt_id, receipt_id in evaluation.get('result_versions', {}).items())


def evaluate_criteria(root, context, gate, operation):
    """Validate provenance and compute the aggregate; never trust machine verdicts from JSON."""
    import json
    import re
    assessments = operation.get('assessments', [])
    if not isinstance(assessments, list) or any(not isinstance(a, dict) for a in assessments):
        raise ValueError('gate_assessments_required: expected an array of criterion assessments')
    by_id = {item.get('criterion_id'): item for item in assessments if isinstance(item, dict)}
    if len(by_id) != len(assessments) or set(by_id) != {c['id'] for c in gate['criteria']}:
        raise ValueError('gate_assessments_required: assess every current criterion exactly once')
    result_versions = {}
    verdicts = []
    for criterion in gate['criteria']:
        assessment = by_id[criterion['id']]
        verdict = assessment.get('verdict')
        if criterion['source_type'] == 'agent_assessment':
            if verdict not in {'pass', 'fail', 'inconclusive', 'blocked'}:
                raise ValueError('gate_assessment_verdict_invalid: supply verdict=pass|fail|inconclusive|blocked')
            if not isinstance(assessment.get('reason'), str) or not assessment['reason'].strip():
                raise ValueError('gate_agent_assessment_requires_reason')
        else:
            ref = assessment.get('result_receipt_ref', '')
            if not re.fullmatch(r'result_[0-9a-f]{64}', ref):
                raise ValueError('gate_result_receipt_required')
            receipt = json.loads((root / 'operations/results' / (ref + '.json')).read_text())
            attempt = next((a for a in context['attempts'] if a['id'] == receipt['attempt_id']), None)
            if not attempt or attempt.get('metadata', {}).get('execution_conflict') or attempt.get('metadata', {}).get('latest_result_receipt_ref') != ref:
                raise ValueError('gate_result_receipt_stale')
            node = next(n for n in context['nodes'] if n['id'] == attempt['node_id'])
            if ((gate['scope'] == 'node' and gate['target_id'] != node['id'])
                    or (gate['scope'] == 'claim' and gate['target_id'] not in node['claim_ids'])):
                raise ValueError('gate_result_scope_mismatch')
            result_versions[attempt['id']] = ref
            if criterion['source_type'] == 'runtime_fact':
                fact = criterion.get('fact')
                if fact == 'execution_succeeded':
                    verdict = 'pass' if receipt['execution_state'] == 'succeeded' else 'fail'
                elif fact == 'outputs_collected':
                    verdict = 'pass' if receipt['collection_state'] == 'complete' else 'inconclusive'
                else:
                    raise ValueError('gate_runtime_fact_invalid')
            else:
                validation = receipt.get('validator_result')
                if not validation or validation['id'] != criterion.get('validator_id'):
                    raise ValueError('gate_validator_receipt_required')
                if validation['version'] != criterion.get('validator_version'):
                    raise ValueError('gate_validator_version_mismatch')
                for producer_id, version in validation.get('input_result_versions', {}).items():
                    producer = next(a for a in context['attempts'] if a['id'] == producer_id)
                    if producer.get('metadata', {}).get('latest_result_receipt_ref') != version:
                        raise ValueError('gate_validator_input_stale')
                    result_versions[producer_id] = version
                artifacts = {a['id']: a for a in context['artifacts']}
                for artifact_id, digest in validation['input_versions'].items():
                    if artifacts.get(artifact_id, {}).get('sha256') != digest:
                        raise ValueError('gate_validator_input_stale')
                verdict = validation['verdict']
            if assessment.get('verdict') is not None and assessment['verdict'] != verdict:
                raise ValueError('gate_machine_verdict_mismatch')
        _validate_gate_shape(assessment, 'assessment')
        verdicts.append(verdict)
    aggregate = 'pass' if all(v == 'pass' for v in verdicts) else next(v for v in ('fail', 'blocked', 'inconclusive') if v in verdicts)
    if operation.get('verdict') != aggregate:
        raise ValueError('gate_aggregate_verdict_mismatch')
    return result_versions


def validate_criteria(criteria):
    if not isinstance(criteria, list) or not criteria or any(not isinstance(c, dict) for c in criteria):
        raise ValueError('gate_criteria_required')
    if len({c.get('id') for c in criteria}) != len(criteria):
        raise ValueError('gate_criteria_ids_must_be_unique')
    for criterion in criteria:
        if not isinstance(criterion.get('id'), str) or not criterion['id'].strip():
            raise ValueError('gate_criterion_id_required')
        if criterion.get('source_type') not in {'runtime_fact', 'validator_result', 'agent_assessment'}:
            raise ValueError('gate_criterion_source_required')
        if criterion['source_type'] == 'validator_result' and not all(criterion.get(k) for k in ('validator_id', 'validator_version')):
            raise ValueError('gate_validator_identity_required')
        if criterion['source_type'] == 'runtime_fact' and criterion.get('fact') not in {'execution_succeeded', 'outputs_collected'}:
            raise ValueError('gate_runtime_fact_invalid')
        _validate_gate_shape(criterion, 'criterion')


def belongs_to_result(artifacts, artifact_id, result_refs, seen=None):
    if artifact_id in result_refs:
        return True
    seen = set() if seen is None else seen
    if artifact_id in seen:
        return False
    seen.add(artifact_id)
    artifact = artifacts.get(artifact_id, {})
    return bool(artifact.get('metadata', {}).get('derivation_executed')) and any(
        belongs_to_result(artifacts, ref, result_refs, seen) for ref in artifact.get('input_artifact_ids', []))
