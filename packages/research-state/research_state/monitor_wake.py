"""Assess durable Monitor facts against canonical Research State, before a wake."""
import json
import re
from pathlib import Path


def assess(root, context, liveness, event_id, session_id):
    if not isinstance(event_id, str) or not re.fullmatch(r'event_[A-Za-z0-9_-]+', event_id):
        raise ValueError('invalid monitor event identity')
    paths = list((Path(root) / 'operations/monitors').glob(f'*/events/{event_id}.json'))
    if len(paths) != 1:
        raise ValueError('unknown monitor event')
    event = json.loads(paths[0].read_text())
    if event.get('workspace_id') != context['workspace_id'] or event.get('session_id') != session_id:
        raise ValueError('monitor event belongs to another workspace or session')
    attempt = next((a for a in context.get('attempts', []) if a['id'] == event.get('attempt_id')), {})
    node = next((n for n in context.get('nodes', []) if n['id'] == event.get('node_id')), {})
    interpreted = any(i.get('attempt_id') == attempt.get('id') for i in context.get('attempt_interpretations', []) if attempt)
    observed = (attempt.get('metadata', {}).get('job_id') == event.get('job_id')
                and attempt.get('state') == event.get('state')
                and attempt.get('exit_code') == event.get('exit_status'))
    collected = 'output_validation' in attempt.get('metadata', {})
    # A terminal workspace alone is never evidence that a new failure was handled.
    obsolete = observed and (interpreted or collected and node.get('state') == 'closed')
    disposition = liveness.get('disposition')
    unhandled_failure = not obsolete and event.get('state') in {'failed', 'timed_out', 'cancelled', 'unknown'}
    deferred = not obsolete and (disposition in {'blocked', 'deferred', 'user_input_required'}
                                or disposition == 'terminal' and not unhandled_failure)
    return {'event_id': event_id, 'event': event, 'obsolete': obsolete,
            'admitted': not obsolete and not deferred,
            'reason': 'already_handled' if obsolete else 'research_' + str(disposition) if deferred else 'attention_required',
            'state_token': f"{context['revision']}:{liveness.get('checkpoint_id')}"}
