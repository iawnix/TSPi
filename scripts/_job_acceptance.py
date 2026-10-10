"""Run bounded offline installation Jobs through the ordinary runtime APIs."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import time
import shlex

try:
    from ._job_install import profiles, resource, write_private
except ImportError:
    from _job_install import profiles, resource, write_private
from research_agent.application.api import execute
from research_agent.application.environment_check import check_environments
from research_agent.application.executors import prepare, prepare_script
from research_agent.jobs.config_contract import load_job_config, binding_digest
from research_agent.research.workspace import initialize_workspace, admit_research_workspace


TERMINAL = {'succeeded', 'failed', 'cancelled', 'timed_out', 'collected'}


def run_job(root, request, timeout):
    path = root / (request['request_id'] + '.json')
    raw = (json.dumps(request) + '\n').encode()
    write_private(path, raw)
    receipt = execute('job.start', root, {'request_file': str(path), 'request_sha256': hashlib.sha256(raw).hexdigest()})
    deadline = time.monotonic() + timeout
    terminal, collected_outputs = False, False
    try:
        while time.monotonic() < deadline:
            status = execute('job.status', root, {'job_id': receipt['job_id']})
            if status['state'] in TERMINAL:
                terminal = True
                if status['state'] != 'succeeded':
                    raise RuntimeError('acceptance_job_' + status['state'])
                collected = execute('job.collect', root, {'job_id': receipt['job_id']})
                collected_outputs = True
                if not collected['output_validation']['complete']:
                    raise RuntimeError('acceptance_outputs_incomplete')
                return {'job_id': receipt['job_id'], 'status': 'execution_verified', 'cwd': receipt['cwd']}
            time.sleep(.2)
        raise RuntimeError('acceptance_queue_or_execution_timeout')
    finally:
        if not terminal:
            execute('job.cancel', root, {'job_id': receipt['job_id']})
            cleanup = time.monotonic() + min(30, timeout)
            while time.monotonic() < cleanup:
                if execute('job.status', root, {'job_id': receipt['job_id']})['state'] in TERMINAL:
                    terminal = True
                    break
                time.sleep(.2)
            if not terminal:
                raise RuntimeError('acceptance_cancellation_pending:' + receipt['job_id'])
        if terminal and receipt.get('metadata', {}).get('remote_dir'):
            if not collected_outputs:
                execute('job.collect', root, {'job_id': receipt['job_id']})
            from research_agent.jobs.remote import TorqueSSHPlatform
            settings = load_job_config(os.environ['RESEARCH_AGENT_JOB_CONFIG'])
            target = settings['environments'][request['platform']]
            remote = receipt['metadata']['remote_dir']
            scope = hashlib.sha256(str(Path(receipt['cwd']).resolve()).encode()).hexdigest()[:24]
            expected = target['remote_root'].rstrip('/') + '/' + receipt['job_id'] + '-' + scope
            if remote != expected:
                raise RuntimeError('acceptance_cleanup_path_mismatch')
            TorqueSSHPlatform(target, platform_name=request['platform'])._run_ssh('rm -rf -- ' + shlex.quote(remote))


def accept(config, package, directory, targets, timeout, *, bindings_only=False):
    os.environ['RESEARCH_AGENT_JOB_CONFIG'] = str(config)
    os.environ['RESEARCH_AGENT_PACKAGE_ROOT'] = str(package)
    settings = load_job_config(config)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    available = profiles(package)
    report = {'schema_version': 'research-agent-job-readiness/1', 'checked_at': datetime.now(timezone.utc).isoformat(),
              'configuration_sha256': binding_digest(settings), 'external_services': 'not_checked', 'targets': {}}
    for name, target in settings['environments'].items():
        if name not in targets:
            report['targets'][name] = {'status': 'not_verified'}
            continue
        row = report['targets'][name] = {'status': 'configuration_validated', 'jobs': []}
        try:
            selected = {'default_environment': name, 'environments': {name: target}}
            row['environments'] = check_environments(selected)[name]
            row['status'] = 'environment_verified'
            root = directory / name
            root.mkdir(mode=0o700)
            initialize_workspace(root, 'installation_' + name, 'research')
            admit_research_workspace(root)
            tested = set()
            for profile in available.values():
                for check in profile.get('checks', []):
                    if bindings_only and not check.get('script'):
                        continue
                    backend = check['backend']
                    if backend not in target.get('backends', {}):
                        continue
                    if check.get('script'):
                        script = resource(Path(profile['root']), check['script'])
                        request = prepare_script(config, name, backend, script, check.get('arguments', []),
                                                 collect=check.get('collect', []))
                    else:
                        inputs = {}
                        for role, value in check.get('inputs', {}).items():
                            source = root / (check['executor'] + '-' + role)
                            write_private(source, value.encode())
                            inputs[role] = source
                        request = prepare(config, name, check['executor'], '1', inputs, check.get('arguments', []))
                    # The bound walltime and cancellation cover both process
                    # execution and queue waits; no live research workspace is used.
                    request['timeout_seconds'] = timeout
                    result = run_job(root, request, timeout)
                    expected = check.get('result')
                    if expected:
                        value = json.loads((Path(result['cwd']) / expected['path']).read_text())
                        for key, wanted in expected.get('fields', {}).items():
                            if value.get(key) != wanted:
                                raise RuntimeError('acceptance_result_mismatch')
                    row['jobs'].append({k: v for k, v in result.items() if k != 'cwd'})
                    tested.add(backend)
            row['tested_backends'] = sorted(tested)
            row['untested_backends'] = sorted(target.get('backends', {}).keys() - tested)
            row['status'] = 'execution_verified' if tested else 'environment_verified'
        except (OSError, RuntimeError, ValueError) as error:
            row['status'] = 'failed'
            row['error'] = str(error)
    return report


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--config', type=Path, required=True)
    p.add_argument('--package-root', type=Path, required=True)
    p.add_argument('--directory', type=Path, required=True)
    p.add_argument('--report', type=Path, required=True)
    p.add_argument('--targets', type=json.loads, required=True)
    p.add_argument('--timeout', type=int, default=180)
    p.add_argument('--bindings-only', action='store_true')
    args = p.parse_args()
    report = accept(args.config, args.package_root, args.directory, args.targets, args.timeout, bindings_only=args.bindings_only)
    write_private(args.report, (json.dumps(report, indent=2) + '\n').encode())
    return int(any(row['status'] == 'failed' for row in report['targets'].values()))


if __name__ == '__main__':
    raise SystemExit(main())
