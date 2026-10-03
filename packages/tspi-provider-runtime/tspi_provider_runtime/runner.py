from __future__ import annotations
import json, sys, traceback
from typing import Callable, Any
from .protocol import PROVIDER_PROTOCOL_VERSION, ProviderRequest, ProviderError

def run_jsonl_provider(handler:Callable[[ProviderRequest],dict[str,Any]], *, stdin=None, stdout=None)->int:
    stdin=stdin or sys.stdin; stdout=stdout or sys.stdout
    for line in stdin:
        if not line.strip(): continue
        request = None
        try:
            request=ProviderRequest.from_dict(json.loads(line)); result=handler(request)
            if not isinstance(result,dict) or result.get("status") not in {"succeeded","failed","cancelled","timed_out"}: raise ProviderError("malformed provider result")
            provenance = result.get("provenance")
            if provenance is not None and (not isinstance(provenance, dict) or provenance.get("provider_id") not in {None, request.provider_id}):
                raise ProviderError("provider result provenance does not match request")
        except Exception as exc:
            result={"status":"failed","result":None,"outputs":[],"provenance":{},"diagnostics":[{"code":"provider_error","message":str(exc)}]}
        result.setdefault("protocol_version", PROVIDER_PROTOCOL_VERSION)
        result.setdefault("provenance", {})
        if request is not None:
            result["provenance"].setdefault("provider_id", request.provider_id)
            result["provenance"].setdefault("request_id", request.request_id)
        stdout.write(json.dumps(result,ensure_ascii=False,separators=(",",":"))+"\n"); stdout.flush()
    return 0
