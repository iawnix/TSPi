"""Runtime-owned Job observations and automatic research journal entries."""
import hashlib
import json
from pathlib import Path
from research_agent.foundation.transactions import read_json, write_json, workspace_transaction
from datetime import datetime, timezone

TERMINAL = {'succeeded', 'failed', 'timed_out', 'cancelled'}


def execution(root, job_id):
    return read_json(Path(root) / 'operations/executions' / (job_id + '.json'))


def list_executions(root, *, session_id=None, user_task_id=None, limit=50, cursor=None):
    """Read persisted Job observations and ownership without polling a platform."""
    from .job_monitor import read_binding
    root = Path(root)
    bindings = {row['job_id']: row for path in (root / 'operations/monitors').glob('*/binding.json')
                for row in [read_binding(path)]}
    rows = []
    for path in sorted((root / 'operations/executions').glob('*.json')):
        if cursor is not None and path.stem <= cursor:
            continue
        binding = bindings.get(path.stem, {})
        if session_id is not None and binding.get('session_id') != session_id:
            continue
        if user_task_id is not None and binding.get('user_task_id') != user_task_id:
            continue
        rows.append({**read_json(path), 'session_id': binding.get('session_id'),
                     'user_task_id': binding.get('user_task_id')})
        if len(rows) > limit:
            break
    return {'jobs': rows[:limit], 'next_cursor': rows[limit - 1]['job_id'] if len(rows) > limit else None}


def register_execution(root, spec, platform):
    value = {'schema_version': 'job-execution/1', 'job_id': spec.job_id, 'state': 'started',
             'platform': platform, 'command': list(spec.command), 'metadata': dict(spec.metadata),
             'collection_state': 'not_collected',
             **spec.metadata.get('research_binding', {'node_id': None, 'node_revision': None})}
    write_json(Path(root) / 'operations/executions' / (spec.job_id + '.json'), value)
    persist_event(root, kind='job', title='Calculation submitted',
                  content=f'Job {spec.job_id} submitted on {platform}.', references=[spec.job_id],
                  data=value, node_id=value['node_id'], node_revision=value['node_revision'], identity=['job', spec.job_id, 'submitted'])


@workspace_transaction('job.observe')
def _observe(root, request):
    job_id, value = request['job_id'], request['value']
    old = execution(root, job_id)
    status = value.get('status', value)
    state = status.get('state')
    if state not in TERMINAL | {'started', 'submitted', 'queued', 'held', 'running', 'unknown'}:
        return None
    if old['state'] in TERMINAL and state != old['state']:
        if state not in TERMINAL | {'unknown'}:
            return None
        if not value.get('_reconciled') or state == 'unknown':
            conflict = {'code': 'job_terminal_conflict', 'confirmed_state': old['state'],
                        'observed_state': state, 'recovery': 'job_reconcile'}
            if old.get('execution_conflict') != conflict:
                write_json(Path(root) / 'operations/executions' / (job_id + '.json'), {**old, 'execution_conflict': conflict})
                persist_event(root, kind='job', title='Calculation status conflict',
                              content=f'Job {job_id} requires reconciliation.', references=[job_id], data={**conflict, 'job_id': job_id}, node_id=old.get('node_id'), node_revision=old.get('node_revision'))
            return conflict
    if old['state'] == 'running' and state in {'started', 'submitted', 'queued', 'held'}:
        return None
    updated = {**old, **{k: status.get(k) for k in ('state', 'exit_code', 'started_at', 'finished_at', 'error')}}
    if value.get('_reconciled') and state != 'unknown':
        updated['execution_conflict'] = None
    if 'output_validation' in value:
        updated['output_validation'] = value['output_validation']
    if 'result_receipt' in value:
        updated['latest_result_receipt_ref'] = value['result_receipt']['receipt_id']
        updated['collection_state'] = value['result_receipt']['collection_state']
        updated['artifact_refs'] = value['result_receipt']['artifact_refs']
    if updated == old:
        return None
    write_json(Path(root) / 'operations/executions' / (job_id + '.json'), updated)
    persist_event(root, kind='job', title='Calculation '+state,
                  content=f'Job {job_id}: {state}; outputs {updated["collection_state"]}. '+(updated.get('error') or ''),
                  references=[job_id, *updated.get('artifact_refs', [])], data=updated, node_id=old.get('node_id'), node_revision=old.get('node_revision'))


def observe_execution(root, receipt, value):
    return _observe(root, {'job_id': receipt.job_id, 'value': value})


def execution_observation(receipt, status):
    observation = {key: status.get(key) for key in ('state', 'exit_code', 'started_at', 'finished_at', 'error')}
    observation.update(workspace_id=receipt.workspace_id, job_id=receipt.job_id,
                       source='job_runtime', schema_version='execution-observation/1')
    observation['observation_id'] = 'obs_' + hashlib.sha256(json.dumps(observation, sort_keys=True).encode()).hexdigest()
    return observation


def persist_event(root, *, kind, title, content, references=(), data=None, identity=None, node_id=None, node_revision=None):
    """Persist a runtime fact with the receipt transaction; Memory is a replayable projection."""
    value = {'kind': kind, 'title': title, 'content': content, 'references': list(references),
             'data': data or {}, 'node_id': node_id, 'node_revision': node_revision}
    key = identity if identity is not None else value
    event_id = 'runtime_' + hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()
    path = Path(root) / 'operations/events' / (event_id + '.json')
    if not path.exists():
        write_json(path, {'schema_version': 'runtime-event/1', 'event_id': event_id,
                         'created_at': datetime.now(timezone.utc).isoformat(), **value})
    return event_id


def project_events(root):
    """Replay durable facts without putting Memory availability on the execution path."""
    errors = []
    for path in sorted((Path(root) / 'operations/events').glob('*.json')):
        receipt_path = Path(root) / 'operations/event-projections' / path.name
        if receipt_path.exists():
            continue
        try:
            from research_agent.research.records import record_event
            event = read_json(path)
            request = {key: value for key, value in event.items() if key not in {'schema_version', 'created_at'}}
            result = record_event(root, request)
            write_json(receipt_path, {'event_id': event['event_id'], 'record_ref': result.get('ref')})
        except Exception as exc:
            errors.append({'event_id': path.stem, 'error': str(exc)})
    return errors
