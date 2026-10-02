from __future__ import annotations
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any
import hashlib, json
class ProviderError(RuntimeError): pass
_REQUIRED=("operation","version","input_schema","parameter_schema","result_schema","output_roles","effects","limits")
@dataclass(frozen=True)
class CapabilityDescriptor:
    operation:str; version:str; input_schema:dict[str,Any]; parameter_schema:dict[str,Any]; result_schema:dict[str,Any]
    output_roles:tuple[str,...]=(); effects:tuple[str,...]=(); limits:dict[str,Any]=field(default_factory=dict)
    provider_id:str|None=None
    @classmethod
    def from_dict(cls, value):
        validate_descriptor(value)
        return cls(operation=value["operation"],version=value["version"],input_schema=value["input_schema"],parameter_schema=value["parameter_schema"],result_schema=value["result_schema"],output_roles=tuple(value["output_roles"]),effects=tuple(value["effects"]),limits=dict(value["limits"]),provider_id=value.get("provider_id"))
    def to_dict(self):
        return asdict(self)
def validate_descriptor(value:dict[str,Any])->dict[str,Any]:
    if not isinstance(value,dict): raise ProviderError("descriptor must be an object")
    missing=[k for k in _REQUIRED if k not in value]
    if missing: raise ProviderError("descriptor missing fields: "+", ".join(missing))
    if not isinstance(value["operation"],str) or not value["operation"]: raise ProviderError("descriptor operation invalid")
    if not isinstance(value["version"],str) or not value["version"]: raise ProviderError("descriptor version invalid")
    for k in ("input_schema","parameter_schema","result_schema","limits"):
        if not isinstance(value[k],dict): raise ProviderError(f"descriptor {k} must be object")
    for k in ("output_roles","effects"):
        if not isinstance(value[k],list) or any(not isinstance(x,str) or not x for x in value[k]): raise ProviderError(f"descriptor {k} must be string array")
    return value
def load_descriptor(path:str|Path)->CapabilityDescriptor:
    try:value=json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as e: raise ProviderError(f"invalid descriptor: {path}") from e
    return CapabilityDescriptor.from_dict(value)
def digest(value:Any)->str:
    return "sha256:"+hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
@dataclass(frozen=True)
class ProviderRequest:
    protocol_version:str; request_id:str; provider_id:str; operation:str; version:str; inputs:dict[str,Any]; parameters:dict[str,Any]; context:dict[str,Any]
    @classmethod
    def from_dict(cls,v):
        required=("protocol_version","request_id","provider_id","operation","version","inputs","parameters","context")
        if not isinstance(v,dict) or any(k not in v for k in required): raise ProviderError("malformed provider request")
        return cls(*(v[k] for k in required))
@dataclass(frozen=True)
class ProviderResult:
    status:str; result:dict[str,Any]|None=None; outputs:list[dict[str,Any]]=field(default_factory=list); provenance:dict[str,Any]=field(default_factory=dict); diagnostics:list[dict[str,Any]]=field(default_factory=list)
    def to_dict(self): return asdict(self)
