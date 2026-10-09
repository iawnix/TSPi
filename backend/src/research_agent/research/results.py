"""Immutable research products, distinct from execution collection receipts."""
from pathlib import Path
import re
import uuid
from research_agent.foundation.transactions import read_json, write_json, workspace_transaction
from research_agent.foundation.path_safety import path_has_symlink
from . import basis, relations
from .records import workspace, now, append_record, digest
from .nodes import get_node, save, text, validate_refs, response


def get_result(root, result_id):
    if not isinstance(result_id, str) or not re.fullmatch(r'result_[a-f0-9]{32}', result_id):
        raise ValueError('result_id_invalid: use a returned Result reference')
    entry = relations.graph(root)['results'].get(result_id)
    if not entry:
        raise ValueError('result_not_found: ' + result_id)
    path = Path(root) / 'research/nodes' / entry['node_id'] / 'results' / (result_id + '.json')
    if path_has_symlink(path):
        raise ValueError('result_path_symlink')
    result = read_json(path)
    if (result.get('id') != result_id or result.get('node_id') != entry['node_id'] or result.get('schema_version') != 'research-result/1'
            or result.get('workspace_id') != read_json(Path(root) / 'workspace_manifest.json')['workspace_id']):
        raise ValueError('result_identity_invalid')
    if digest(result) != entry.get('content_digest'):
        raise ValueError('result_content_changed')
    return result


@workspace_transaction('research.result')
def publish(root, request):
    root = workspace(root)
    node = get_node(root, request['node_id'])
    conclusion = text(request.get('conclusion'), 'conclusion', required=True, limit=64000)
    external = request.get('_reference_details', {})
    inputs = list(validate_refs(root, request.get('inputs', []), external))
    if any(not ref.startswith('result_') and external.get(ref, {}).get('kind') != 'artifact' for ref in inputs):
        raise ValueError('result_inputs_require_fixed_results_or_artifacts: cite execution records in evidence_refs')
    evidence = validate_refs(root, request.get('evidence_refs', []), external)
    files = request.get('files', [])
    if not isinstance(files, list) or len(files) > 128:
        raise ValueError('result_files_invalid')
    for item in files:
        if not isinstance(item, dict) or set(item) - {'name', 'purpose', 'artifact_ref'}:
            raise ValueError('result_file_fields_invalid')
        ref = item.get('artifact_ref')
        if ref not in external or external[ref].get('kind') != 'artifact':
            raise ValueError('result_file_requires_verified_artifact')
        text(item.get('name'), 'file_name', required=True, limit=1000)
        text(item.get('purpose'), 'file_purpose')
    supersedes = request.get('supersedes')
    if supersedes is not None and get_result(root, supersedes)['node_id'] != node['id']:
        raise ValueError('supersedes_requires_same_node')
    if 'as_assessment' in request and type(request['as_assessment']) is not bool:
        raise ValueError('as_assessment_requires_boolean')
    bindings = []
    for ref in dict.fromkeys(inputs + evidence):
        detail = external.get(ref, {})
        if detail.get('research_binding'):
            bindings.append({'ref': ref, **detail['research_binding']})
        for used in detail.get('input_refs', []):
            if used not in inputs:
                inputs.append(used)
    result = dict(schema_version='research-result/1', id='result_' + uuid.uuid4().hex,
                  workspace_id=node['workspace_id'], node_id=node['id'],
                  summary=text(request.get('summary', conclusion[:600]), 'summary', required=True, limit=4000),
                  summary_is_excerpt='summary' not in request and len(conclusion) > 600,
                  observation=text(request.get('observation'), 'observation', limit=64000), conclusion=conclusion,
                  limitations=text(request.get('limitations'), 'limitations', limit=32000),
                  inputs=inputs, evidence_refs=evidence, files=files, supersedes=supersedes,
                  authored_node_revision=basis.seen_revision(root, node['id'], request), basis_refs=bindings,
                  author={'session_id': request.get('session_id')}, created_at=now())
    write_json(root / 'research/nodes' / node['id'] / 'results' / (result['id'] + '.json'), result)
    graph = relations.graph(root)
    graph['results'][result['id']] = {**{k: result[k] for k in ('id', 'node_id', 'summary', 'created_at', 'supersedes')}, 'content_digest': digest(result)}
    write_json(root / 'research/map.json', graph)
    log = append_record(root, origin='agent', kind='result_published', title=node['title'], content=result['summary'],
                        node_id=node['id'], node_revision=node['revision'], references=[result['id']],
                        data={'result_id': result['id'], 'result_digest': digest(result)}, identity=['result', result['id']])
    for ref in dict.fromkeys(inputs + evidence + [item['artifact_ref'] for item in files]):
        relations.cite(root, result['id'], ref, basis_ref=log['ref'], kind='uses' if ref in inputs else 'cites')
    selected, conflict = False, None
    if request.get('as_assessment'):
        try:
            basis.check(root, node, request, {'assessment_ref'})
        except ValueError as exc:
            conflict = str(exc)
        else:
            node.update(assessment_ref=result['id'], revision=node['revision'] + 1, updated_at=now())
            save(root, node)
            append_record(root, origin='agent', kind='node_updated', title=node['title'], content='Assessment selected',
                          node_id=node['id'], node_revision=node['revision'], references=[result['id']],
                          data={'node': node, 'author': result['author']}, identity=['assessment', result['id']])
            selected = True
    return response(root, node, request, result=result, result_saved=True, assessment_selected=selected, conflict=conflict)
