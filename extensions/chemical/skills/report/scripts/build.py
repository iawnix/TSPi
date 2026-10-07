"""Build a reproducible report from validated Skill results, preserving gaps."""
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
        for step in result.get('steps',[]):
            rows.append({'environment':environment,'method':result['method'],'basis':result.get('basis'),
                         'task':step['task'],'energy_hartree':step.get('energy_hartree'),
                         'validated':result.get('validated') is True,'input_sha256':step.get('input_sha256')})
        if not result.get('validated'):
            rows.append({'environment':environment,'method':result.get('method'),'task':'failure','error':result.get('error'),'validated':False})
    return {'schema_version':'science-report/1','results':rows,'sources':sources}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--result',action='append',required=True,help='environment=path to result.json')
    p.add_argument('--output-dir',required=True)
    a=p.parse_args();out=Path(a.output_dir);out.mkdir(parents=True,exist_ok=True)
    if any(out.iterdir()):
        raise ValueError('report output directory must be empty; refusing to overwrite existing files')
    report=build(a.result)
    with (out/'report.json').open('x') as stream:
        stream.write(json.dumps(report,indent=2,ensure_ascii=False,allow_nan=False)+'\n')
    text=['# Calculation report','','This report lists supplied evidence. Missing matrix cells remain unverified.','',
          '| Environment | Method | Basis | Step | Energy (hartree) | Validated |','| --- | --- | --- | --- | --- | --- |']
    for row in report['results']:
        cells=[row.get(k,'') for k in ['environment','method','basis','task','energy_hartree','validated']]
        text.append('| '+' | '.join(str(v).replace('|','\\|').replace('\n',' ') for v in cells)+' |')
        if row.get('error'):text.extend(['',str(row['error']),''])
    text.extend(['','Absolute energies from different methods are not an accuracy ranking.','',
                 'Source file digests and input bindings are in report.json.'])
    with (out/'report.md').open('x') as stream:
        stream.write('\n'.join(text)+'\n')


if __name__=='__main__':main()
