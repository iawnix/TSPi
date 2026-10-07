"""Prepare a local report Job with staged inputs; never execute the report."""
import argparse
import hashlib
import json
import os
from pathlib import Path


def prepare(entries, python, work_id=None):
    if not python or not Path(python).is_absolute() or not Path(python).is_file():
        raise ValueError('Provide the installed absolute TSPI_PYTHON path via --python')
    script = Path(__file__).with_name('build.py').resolve()
    inputs = [{'source': str(script), 'destination': 'scripts/build.py'}]
    argv = [python, 'scripts/build.py', '--output-dir', 'results']
    sources = []
    for index, entry in enumerate(entries):
        environment, filename = entry.split('=', 1)
        if not environment or not filename:
            raise ValueError('--result requires environment=path')
        path = Path(filename).resolve()
        content = path.read_bytes()
        json.loads(content)
        destination = f'inputs/result_{index}.json'
        inputs.append({'source': str(path), 'destination': destination})
        argv.extend(['--result', f'{environment}={destination}'])
        sources.append({'environment': environment, 'sha256': hashlib.sha256(content).hexdigest()})
    metadata = {'skill': 'report', 'sources': sources, 'script_sha256': hashlib.sha256(script.read_bytes()).hexdigest()}
    identity = hashlib.sha256(json.dumps([metadata, python], sort_keys=True).encode()).hexdigest()
    work_id = work_id or 'report_' + identity[:48]
    return {'requestId': 'report_' + hashlib.sha256(work_id.encode()).hexdigest()[:48],
            'workId': work_id, 'platform': 'local', 'command': argv, 'inputs': inputs,
            'outputs': [{'path': 'results/report.' + extension, 'required': True, 'minBytes': 1,
                         'mediaType': media} for extension, media in [('json', 'application/json'), ('md', 'text/markdown')]],
            'metadata': metadata}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--result', action='append', required=True, help='environment=path to result.json')
    parser.add_argument('--python', default=os.environ.get('TSPI_PYTHON'), help='Installed local Python (defaults to TSPI_PYTHON)')
    parser.add_argument('--work-id', help='New identity for an intentional rerun')
    parser.add_argument('--output', required=True, help='Request file inside the workspace')
    args = parser.parse_args()
    request = prepare(args.result, args.python, args.work_id)
    content = (json.dumps(request, indent=2) + '\n').encode()
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(content)
    print(json.dumps({'requestFile': str(output), 'requestSha256': hashlib.sha256(content).hexdigest()}))


if __name__ == '__main__':
    main()
