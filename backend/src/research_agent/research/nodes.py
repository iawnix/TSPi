"""A Node retains one research question across repeated attempts."""
from pathlib import Path
import re
import uuid
from research_agent.foundation.transactions import read_json, write_json, workspace_transaction
from research_agent.foundation.path_safety import path_has_symlink
from .records import workspace, append_record, record, now
from . import basis, relations


def text(value, name, *, required=False, limit=16000):
    if value is None and not required:
        return None
    if not isinstance(value, str) or required and not value.strip() or len(value.encode()) > limit:
        raise ValueError(name + '_invalid')
    return value


def get_node(root, node_id):
    if not isinstance(node_id, str) or not re.fullmatch(r'node_[a-f0-9]{32}', node_id):
        raise ValueError('node_id_invalid: use a returned Node reference')
    path = Path(root) / 'research/nodes' / node_id / 'node.json'
    if path_has_symlink(path):
        raise ValueError('node_path_symlink')
    value = read_json(path)
    if (value.get('id') != node_id or value.get('schema_version') != 'research-node/1'
            or value.get('workspace_id') != read_json(Path(root) / 'workspace_manifest.json')['workspace_id']):
        raise ValueError('node_identity_invalid')
    return value


def save(root, node):
    write_json(Path(root) / 'research/nodes' / node['id'] / 'node.json', node)
    graph = relations.graph(root)
    graph['nodes'][node['id']] = node
    write_json(Path(root) / 'research/map.json', graph)


def validate_refs(root, refs, external=None):
    from .results import get_result
    if not isinstance(refs, list) or len(refs) > 128 or any(not isinstance(r, str) for r in refs) or len(set(refs)) != len(refs):
        raise ValueError('references_invalid: use unique returned references')
    for ref in refs:
        if ref.startswith('node_'):
            get_node(root, ref)
        elif ref.startswith('result_'):
            get_result(root, ref)
        elif ref.startswith(('user_', 'record_', 'note_')):
            record(root, ref)
        elif ref not in (external or {}):
            raise ValueError('reference_not_verified: ' + ref)
    return refs


def response(root, node, request, **values):
    return {'accepted': True, 'node': node, 'relations': relations.links(root, node['id']), 'read_basis': basis.issue(root, [node], request.get('session_id')), **values}


@workspace_transaction('research.create')
def create(root, request):
    root = workspace(root)
    goal = text(request.get('goal'), 'goal', required=True, limit=8000)
    title = text(request.get('title', goal[:100]), 'title', required=True, limit=1000)
    source_refs = validate_refs(root, request.get('source_refs', []))
    if any(not ref.startswith('user_') for ref in source_refs):
        raise ValueError('source_refs_require_user_messages')
    input_refs = validate_refs(root, request.get('input_refs', []), request.get('_reference_details'))
    node = dict(schema_version='research-node/1', id='node_' + uuid.uuid4().hex,
                workspace_id=read_json(root / 'workspace_manifest.json')['workspace_id'],
                title=title, goal=goal, proposal=text(request.get('proposal'), 'proposal'),
                plan=text(request.get('plan'), 'plan'), progress='', status='open', assessment_ref=None,
                source_refs=source_refs, input_refs=input_refs, revision=1, created_at=now(), updated_at=now(),
                author={'session_id': request.get('session_id')})
    save(root, node)
    log = append_record(root, origin='agent', kind='node_created', title=title, content=goal,
                        references=source_refs + input_refs, node_id=node['id'], node_revision=1,
                        data={'node': node}, identity=['create', node['id']])
    relations.change(root, node['id'], request.get('relations', []), author=node['author'])
    for ref in input_refs:
        relations.cite(root, node['id'], ref, basis_ref=log['ref'])
    (root / 'research/nodes' / node['id'] / 'work').mkdir(parents=True, exist_ok=True)
    return response(root, node, request, ref=log['ref'])


@workspace_transaction('research.update')
def update(root, request):
    root = workspace(root)
    node = get_node(root, request['node_id'])
    note = text(request.get('note'), 'note', required=True, limit=64000)
    changed = set(request) & basis.EDIT_FIELDS
    if request.get('add_relations') or request.get('remove_relations'):
        changed.add('relations')
    basis.check(root, node, request, changed)
    for key in changed - {'relations', 'status', 'assessment_ref'}:
        node[key] = text(request[key], key, required=key in {'goal', 'title'})
    if 'status' in changed:
        if request['status'] not in {'open', 'paused', 'closed'}:
            raise ValueError('node_status_invalid')
        node['status'] = request['status']
    if 'assessment_ref' in changed:
        ref = request['assessment_ref']
        if ref is not None:
            validate_refs(root, [ref])
            from .results import get_result
            selected = get_result(root, ref) if ref.startswith('result_') else record(root, ref)
            if selected.get('node_id') != node['id'] or selected.get('origin', 'agent') != 'agent':
                raise ValueError('assessment_must_belong_to_node')
        node['assessment_ref'] = ref
    if changed:
        node['revision'] += 1
        node['updated_at'] = now()
    log = append_record(root, origin='agent', kind='node_updated' if changed else 'note', title=node['title'],
                        content=note, node_id=node['id'], node_revision=node['revision'],
                        data={**({'node': node} if changed else {}), 'author': {'session_id': request.get('session_id')}},
                        identity=['note', request.get('request_id') or uuid.uuid4().hex])
    if changed:
        save(root, node)
        relations.change(root, node['id'], request.get('add_relations', []), request.get('remove_relations', []),
                         author={'session_id': request.get('session_id')})
    return response(root, node, request, ref=log['ref'])
