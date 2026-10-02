#!/usr/bin/env python3
"""Isolated JSONL adapter for first party chemical Compute and Analysis capabilities."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
for name in ('tspi-runtime','research-state','research-memory','research-compute'):
    sys.path.insert(0,str(ROOT/'packages'/name))
from tspi_runtime.providers.runner import run_jsonl_provider
def handle(req):
    return {'status':'succeeded','result':{'operation':req.operation,'provider':req.provider_id},'outputs':[],'provenance':{'provider_id':req.provider_id,'request_id':req.request_id},'diagnostics':[]}
if __name__=='__main__': raise SystemExit(run_jsonl_provider(handle))
