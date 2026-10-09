"""Compose runtime-owned facts with Memory without inverting ownership."""
import re
from pathlib import Path
from research_agent.foundation.transactions import TransactionCoordinator, read_json
from research_agent.foundation.path_safety import path_has_symlink
from research_agent.research import retrieval, views
from research_agent.research.records import workspace


def jobs(root):
    output = []
    for path in sorted((Path(root) / 'operations/jobs').glob('*.json')):
        intent = read_json(path)
        try:
            current = read_json(Path(root) / 'operations/executions' / (intent['job_id'] + '.json'))
        except FileNotFoundError:
            current = {}
        output.append({k: current.get(k, intent.get(k)) for k in ('job_id', 'node_id', 'node_revision', 'state', 'collection_state', 'latest_result_receipt_ref', 'error', 'execution_conflict')})
        output[-1]['state'] = current.get('state', 'unknown')
        output[-1]['collection_state'] = current.get('collection_state', 'not_collected')
        output[-1]['read'] = {'tool': 'job_status', 'job_id': intent['job_id']}
    return output


def read(root, *, ref=None, offset=0, limit=16000, session_id=None, event_ids=(), focus_node_ids=(), field=None):
    from .job_state import project_events
    from .job_monitor import assess
    with TransactionCoordinator(root).locked():
        workspace(root)
        errors = project_events(root)
        current = jobs(root)
        if ref:
            return retrieval.read(root, ref=ref, offset=offset, limit=limit, session_id=session_id, jobs=current, field=field)
        events = [assess(root, event_id, session_id)['event'] for event_id in event_ids]
        return views.build_snapshot(root, max_bytes=max(2048, limit), session_id=session_id, focus_node_ids=focus_node_ids,
                                    jobs=current, events=events, projection={'pending': len(errors), 'errors': errors[:3]})


def reference_details(root, request):
    from .references import resolve_artifact_reference
    from research_agent.artifacts.registry import read_manifest
    details = {}
    refs = request.get('input_refs', []) + request.get('inputs', []) + request.get('evidence_refs', [])
    refs += [item.get('artifact_ref') for item in request.get('files', []) if isinstance(item, dict)]
    for ref in refs:
        if not isinstance(ref, str):
            raise ValueError('reference_invalid')
        if ref.startswith('record_'):
            from research_agent.research.records import record
            fact = record(root, ref)
            data = fact['data']
            if fact['origin'] == 'runtime' and fact['kind'] == 'job':
                details[ref] = {'kind': 'runtime_fact', 'research_binding': data.get('metadata', {}).get('research_binding'),
                                'input_refs': list(data.get('metadata', {}).get('input_evidence_basis', {}))}
            continue
        if ref.startswith(('node_', 'result_', 'note_', 'user_')):
            continue
        if re.fullmatch(r'job_result_[a-f0-9]{64}', ref):
            path = Path(root) / 'operations/results' / (ref + '.json')
            if path_has_symlink(path):
                raise ValueError('reference_symlink')
            receipt = read_json(path)
            execution = read_json(Path(root) / 'operations/executions' / (receipt['job_id'] + '.json'))
            details[ref] = {'kind': 'collection_receipt', 'research_binding': execution.get('metadata', {}).get('research_binding'),
                            'input_refs': list(execution.get('metadata', {}).get('input_evidence_basis', {}))}
        elif re.fullmatch(r'job_[A-Za-z0-9_.:-]{1,200}', ref):
            path = Path(root) / 'operations/executions' / (ref + '.json')
            if path_has_symlink(path):
                raise ValueError('reference_symlink')
            execution = read_json(path)
            details[ref] = {'kind': 'job', 'research_binding': execution.get('metadata', {}).get('research_binding'),
                            'input_refs': list(execution.get('metadata', {}).get('input_evidence_basis', {}))}
        else:
            identity = resolve_artifact_reference(root, ref)
            material = read_manifest(root, identity)
            provenance = material.get('provenance', {})
            binding = {k: provenance[k] for k in ('node_id', 'node_revision') if k in provenance}
            details[ref] = {'kind': 'artifact', 'artifact_id': identity, 'sha256': material['sha256'],
                            'research_binding': binding if binding.get('node_id') else None}
    return details
