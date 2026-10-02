from __future__ import annotations
import json, subprocess, sys, time, uuid, hashlib
from pathlib import Path
from .protocol import CapabilityDescriptor, ProviderError, ProviderRequest, digest
class ProviderDispatcher:
    def __init__(self, descriptors=None): self._descriptors=dict(descriptors or {})
    def register(self, descriptor:CapabilityDescriptor):
        if descriptor.operation in self._descriptors: raise ProviderError(f"duplicate provider operation: {descriptor.operation}")
        self._descriptors[descriptor.operation]=descriptor
    def catalog(self): return [d.to_dict() for d in self._descriptors.values()]
    def readiness(self, operation): return {"operation":operation,"ready":operation in self._descriptors}
    def execute(self, operation, *, provider_id, entry, inputs=None, parameters=None, context=None, timeout=60):
        descriptor=self._descriptors.get(operation)
        if descriptor is None: raise ProviderError(f"unknown provider operation: {operation}")
        request={"protocol_version":"tspi-provider/1","request_id":uuid.uuid4().hex,"provider_id":provider_id,"operation":operation,"version":descriptor.version,"inputs":inputs or {},"parameters":parameters or {},"context":context or {}}
        proc=subprocess.Popen([sys.executable,str(entry)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            out,err=proc.communicate(json.dumps(request)+"\n",timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill(); proc.communicate(); return {"status":"timed_out","result":None,"outputs":[],"provenance":{"provider_id":provider_id,"operation":operation},"diagnostics":[{"code":"timeout"}]}
        if proc.returncode!=0: return {"status":"failed","result":None,"outputs":[],"provenance":{"provider_id":provider_id},"diagnostics":[{"code":"crash","message":err[-2000:]}]}
        try: result=json.loads(out.strip().splitlines()[-1])
        except Exception as e: raise ProviderError("malformed provider result") from e
        if result.get("status") not in {"succeeded","failed","cancelled","timed_out"}: raise ProviderError("invalid provider status")
        result.setdefault("provenance",{}).update({"provider_id":provider_id,"operation":operation,"descriptor_version":descriptor.version})
        for output in result.get("outputs",[]):
            if isinstance(output,dict) and "digest" in output and "content" in output: output["digest"]=digest(output["content"])
        return result
