"""Read receipts are session-scoped capabilities for authored field replacement."""
from pathlib import Path
from research_agent.foundation.transactions import read_json, write_json, workspace_transaction
from .records import digest, now

EDIT_FIELDS = frozenset({'goal', 'title', 'proposal', 'plan', 'progress', 'status', 'assessment_ref', 'relations'})


def issue(root, nodes, session_id=None, fields=None, segments=None):
    entries = {node['id']: {'revision': node['revision'], 'fields': sorted(EDIT_FIELDS if fields is None else fields)} for node in nodes}
    for node_id, entry in entries.items():
        if 'relations' in entry['fields'] or segments and 'relations' in segments:
            entry['relations_digest'] = relation_digest(root, node_id)
    if segments:
        for entry in entries.values():
            entry['segments'] = segments
    receipt = {'schema_version': 'research-read-basis/1', 'session_id': session_id, 'nodes': entries}
    ref = 'read_' + digest(receipt)
    write_json(Path(root) / 'operations/contexts' / (ref + '.json'), receipt)
    return ref


def _receipt(root, token, session_id):
    if not isinstance(token, str) or not token.startswith('read_') or len(token) != 69 or any(c not in '0123456789abcdef' for c in token[5:]):
        raise ValueError('read_basis_invalid')
    value = read_json(Path(root) / 'operations/contexts' / (token + '.json'))
    if value['session_id'] != session_id:
        raise ValueError('read_basis_session_mismatch')
    return value


@workspace_transaction('research.observe')
def observe(root, request):
    session = request.get('session_id')
    value = _receipt(root, request['read_basis'], session)
    path = Path(root) / 'operations/contexts/readers' / (digest(session) + '.json')
    try:
        previous = read_json(path)
    except FileNotFoundError:
        previous = {'session_id': session, 'nodes': {}}
    for node_id, entry in value['nodes'].items():
        old = previous['nodes'].get(node_id)
        if old and old['revision'] > entry['revision']:
            continue
        same_revision = old is not None and old['revision'] == entry['revision']
        prior_fields = set(old['fields']) if same_revision else set()
        if same_revision and entry.get('relations_digest') and entry['relations_digest'] != old.get('relations_digest'):
            prior_fields.discard('relations')
        fields = set(entry['fields']) | prior_fields
        segments = dict(old.get('segments', {})) if same_revision else {}
        for field, page in entry.get('segments', {}).items():
            prior = segments.get(field)
            ranges = page['ranges'] + (prior['ranges'] if prior and prior['digest'] == page['digest'] else [])
            merged = []
            for start, end in sorted(ranges):
                if merged and start <= merged[-1][1]:
                    merged[-1][1] = max(end, merged[-1][1])
                else:
                    merged.append([start, end])
            segments[field] = {**page, 'ranges': merged}
            if merged == [[0, page['total_characters']]]:
                fields.add(field)
        combined = {**entry, 'fields': sorted(fields), 'segments': segments}
        if same_revision and 'relations_digest' not in combined and old.get('relations_digest'):
            combined['relations_digest'] = old['relations_digest']
        previous['nodes'][node_id] = combined
    write_json(path, previous)
    return {'recorded': True}


def check(root, node, request, fields):
    if not fields:
        return
    try:
        if request.get('read_basis'):
            receipt = _receipt(root, request['read_basis'], request.get('session_id'))
        else:
            receipt = read_json(Path(root) / 'operations/contexts/readers' / (digest(request.get('session_id')) + '.json'))
        entry = receipt['nodes'].get(node['id'])
    except FileNotFoundError:
        entry = None
    if not entry:
        raise ValueError('node_read_required: research_read ref=' + node['id'])
    if entry['revision'] != node['revision']:
        raise ValueError(f"node_revision_conflict: research_read ref={node['id']}; current revision {node['revision']}")
    if 'relations' in fields and 'relations' in entry['fields'] and entry.get('relations_digest') != relation_digest(root, node['id']):
        raise ValueError('node_relations_conflict: research_read ref=' + node['id'] + ' field=relations')
    if set(fields) - set(entry['fields']):
        raise ValueError('node_fields_not_read: research_read ref=' + node['id'])


def seen_revision(root, node_id, request):
    """Missing context remains unknown; publication never invents a read."""
    try:
        receipt = (_receipt(root, request['read_basis'], request.get('session_id')) if request.get('read_basis') else
                   read_json(Path(root) / 'operations/contexts/readers' / (digest(request.get('session_id')) + '.json')))
    except FileNotFoundError:
        return None
    return receipt['nodes'].get(node_id, {}).get('revision')


def relation_digest(root, node_id):
    from .relations import links, DECLARED
    return digest(sorted((edge for edge in links(root, node_id) if edge['kind'] in DECLARED and (edge['source'] == node_id or edge['kind'] == 'alternative_to')), key=lambda edge: edge['id']))
