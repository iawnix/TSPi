"""Persist operational Job facts through the canonical Research State writer."""
import hashlib
import json
from datetime import datetime, timezone
from research_state.transactions import TransactionCoordinator, read_json
from research_state import agent_workspace as state


def context(root):
    return read_json(root / 'research_map/context.json')


def change(root, key, operations):
    from research_state.write_origin import runtime_write
    with runtime_write():
        return state.apply_change(root, {'request_id': key, 'principal': 'root_agent', 'authority': 'kernel_write',
                                        'operations': operations})


def register_attempt(root, spec, platform):
    if spec.node_id is None:
        if spec.attempt_id:
            raise ValueError('attempt binding requires a node')
        return None
    if not state.has_state_files(root):
        raise ValueError('research Job requires an initialized research workspace')
    attempt_id = spec.attempt_id or 'attempt_' + hashlib.sha256(spec.job_id.encode()).hexdigest()[:32]
    ctx = context(root)
    old = next((a for a in ctx['attempts'] if a['id'] == attempt_id), None)
    if old:
        if old['node_id'] != spec.node_id or old.get('metadata', {}).get('job_id') != spec.job_id:
            raise ValueError('attempt already belongs to another node or job')
        return attempt_id
    change(root, 'job-attempt:' + spec.job_id, [{'type': 'register_attempt', 'id': attempt_id, 'node_id': spec.node_id,
        'execution_kind': 'command', 'state': 'started', 'started_at': None, 'environment': platform or 'local',
        'metadata': {'job_id': spec.job_id, 'command': list(spec.command), 'job_metadata': dict(spec.metadata)}}])
    return attempt_id


def observe_attempt(root, receipt, value):
    with TransactionCoordinator(root).locked():
        return _observe_attempt(root, receipt, value)


def _observe_attempt(root, receipt, value):
    if not receipt.attempt_id or not state.has_state_files(root):
        return
    status = value.get('status', value)
    execution = status.get('state')
    mapped = {'submitted': 'started', 'queued': 'started', 'held': 'started', 'running': 'running',
              'succeeded': 'succeeded', 'failed': 'failed', 'timed_out': 'timed_out',
              'cancelled': 'cancelled', 'unknown': 'unknown'}.get(execution)
    if not mapped:
        return
    old = next((a for a in context(root)['attempts'] if a['id'] == receipt.attempt_id), None)
    if not old or old.get('metadata', {}).get('job_id') != receipt.job_id or old['node_id'] != receipt.node_id:
        raise ValueError('job_binding_mismatch: receipt does not match registered Attempt')
    conflict = None
    if old['state'] in state.ATTEMPT_TERMINAL_STATES and old['state'] != mapped:
        if mapped not in state.ATTEMPT_TERMINAL_STATES and mapped != 'unknown':
            return
        if not value.get('_reconciled') or mapped == 'unknown':
            conflict = {'code': 'job_terminal_conflict', 'confirmed_state': old['state'], 'observed_state': mapped,
                        'recovery': 'job_reconcile'}
            if old.get('metadata', {}).get('execution_conflict') != conflict:
                change(root, None, [{'type': 'transition_attempt', 'attempt_id': receipt.attempt_id, 'state': old['state'],
                    'metadata': {**old.get('metadata', {}), 'execution_conflict': conflict},
                    'finished_at': old.get('finished_at')}])
            return conflict
    if old['state'] == 'running' and mapped == 'started':
        return
    observation = execution_observation(receipt, status)
    metadata = {**old.get('metadata', {}), 'execution_observation': observation}
    if value.get('_reconciled') and mapped != 'unknown':
        metadata['execution_conflict'] = None
        metadata['reconciliation'] = {'previous_observation': old.get('metadata', {}).get('execution_observation'), 'confirmed_observation': observation}
    if 'output_validation' in value:
        metadata['output_validation'] = value['output_validation']
    if 'result_receipt' in value:
        metadata['latest_result_receipt_ref'] = value['result_receipt']['receipt_id']
    if old['state'] == mapped and all(old.get('metadata', {}).get(k) == v for k, v in metadata.items()):
        return
    metadata['observed_at'] = datetime.now(timezone.utc).isoformat()
    operation = {'type': 'transition_attempt', 'attempt_id': receipt.attempt_id, 'state': mapped,
                 'exit_code': status.get('exit_code'), 'metadata': metadata, 'finished_at': status.get('finished_at')}
    if value.get('_reconciled'):
        operation.update(type='reconcile_attempt', recovery_reason='Confirmed by explicit Job Runtime reconciliation')
    if status.get('started_at'):
        operation['started_at'] = status['started_at']
    if status.get('error'):
        operation['error'] = status['error']
    # No stable request ID: semantic no-op above handles repeat observations,
    # while the enclosing transaction gives each actual change one redo record.
    change(root, None, [operation])


def execution_observation(receipt, status):
    observation = {key: status.get(key) for key in ('state', 'exit_code', 'started_at', 'finished_at', 'error')}
    observation.update(workspace_id=receipt.workspace_id, job_id=receipt.job_id, attempt_id=receipt.attempt_id,
                       source='job_runtime', schema_version='execution-observation/1')
    observation['observation_id'] = 'obs_' + hashlib.sha256(json.dumps(observation, sort_keys=True).encode()).hexdigest()
    return observation
