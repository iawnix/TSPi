"""Immutable research history; execution facts retain their runtime origin."""
from __future__ import annotations
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from research_agent.foundation.path_safety import path_has_symlink
from research_agent.foundation.transactions import read_json, write_json, workspace_transaction


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def workspace(root):
    from .workspace import validate_workspace_manifest
    root = Path(root).expanduser().absolute()
    validate_workspace_manifest(read_json(root / 'workspace_manifest.json'), root, require_ready=True)
    return root


def journal(root):
    return read_json(Path(root) / 'research/journal.json')


def record(root, ref):
    if not isinstance(ref, str) or not re.fullmatch(r'(?:note|record|user)_[a-f0-9]{64}', ref):
        raise ValueError('record_reference_invalid: use an exact returned reference')
    path = Path(root) / 'research/records' / (ref + '.json')
    if path_has_symlink(path):
        raise ValueError('record_path_symlink')
    value = read_json(path)
    if value.get('ref') != ref or value.get('schema_version') != 'research-record/2':
        raise ValueError('record_identity_invalid')
    if value.get('content_digest') != digest({key: item for key, item in value.items() if key != 'content_digest'}):
        raise ValueError('record_content_changed')
    return value


def append_record(root, *, origin, kind, title, content, references=(), data=None,
                  identity=None, node_id=None, node_revision=None):
    root = Path(root)
    body = dict(origin=origin, kind=kind, title=title, content=content,
                references=list(references), data=data or {}, node_id=node_id, node_revision=node_revision)
    prefix = 'user' if origin == 'user' else 'note' if origin == 'agent' else 'record'
    ref = prefix + '_' + digest(identity if identity is not None else body)
    path = root / 'research/records' / (ref + '.json')
    try:
        previous = record(root, ref)
    except FileNotFoundError:
        previous = None
    if previous is not None:
        if any(previous[key] != value for key, value in body.items()):
            raise ValueError('record_identity_reused')
        return previous
    index = journal(root)
    value = dict(schema_version='research-record/2', ref=ref, sequence=index['sequence'] + 1,
                 created_at=now(), **body)
    value['content_digest'] = digest(value)
    write_json(path, value)
    index['sequence'] = value['sequence']
    index['records'].append({key: value[key] for key in ('ref', 'sequence', 'origin', 'kind', 'title', 'node_id', 'created_at')})
    write_json(root / 'research/journal.json', index)
    return value


@workspace_transaction('research.event')
def record_event(root, request):
    root = workspace(root)
    identity = ['runtime', request['event_id']] if request.get('event_id') else request.get('identity')
    value = append_record(root, origin='runtime', kind=request['kind'], title=request['title'],
                          content=request.get('content', ''), references=request.get('references', ()),
                          data=request.get('data'), identity=identity, node_id=request.get('node_id'),
                          node_revision=request.get('node_revision'))
    if request.get('node_id') and request['kind'] == 'job' and (request.get('data') or {}).get('state') == 'started':
        from .relations import cite
        verified_inputs = (request.get('data') or {}).get('metadata', {}).get('input_evidence_basis', {})
        for artifact_ref in verified_inputs:
            cite(root, request['node_id'], artifact_ref, basis_ref=value['ref'], kind='uses', origin='runtime')
    return {'ref': value['ref'], 'sequence': value['sequence'], 'recorded': True}


@workspace_transaction('research.source')
def record_source(root, request):
    root = workspace(root)
    for key in ('session_id', 'message_id', 'text'):
        if not isinstance(request.get(key), str) or not request[key].strip():
            raise ValueError('user_input_invalid: ' + key)
    if len(request['text'].encode()) > 1_000_000:
        raise ValueError('user_input_too_large')
    value = append_record(root, origin='user', kind='task', title='User request', content=request['text'],
                          data={key: request[key] for key in ('session_id', 'message_id')},
                          identity=['user', request['session_id'], request['message_id']])
    return {'source_ref': value['ref'], 'recorded': True}
