"""Domain-neutral subject references and derived review notices, never truth gates."""
import re
from .records import digest
from . import relations


def subjects(root, value, external):
    from .nodes import validate_refs
    if not isinstance(value, dict) or len(value) > 32 or any(
            not isinstance(role, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,63}', role) for role in value):
        raise ValueError('subjects_invalid: use named roles and fixed artifact or Result references')
    refs = list(dict.fromkeys(value.values()))
    validate_refs(root, refs, external)
    if any(not ref.startswith('result_') and external.get(ref, {}).get('kind') != 'artifact' for ref in refs):
        raise ValueError('subjects_require_fixed_references')
    return dict(value)


def node_context(node):
    return digest({key: node.get(key, {} if key == 'subjects' else None)
                   for key in ('title', 'goal', 'proposal', 'plan', 'progress', 'status', 'subjects')})


def result_notices(root, result, graph=None):
    graph = graph or relations.graph(root)
    notices = []
    context = result.get('context_basis')
    node = graph['nodes'].get(result['node_id'])
    if context and node and context['sha256'] != node_context(node):
        notices.append({'code': 'node_context_changed', 'node_id': node['id'],
                        'basis_revision': context['node_revision'], 'current_revision': node['revision']})
    refs = {result['id'], *result.get('inputs', []), *result.get('evidence_refs', []),
            *result.get('check_refs', []), *result.get('subjects', {}).values()}
    for replacement in graph['results'].values():
        if replacement.get('supersedes') in refs:
            notices.append({'code': 'result_superseded' if replacement['supersedes'] == result['id'] else 'cited_result_superseded',
                            'used': replacement['supersedes'], 'superseded_by': replacement['id']})
    for binding in result.get('basis_refs', []):
        current = graph['nodes'].get(binding.get('node_id'))
        if current and current['id'] != result['node_id'] and current['revision'] != binding.get('node_revision'):
            notices.append({'code': 'cited_node_changed', 'node_id': current['id'], 'ref': binding['ref'],
                            'basis_revision': binding.get('node_revision'), 'current_revision': current['revision']})
    return notices
