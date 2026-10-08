"""Execute registered extension validators through ordinary durable Jobs."""
import hashlib
import json
import os
import sys
from pathlib import Path


def prepare(root, params):
    package = Path(os.environ.get('TSPI_PACKAGE_ROOT') or os.environ.get('TS_PACKAGE_ROOT') or Path(__file__).resolve().parents[3]).resolve()
    entries = []
    for manifest in (package / 'extensions').glob('*/manifest.json'):
        extension = json.loads(manifest.read_text())
        for descriptor in extension.get('validators', []):
            if descriptor.get('id') == params['validator_id']:
                entries.append((manifest.parent, descriptor))
    if len(entries) != 1:
        raise ValueError('validator_not_registered: use an installed extension validator ID')
    base, descriptor = entries[0]
    script = (base / descriptor['entry']).resolve()
    if not script.is_relative_to(base.resolve()) or not script.is_file():
        raise ValueError('validator_entry_invalid')
    script_digest = hashlib.sha256(script.read_bytes()).hexdigest()
    if descriptor['sha256'] != 'sha256:' + script_digest:
        raise ValueError('validator_version_mismatch')
    if any(k in params for k in ('command', 'inputs', 'outputs', 'environment', 'env', 'metadata', 'platform', 'cwd')):
        raise ValueError('validator_request_invalid: only validator_id, input_artifact_ids and Job identity may be provided')
    from research_state.agent_workspace import read_context
    from artifact_store import PayloadStore
    store = PayloadStore(root / 'artifacts')
    artifacts = {a['id']: a for a in read_context(root)['artifacts']}
    refs = params.get('input_artifact_ids', [])
    if not refs or len(refs) != len(set(refs)):
        raise ValueError('validator_inputs_required')
    inputs = [{'source': str(script), 'destination': 'validator.py', 'sha256': script_digest}]
    input_versions = {}
    input_result_versions = {}
    for index, ref in enumerate(refs):
        artifact = artifacts.get(ref)
        if not artifact:
            raise ValueError('validator_input_missing')
        producer = next((a for a in read_context(root)['attempts'] if a['id'] == artifact.get('producer_attempt_id')), None)
        if not producer or not producer.get('metadata', {}).get('latest_result_receipt_ref'):
            raise ValueError('validator_input_requires_collected_output')
        result_ref = producer["metadata"]["latest_result_receipt_ref"]
        result = json.loads((root / 'operations/results' / (result_ref + '.json')).read_text())
        if producer.get('metadata', {}).get('execution_conflict') or ref not in result['artifact_refs']:
            raise ValueError('validator_input_stale: select evidence from the current result receipt')
        input_result_versions[producer["id"]] = result_ref
        payload = store.read_bytes(ref)
        digest = hashlib.sha256(payload).hexdigest()
        if artifact['sha256'].removeprefix('sha256:') != digest:
            raise ValueError('validator_input_digest_mismatch')
        inputs.append({'source': artifact['location'], 'destination': f'input_{index}', 'sha256': digest})
        input_versions[ref] = 'sha256:' + digest
    return {**params, 'command': [sys.executable, 'validator.py', *[f'input_{i}' for i in range(len(refs))]],
        'inputs': inputs, 'outputs': [{'path': 'validator_result.json', 'required': True, 'min_bytes': 2}],
        'metadata': {'validator': {'id': descriptor['id'], 'version': descriptor['version'],
            'script_sha256': descriptor['sha256'], 'input_versions': input_versions, 'input_result_versions': input_result_versions},
            'input_artifact_ids': refs}}


def collect_validation(receipt, collected):
    """Only an actual registered Job can create a validation receipt."""
    spec = json.loads((Path(receipt.cwd) / 'spec.json').read_text())
    validator = spec.get('metadata', {}).get('validator')
    if not validator:
        return None
    result = next((a for a in collected.get('artifacts', [])
                   if a.get('provenance', {}).get('source_path', '').endswith('/validator_result.json')), None)
    if collected.get('status', {}).get('state') != 'succeeded' or not result:
        return {**validator, 'verdict': 'blocked', 'reason': 'validator execution did not succeed'}
    payload = Path(result['location']).read_bytes()
    digest = 'sha256:' + hashlib.sha256(payload).hexdigest()
    if digest != result['sha256']:
        raise ValueError('validator_output_digest_mismatch')
    value = json.loads(payload)
    if value.get('schema_version') != 'validator-output/1' or value.get('verdict') not in {'pass', 'fail', 'inconclusive'}:
        raise ValueError('validator_output_invalid')
    return {**validator, 'verdict': value['verdict'], 'output_sha256': digest}
