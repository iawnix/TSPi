"""Explicit research links and evidence-backed citations, with one stored edge."""
from .records import append_record, digest, now
from research_agent.foundation.transactions import read_json, write_json
from pathlib import Path

DECLARED = frozenset({'part_of', 'requires', 'alternative_to'})


def graph(root):
    return read_json(Path(root) / 'research/map.json')


def links(root, node_id):
    return [edge for edge in graph(root)['relations'].values()
            if edge['active'] and node_id in (edge['source'], edge['target'])]


def change(root, node_id, additions=(), removals=(), *, author=None):
    value = graph(root)
    for ref in removals:
        edge = value['relations'].get(ref)
        if not edge or edge['kind'] not in DECLARED or node_id not in (edge['source'], edge['target']):
            raise ValueError('relation_not_owned: use a declared relation returned for this Node')
        if edge['source'] != node_id and edge['kind'] != 'alternative_to':
            raise ValueError('relation_not_owned')
        if edge['active']:
            edge = {**edge, 'active': False}
            append_record(root, origin='agent', kind='relation', title='Research relation withdrawn', content=ref,
                          node_id=node_id, data={'relation': edge, 'author': author}, identity=['withdraw', ref, now()])
            value['relations'][ref] = edge
    for item in additions:
        if not isinstance(item, dict) or set(item) - {'kind', 'target', 'reason'}:
            raise ValueError('relation_fields_invalid')
        kind, target = item.get('kind'), item.get('target')
        if kind not in DECLARED or target not in value['nodes'] or target == node_id:
            raise ValueError('relation_invalid: choose part_of/requires/alternative_to and an existing different Node')
        reason = item.get('reason', '')
        if not isinstance(reason, str) or len(reason) > 4000:
            raise ValueError('relation_reason_invalid')
        source = node_id
        if kind == 'alternative_to':
            source, target = sorted((source, target))
        if kind == 'part_of':
            pending, visited = [target], set()
            while pending:
                candidate = pending.pop()
                if candidate == source:
                    raise ValueError('relation_containment_cycle')
                if candidate in visited:
                    continue
                visited.add(candidate)
                pending.extend(e['target'] for e in value['relations'].values()
                               if e['active'] and e['kind'] == kind and e['source'] == candidate)
        ref = 'link_' + digest([source, kind, target])
        old = value['relations'].get(ref)
        if old and old['active'] and old['reason'] == reason:
            continue
        edge = dict(id=ref, source=source, kind=kind, target=target, reason=reason,
                    origin='agent', basis_refs=[], active=True, created_at=now())
        log = append_record(root, origin='agent', kind='relation', title='Research relation declared',
                            content=reason, node_id=node_id, data={'relation': edge, 'author': author},
                            identity=['relation', ref, now()])
        edge['basis_refs'] = [log['ref']]
        value['relations'][ref] = edge
    write_json(Path(root) / 'research/map.json', value)


def cite(root, source, target, *, basis_ref, kind='cites', origin='agent'):
    """References preserve exact Result/material identity; reading creates no link."""
    value = graph(root)
    ref = 'link_' + digest([source, kind, target, basis_ref])
    if ref not in value['relations']:
        edge = dict(id=ref, source=source, kind=kind, target=target, reason='', origin=origin,
                    basis_refs=[basis_ref], active=True, created_at=now())
        append_record(root, origin=origin, kind='relation', title='Result provenance', content=target,
                      node_id=source if source.startswith('node_') else None,
                      data={'relation': edge}, identity=['citation', ref])
        value['relations'][ref] = edge
        write_json(Path(root) / 'research/map.json', value)
    return ref


def diagnostics(root):
    """Describe cyclic planning dependencies without turning them into execution gates."""
    value = graph(root)
    adjacency = {node: [] for node in value['nodes']}
    reverse = {node: [] for node in adjacency}
    for edge in value['relations'].values():
        if edge['active'] and edge['kind'] == 'requires':
            adjacency[edge['source']].append(edge['target'])
            reverse[edge['target']].append(edge['source'])
    visited, order = set(), []
    for start in adjacency:
        pending = [(start, False)]
        while pending:
            node, expanded = pending.pop()
            if expanded:
                order.append(node)
            elif node not in visited:
                visited.add(node)
                pending.append((node, True))
                pending.extend((target, False) for target in adjacency[node] if target not in visited)
    visited, findings = set(), []
    for start in reversed(order):
        if start in visited:
            continue
        component, pending = [], [start]
        while pending:
            node = pending.pop()
            if node in visited:
                continue
            visited.add(node)
            component.append(node)
            pending.extend(reverse[node])
        if len(component) > 1:
            members = set(component)
            findings.append({'severity': 'warning', 'code': 'requires_cycle',
                'node_ids': sorted(component), 'relation_ids': sorted(edge['id'] for edge in value['relations'].values()
                    if edge['active'] and edge['kind'] == 'requires' and edge['source'] in members and edge['target'] in members),
                'message': 'Planning dependencies form a cycle; inspect the waiting intent. Tools remain available.'})
    return sorted(findings, key=lambda item: item['node_ids'])
