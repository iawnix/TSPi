"""Execute registered extension validators through ordinary durable Jobs."""
import hashlib
import json
import os
from pathlib import Path


def _registered_file(base, relative, expected):
    path = (base / relative).resolve()
    if not path.is_relative_to(base.resolve()) or not path.is_file():
        raise ValueError('validator_entry_invalid')
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if expected != 'sha256:' + digest:
        raise ValueError('validator_version_mismatch')
    return path, digest


def prepare(root, params):
    root = Path(root).resolve()
    from research_agent.application.execution_catalog import registered_entry
    base, descriptor = registered_entry('validators', params['validator_id'], params.get('validator_version'))
    script, script_digest = _registered_file(base, descriptor['entry'], descriptor['sha256'])
    if any(k in params for k in ('command', 'inputs', 'outputs', 'environment', 'env', 'metadata', 'cwd')):
        raise ValueError('validator_request_invalid: use validator identity, inputs, Job identity and a named platform')
    from research_agent.jobs.config_contract import load_job_config, resolve_binding, binding_digest
    from research_agent.jobs.environment import probe_binding, guarded_command
    config_path = os.environ.get('RESEARCH_AGENT_JOB_CONFIG')
    if not config_path:
        raise ValueError('job_config_required')
    settings = load_job_config(config_path)
    selected = resolve_binding(settings, params.get('platform') or settings['default_environment'],
                               descriptor['backend'], runtime='python')
    from research_agent.artifacts import PayloadStore
    store = PayloadStore(root / 'artifacts')
    from research_agent.artifacts.registry import manifests
    from .job_state import execution
    artifacts = {a['artifact_id']: a for a in manifests(root)}
    refs = params.get('input_artifact_ids', [])
    if not isinstance(refs, list) or not refs or any(not isinstance(x, str) for x in refs) or len(refs) != len(set(refs)):
        raise ValueError('validator_inputs_required')
    contract = descriptor.get('input_contract')
    if contract is not None:
        if contract.get('schema_version') != 'validator-input/1' or not isinstance(contract.get('roles'), list):
            raise ValueError('validator_input_contract_invalid')
        roles = contract['roles']
        if len(roles) != len(refs):
            raise ValueError('validator_input_count_mismatch')
    else:
        roles = [{'name': str(i), 'source': 'collected_output'} for i in range(len(refs))]
    inputs = [{'source': str(script), 'destination': 'validator.py', 'sha256': script_digest}]
    destinations = set()
    reserved = {'validator.py', 'validator_inputs.json', 'validator_result.json',
                'spec.json', 'receipt.json', 'status.json', 'logs', '.research-agent'}
    for destination, resource in descriptor.get('resources', {}).items():
        target = Path(destination)
        if (target.is_absolute() or '..' in target.parts or not target.parts
                or target.parts[0] in reserved or target.parts[0].startswith('input_')
                or any(target == other or target in other.parents or other in target.parents for other in destinations)):
            raise ValueError('validator_resource_destination_invalid')
        destinations.add(target)
        path, digest = _registered_file(base, resource['path'], resource['sha256'])
        inputs.append({'source': str(path), 'destination': target.as_posix(), 'sha256': digest})
    input_versions, input_result_versions, records = {}, {}, []
    for index, (ref, role) in enumerate(zip(refs, roles)):
        artifact = artifacts.get(ref)
        if not artifact:
            raise ValueError('validator_input_missing')
        source = role.get('source')
        if source not in {'collected_output', 'registered_artifact'}:
            raise ValueError('validator_input_contract_invalid')
        producer_id = artifact.get('provenance', {}).get('job_id')
        producer = execution(root, producer_id) if producer_id else None
        result_ref = None
        # Registered inputs permit literature/input data, but never bypass a claimed producer's receipt.
        if source == 'collected_output' or producer_id:
            if not producer or not producer.get('latest_result_receipt_ref'):
                raise ValueError('validator_input_requires_collected_output')
            result_ref = producer['latest_result_receipt_ref']
            import re
            if not re.fullmatch(r'job_result_[0-9a-f]{64}', result_ref):
                raise ValueError('validator_input_receipt_invalid')
            result = json.loads((root / 'operations/results' / (result_ref + '.json')).read_text())
            if (producer.get('execution_conflict') or ref not in result['artifact_refs']
                    or result.get('job_id') != producer_id):
                raise ValueError('validator_input_stale: select evidence from the current result receipt')
            input_result_versions[producer_id] = result_ref
        maximum = role.get('max_bytes', 64 * 1024 * 1024)
        if type(maximum) is not int or maximum < 1:
            raise ValueError('validator_input_contract_invalid')
        payload = store.read_bytes(ref, max_bytes=maximum + 1)
        if len(payload) > maximum:
            raise ValueError('validator_input_too_large')
        digest = hashlib.sha256(payload).hexdigest()
        if artifact['sha256'].removeprefix('sha256:') != digest:
            raise ValueError('validator_input_digest_mismatch')
        if artifact.get('size_bytes') != len(payload):
            raise ValueError('validator_input_size_mismatch')
        expected_location = (root/'artifacts'/ref/'payload').resolve()
        if Path(artifact['location']).resolve() != expected_location:
            raise ValueError('validator_input_location_mismatch')
        if role.get('schema_version'):
            value = json.loads(payload)
            if not isinstance(value, dict) or value.get('schema_version') != role['schema_version']:
                raise ValueError('validator_input_schema_mismatch')
        inputs.append({'source': str(expected_location), 'destination': f'input_{index}', 'sha256': digest})
        input_versions[ref] = 'sha256:' + digest
        records.append({'role': role.get('name', str(index)), 'artifact_id': ref, 'sha256':'sha256:'+digest,
                        'source': source, 'job_id': producer_id, 'result_receipt_ref': result_ref,
                        'execution_inputs': producer.get('metadata', {}).get('input_roles', {}) if producer else {}})
    manifest_data = json.dumps({'schema_version':'validator-bound-inputs/1','inputs':records},sort_keys=True).encode()
    manifest_digest = hashlib.sha256(manifest_data).hexdigest()
    manifest_path = root/'operations/validator-inputs'/f'{manifest_digest}.json'
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with manifest_path.open('xb') as stream:
            stream.write(manifest_data)
    except FileExistsError:
        if manifest_path.read_bytes() != manifest_data:
            raise ValueError('validator_input_manifest_conflict')
    inputs.append({'source':str(manifest_path),'destination':'validator_inputs.json','sha256':manifest_digest})
    environment = probe_binding(settings, selected, descriptor.get('requirements', {}))
    argv = ['validator.py', *[f'input_{i}' for i in range(len(refs))]]
    module_paths = descriptor.get('module_paths')
    command, guard_inputs = guarded_command(selected, argv, environment, module_paths=module_paths)
    inputs.extend(guard_inputs)
    return {**params, 'platform': selected['environment'],
        'command': command,
        'environment': selected['binding'].get('environment', {}),
        'inputs': inputs, 'outputs': [{'path': 'validator_result.json', 'required': True, 'min_bytes': 2}],
        'metadata': {**selected['submission'], 'execution_binding': selected, 'python_binding': selected['python'],
            'execution_environment': environment, 'execution_argv': argv,
            **({'module_paths': module_paths} if module_paths is not None else {}),
            'configuration_sha256': binding_digest(selected),
            'resources_sha256': {row['destination']: row['sha256'] for row in inputs if not row['destination'].startswith('input_')},
            'validator': {'id': descriptor['id'], 'version': descriptor['version'],
            'script_sha256': descriptor['sha256'], 'input_versions': input_versions, 'input_result_versions': input_result_versions},
            'input_artifact_ids': refs}}


def check_current_inputs(root, prepared):
    """Recheck execution receipt versions after the target probe, inside submission's lock."""
    from research_agent.artifacts.registry import manifests
    from .job_state import execution
    validator = prepared['metadata']['validator']
    artifacts = {row['artifact_id']: row for row in manifests(root)}
    for ref, digest in validator['input_versions'].items():
        if artifacts.get(ref, {}).get('sha256') != digest:
            raise ValueError('validator_input_stale')
    for ref, version in validator['input_result_versions'].items():
        metadata = execution(root, ref)
        if metadata.get('latest_result_receipt_ref') != version or metadata.get('execution_conflict'):
            raise ValueError('validator_input_stale')


def collect_validation(receipt, collected):
    """Only an actual registered Job can create a validation receipt."""
    spec = json.loads((Path(receipt.cwd) / 'spec.json').read_text())
    validator = spec.get('metadata', {}).get('validator')
    if not validator:
        return None
    result = next((a for a in collected.get('artifacts', [])
                   if a.get('provenance', {}).get('source_path', '').endswith('/validator_result.json')), None)
    if collected.get('status', {}).get('state') != 'succeeded' or not result:
        return {**validator, 'verdict': 'blocked', 'execution_status': 'failed',
                'parsing': {'status': 'not_run'}, 'reason': 'validator execution did not succeed'}
    payload = Path(result['location']).read_bytes()
    digest = 'sha256:' + hashlib.sha256(payload).hexdigest()
    if digest != result['sha256']:
        raise ValueError('validator_output_digest_mismatch')
    value = json.loads(payload)
    if value.get('schema_version') != 'validator-output/1' or value.get('verdict') not in {'pass', 'fail', 'inconclusive'}:
        raise ValueError('validator_output_invalid')
    if 'bindings' in value and not isinstance(value['bindings'], dict):
        raise ValueError('validator_output_bindings_invalid')
    return {**validator, 'verdict': value['verdict'], 'output_sha256': digest,
            'execution_status': 'succeeded',
            'parsing': value.get('parsing', {'status': 'not_reported'}),
            'provenance': {'status': 'verified', 'basis': 'staged_inputs_and_collected_output',
                           'input_versions': validator['input_versions'],
                           'input_result_versions': validator['input_result_versions'],
                           'scope': 'Recorded execution source and bytes; not scientific identity or truth'},
            **({k:value[k] for k in ('bindings','checks','scope','scientific_verdict') if k in value})}
