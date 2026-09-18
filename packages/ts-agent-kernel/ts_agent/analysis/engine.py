"""Immutable inputs, bounded outputs, and replayable local analysis evidence."""

from __future__ import annotations

import hashlib
import json
import math
from copy import deepcopy
from pathlib import Path
from typing import Any


def digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def number(value: Any, label: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label} must be finite")
    if positive and value <= 0:
        raise ValueError(f"{label} must be positive")
    return float(value)


def outcome(schema: str, data: dict, *, verdict: str = "valid", diagnostics=(), limitations=(), facts=None, files=None) -> dict:
    return {
        "schema_version": schema, "verdict": verdict, "data": data,
        "diagnostics": list(diagnostics), "limitations": list(limitations),
        "facts": facts or {}, "files": files or {},
    }


class Inputs:
    def __init__(self, bindings: dict[str, list[dict]], payloads: dict[str, bytes]):
        self.bindings, self.payloads = bindings, payloads

    def text(self, role: str, index: int = 0) -> str:
        return self.payloads[self.bindings[role][index]["artifact_id"]].decode("utf-8")

    def json(self, role: str, index: int = 0) -> dict:
        value = self.document(role, index)
        if value.get("schema_version") == "ts-scientific-analysis/1":
            value = value["result"]
        return value

    def document(self, role: str, index: int = 0) -> dict:
        value = json.loads(self.text(role, index))
        if not isinstance(value, dict):
            raise ValueError(f"{role} must contain a JSON object")
        return value

    def data(self, role: str, index: int = 0, *, schema: str | None = None) -> dict:
        document = self.json(role, index)
        if schema is not None and document.get("schema_version") != schema:
            raise ValueError(f"{role} requires {schema}")
        data = document.get("data", document)
        if not isinstance(data, dict):
            raise ValueError(f"{role} data must be an object")
        return data

    def xyz(self, role: str, index: int = 0):
        return xyz_frames(self.text(role, index))[0]


def xyz_frames(text: str, max_frames: int = 512) -> list[dict]:
    from ase.data import atomic_numbers

    lines = text.splitlines()
    frames = []
    cursor = 0
    while cursor < len(lines):
        if not lines[cursor].strip():
            cursor += 1
            continue
        count = int(lines[cursor])
        if not 1 <= count <= 4096 or cursor + count + 2 > len(lines):
            raise ValueError("invalid or oversized XYZ frame")
        symbols, coordinates = [], []
        for line in lines[cursor + 2:cursor + count + 2]:
            fields = line.split()
            if len(fields) < 4 or atomic_numbers.get(fields[0], 0) <= 0:
                raise ValueError("invalid XYZ atom")
            symbols.append(fields[0])
            coordinates.append([number(float(v), "XYZ coordinate") for v in fields[1:4]])
        frames.append({"symbols": symbols, "coordinates": coordinates, "comment": lines[cursor + 1]})
        if len(frames) > max_frames:
            raise ValueError(f"trajectory exceeds {max_frames} frames")
        cursor += count + 2
    if not frames:
        raise ValueError("XYZ input has no frames")
    return frames


def xyz_text(symbols, coordinates, comment="Generated structure; no optimization implied") -> str:
    return f"{len(symbols)}\n{comment}\n" + "".join(
        f"{symbol} {xyz[0]:.10f} {xyz[1]:.10f} {xyz[2]:.10f}\n"
        for symbol, xyz in zip(symbols, coordinates)
    )


def load_inputs(root: Path, supplied: dict) -> tuple[Inputs, list[dict]]:
    from ts_agent.workspace.artifacts import resolve_workspace_artifact_ids

    ids = list(dict.fromkeys(item for role in sorted(supplied) for item in supplied[role]))
    sources = resolve_workspace_artifact_ids(root, ids) if ids else []
    by_id = {item["artifact_id"]: item for item in sources}
    payloads = {}
    for record in sources:
        path = root / record["path"]
        if record["size_bytes"] > 32 * 1024 * 1024:
            raise ValueError("analysis input exceeds 32 MiB")
        payload = path.read_bytes()
        if digest(payload) != record["sha256"]:
            raise ValueError("analysis input changed during read")
        payloads[record["artifact_id"]] = payload
    if sum(map(len, payloads.values())) > 64 * 1024 * 1024:
        raise ValueError("analysis inputs exceed 64 MiB")
    return Inputs({role: [by_id[item] for item in values] for role, values in supplied.items()}, payloads), sources


def evaluate(capability: str, inputs: Inputs, parameters: dict) -> dict:
    from . import reaction, structures, transition_state, thermochemistry, kinetics, network

    handlers = {
        **reaction.HANDLERS, **structures.HANDLERS, **transition_state.HANDLERS,
        **thermochemistry.HANDLERS, **kinetics.HANDLERS, **network.HANDLERS,
    }
    handler = handlers.get(capability)
    if handler is None:
        raise ValueError(f"analysis has no registered implementation: {capability}")
    try:
        result = handler(inputs, deepcopy(parameters))
    except (KeyError, TypeError, IndexError) as exc:
        raise ValueError(f"{capability}: malformed or incomplete input record ({exc})") from exc
    # Reject NaN/Infinity at the evidence boundary.
    json.dumps(result, allow_nan=False)
    if result["verdict"] not in {"valid", "invalid", "inconclusive", "unsupported"}:
        raise ValueError("invalid scientific verdict")
    return result


def candidates(capability: str, node_id: str, result: dict, sources: list[dict]) -> dict:
    return {
        "schema_version": "ts-analysis-finding-candidates/1", "node_id": node_id,
        "capability": capability, "capability_version": "1",
        "parser": {"name": capability, "contract": result["schema_version"]},
        "source_artifacts": [{key: r[key] for key in ("artifact_id", "path", "sha256")} for r in sources],
        "candidates": [
            {
                "candidate_id": f"candidate_{i}", "concept_id": concept,
                "value": fact["value"], "unit": fact.get("unit"),
                "datatype": _datatype(fact["value"]),
                "qualifiers": {"capability": capability, "capability_version": "1", "producer_kind": "analysis", "parser_field": concept},
                "source_artifact_ids": [r["artifact_id"] for r in sources],
            }
            for i, (concept, fact) in enumerate(sorted(result["facts"].items()), 1)
        ],
    }


def _datatype(value):
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    return "json"


def normalized_result(result: dict) -> dict:
    return {
        **{key: value for key, value in result.items() if key != "files"},
        "files": {name: {"sha256": digest(content.encode()), "size_bytes": len(content.encode())}
                  for name, content in result["files"].items()},
    }


def run_scientific_analysis(root: str | Path, request: dict) -> dict:
    from ts_agent.compute.artifacts import (
        _workspace_root, _node_record, _node_analysis_directory, _write_artifact_payload,
        _artifact_for_path, _node_ids,
    )
    from ts_agent.workspace.transactions import workspace_lock

    workspace = _workspace_root(root)
    node_id, capability = request["node_id"], request["capability"]
    with workspace_lock(workspace):
        from ts_agent.workspace.dispatch import require_dispatch_allowed
        require_dispatch_allowed(workspace, node_id)
        if _node_record(workspace, node_id).get("state") == "closed":
            raise ValueError("scientific analysis requires an open ResearchNode")
        inputs, sources = load_inputs(workspace, request["input_artifacts"])
        result = evaluate(capability, inputs, request["parameters"])
        candidate_document = candidates(capability, node_id, result, sources)
        outputs = _node_analysis_directory(workspace, node_id)
        generated = {}
        created_paths = []
        try:
            for name, content in result["files"].items():
                if Path(name).name != name or Path(name).suffix not in {".xyz", ".gjf", ".json", ".svg", ".md"}:
                    raise ValueError("invalid analysis output basename")
                payload = content.encode()
                path = outputs / f"{Path(name).stem}_{digest(payload)[7:]}{Path(name).suffix}"
                if _write_artifact_payload(path, payload):
                    created_paths.append(path)
                generated[name] = _artifact_for_path(workspace, path, _node_ids(workspace))
            document = {
                "schema_version": "ts-scientific-analysis/1", "node_id": node_id,
                "capability": capability, "capability_version": "1",
                "input_artifacts": request["input_artifacts"], "parameters": request["parameters"],
                "source_artifacts": [{k: s[k] for k in ("artifact_id", "path", "sha256")} for s in sources],
                "result": normalized_result(result), "output_artifacts": generated,
                "finding_candidates": candidate_document,
            }
            payload = (json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
            if len(payload) > 4 * 1024 * 1024:
                raise ValueError("analysis evidence exceeds 4 MiB; reduce the input scope")
            path = outputs / f"{capability.replace('.', '_')}_{digest(payload)[7:]}.json"
            if _write_artifact_payload(path, payload):
                created_paths.append(path)
            artifact = _artifact_for_path(workspace, path, _node_ids(workspace))
        except Exception:
            for path in reversed(created_paths):
                path.unlink(missing_ok=True)
            raise
    return {
        "schema_version": "ts-analysis-result/1", "operation": "run", "node_id": node_id,
        "capability": capability, "capability_version": "1", "created": bool(created_paths),
        "analysis_artifact": artifact, "output_artifacts": generated,
        "input_artifact_ids": [r["artifact_id"] for r in sources],
        "verdict": result["verdict"], "diagnostics": result["diagnostics"][:32],
        "limitations": result["limitations"],
        "summary": f"{capability}@1: {result['verdict']}; {len(generated)} output files, {len(result['diagnostics'])} diagnostics.",
        "candidate_refs": [{"artifactId": artifact["artifact_id"], "candidateId": c["candidate_id"], "conceptId": c["concept_id"], "value": c["value"]} for c in candidate_document["candidates"]],
    }
