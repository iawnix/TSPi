"""Diagnose and rebuild projections without changing execution receipts."""
from pathlib import Path
from research_agent.foundation.transactions import read_json, write_json, workspace_transaction, TransactionCoordinator
from .workspace import validate_workspace_manifest
from .records import record, digest
from research_agent.foundation.path_safety import path_has_symlink


def _replay(root):
    root = Path(root)
    workspace_id = read_json(root / 'workspace_manifest.json')['workspace_id']
    records = []
    for path in (root / 'research/records').glob('*.json'):
        if path.is_symlink():
            raise ValueError('record_path_symlink')
        records.append(record(root, path.stem))
    records.sort(key=lambda r: r['sequence'])
    graph = {'schema_version': 'research-map/1', 'nodes': {}, 'results': {}, 'relations': {}}
    headers = []
    for sequence, item in enumerate(records, 1):
        if item['sequence'] != sequence or item['schema_version'] != 'research-record/2':
            raise ValueError('record_sequence_gap_or_duplicate')
        headers.append({k: item[k] for k in ('ref','sequence','origin','kind','title','node_id','created_at')})
        if item['data'].get('node'):
            node = item['data']['node']
            if node.get('workspace_id') != workspace_id or node.get('id') != item['node_id'] or node.get('schema_version') != 'research-node/1':
                raise ValueError('node_identity_invalid')
            graph['nodes'][node['id']] = node
        if item['data'].get('relation'):
            edge = item['data']['relation']
            if not edge['basis_refs']:
                edge['basis_refs'] = [item['ref']]
            graph['relations'][edge['id']] = edge
        if item['data'].get('result_id'):
            result_id = item['data']['result_id']
            path = root / 'research/nodes' / item['node_id'] / 'results' / (result_id + '.json')
            if path_has_symlink(path):
                raise ValueError('result_path_symlink')
            result = read_json(path)
            if result.get('id') != result_id or result.get('node_id') != item['node_id'] or result.get('workspace_id') != workspace_id or digest(result) != item['data'].get('result_digest'):
                raise ValueError('result_content_changed')
            graph['results'][result_id] = {**{k: result[k] for k in ('id','node_id','summary','created_at','supersedes')},
                                          'content_digest': item['data']['result_digest']}
    return {'schema_version': 'research-journal/2', 'sequence': len(headers), 'records': headers}, graph


@workspace_transaction('research.rebuild')
def _rebuild(root, request):
    root = Path(root)
    validate_workspace_manifest(read_json(root / 'workspace_manifest.json'), root, validate_documents=False)
    journal, graph = _replay(root)
    write_json(root / 'research/journal.json', journal)
    write_json(root / 'research/map.json', graph)
    for node in graph['nodes'].values():
        write_json(root / 'research/nodes' / node['id'] / 'node.json', node)
    return {'rebuilt': True, 'nodes': len(graph['nodes']), 'records': journal['sequence']}


def rebuild(root):
    with TransactionCoordinator(root).locked():
        result = _rebuild(root, {})
        path = Path(root) / 'research/search/index.sqlite'
        if path.is_symlink():
            raise ValueError('search_path_symlink')
        path.unlink(missing_ok=True)
        from .views import render
        render(root)
        return result


def inspect_workspace(root):
    root = Path(root).absolute()
    findings, sources = [], {}
    try:
        with TransactionCoordinator(root).locked():
            manifest = validate_workspace_manifest(read_json(root / 'workspace_manifest.json'), root)
            sources['manifest'] = manifest
            journal, graph = _replay(root)
            if journal != read_json(root / 'research/journal.json') or graph != read_json(root / 'research/map.json'):
                raise ValueError('projection_mismatch: rebuild research projections')
            for node in graph['nodes'].values():
                if node != read_json(root / 'research/nodes' / node['id'] / 'node.json'):
                    raise ValueError('node_projection_mismatch')
            from .relations import diagnostics
            from .views import documents
            findings.extend(diagnostics(root))
            for relative, expected in documents(root).items():
                path = root / relative
                if path_has_symlink(path):
                    raise ValueError('view_path_symlink')
                if not path.is_file() or path.read_text(encoding='utf-8') != expected:
                    findings.append({'severity': 'warning', 'code': 'generated_view_mismatch', 'path': relative,
                                     'message': 'Generated Markdown is missing or out of date; rebuild the research views.'})
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        findings.append({'severity': 'error', 'code': 'workspace_invalid', 'message': str(error)})
    valid = not any(item['severity'] == 'error' for item in findings)
    return {'schema_version': 'research-memory-workspace-doctor/1', 'root': str(root), 'valid': valid,
            'status': 'blocked' if not valid else 'attention' if findings else 'healthy', 'findings': findings, 'sources': sources}
