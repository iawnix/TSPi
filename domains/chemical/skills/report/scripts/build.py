"""Summarize supplied runner evidence without certifying scientific conclusions."""
import argparse
import hashlib
import json
from pathlib import Path


def build(entries):
    rows=[];sources=[]
    for entry in entries:
        environment,filename=entry.split('=',1);path=Path(filename)
        result=json.loads(path.read_text())
        sources.append({'environment':environment,'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
        # The old validated flag had incompatible meanings across runners. Keep
        # historical files intact; never translate it into scientific acceptance.
        checks = result.get('checks_passed') if result.get('schema_version') == 'science-result/2' else None
        for step in result.get('steps',[]):
            rows.append({'environment':environment,'method':result['method'],'basis':result.get('basis'),
                         'task':step['task'],'energy_hartree':step.get('energy_hartree'),
                         'checks_passed':checks, 'scientific_validation':'not_assessed',
                         'source_schema':result.get('schema_version'), 'input_sha256':step.get('input_sha256')})
        if checks is not True:
            rows.append({'environment':environment,'method':result.get('method'),
                         'task':'failure' if result.get('error') else 'unverified',
                         'scientific_validation':'not_assessed',
                         'checks_passed':checks, 'error':result.get('error')})
    return {'schema_version':'science-report/2','results':rows,'sources':sources}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--result',action='append',default=[],help='environment=path to standalone result.json')
    p.add_argument('--job',action='append',default=[],help='Job directory; read environment and result location from its receipts')
    p.add_argument('--output-dir',required=True)
    a=p.parse_args()
    if not a.result and not a.job: p.error('supply --job or --result')
    for directory in a.job:
        job = Path(directory).resolve()
        receipt = json.loads((job/'receipt.json').read_text())
        intent = json.loads((job.parents[2]/'operations/jobs'/f'{job.name}.json').read_text())
        if receipt.get('job_id') != job.name or intent.get('job_id') != job.name:
            raise ValueError('job identity does not match report source')
        cwd = Path(receipt['cwd']).resolve()
        if not cwd.is_relative_to(job): raise ValueError('job result directory is outside the Job')
        a.result.append(f"{intent['platform']}={cwd/'results/result.json'}")
    out=Path(a.output_dir);out.mkdir(parents=True,exist_ok=True)
    if any(out.iterdir()):
        raise ValueError('report output directory must be empty; refusing to overwrite existing files')
    report=build(a.result)
    with (out/'report.json').open('x') as stream:
        stream.write(json.dumps(report,indent=2,ensure_ascii=False,allow_nan=False)+'\n')
    text=['# Calculation report','','This report lists supplied evidence. Missing matrix cells remain unverified.','',
          'Runner checks do not establish a minimum, transition state, or mechanism. Scientific assessments are recorded separately.', '',
          '| Environment | Method | Basis | Step | Energy (hartree) | Runner checks |','| --- | --- | --- | --- | --- | --- |']
    for row in report['results']:
        cells=[row.get(k,'') for k in ['environment','method','basis','task','energy_hartree','checks_passed']]
        text.append('| '+' | '.join(str(v).replace('|','\\|').replace('\n',' ') for v in cells)+' |')
        if row.get('error'):text.extend(['',str(row['error']),''])
    text.extend(['','Absolute energies from different methods are not an accuracy ranking.','',
                 'Source file digests and input bindings are in report.json.'])
    with (out/'report.md').open('x') as stream:
        stream.write('\n'.join(text)+'\n')


if __name__=='__main__':main()
