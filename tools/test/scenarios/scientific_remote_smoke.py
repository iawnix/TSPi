"""Opt-in real backend smoke in an isolated workspace using a selected environment.

Launch once; advance polls existing Attempts and collects/parses settled jobs.
This checks software integration, not the validity of a reaction mechanism.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "packages/ts-agent-kernel"))
from ts_agent.workspace import bootstrap_workspace
from ts_agent.research import ResearchKernel
from tests.unit.test_scientific_analysis import request
from ts_agent.compute import import_calculation_artifact, create_calculation_intent, prepare_calculation, submit_calculation, calculation_status, collect_calculation, parse_calculation
from ts_agent.compute.analysis import run_analysis
from ts_agent.compute.artifacts import resolve_artifact_ref
from ts_agent.io import write_json, read_json
from ts_agent.report.builder import build_report_package


def xyz(root, node, name, content):
    return import_calculation_artifact(root, {"schema_version": "ts-artifact-import-request/2", "node_id": node,
        "format": "xyz_structure", "input_name": name, "content": content, "charge": 0, "multiplicity": 1})["artifact"]["artifact_id"]


def ensure_research_node(root, title: str, objective: str) -> str:
    research_map = ResearchKernel(root).load()
    existing = next((node for node in research_map.nodes.values() if node.title == title), None)
    if existing is not None:
        return existing.id
    ordinal = len(research_map.nodes) + 1
    phase_id = f"phase_{len(research_map.phases) + 1}"
    claim_id = f"claim_{len(research_map.claims) + 1}"
    node_id = f"node_{ordinal}"
    ResearchKernel(root).apply({
        "expected_revision": research_map.revision,
        "operations": [
            {"type": "create_phase", "id": phase_id, "title": "Remote integration smoke"},
            {"type": "create_claim", "id": claim_id, "statement": f"The {title} software interface is usable."},
            {"type": "create_node", "id": node_id, "title": title, "objective": objective, "phase_id": phase_id, "claim_ids": [claim_id]},
        ],
    })
    return node_id


def launch(root, environment, retry_capability=None):
    if root.exists():
        manifest = read_json(root / "smoke_manifest.json")
        if manifest["environment"] != environment:
            raise ValueError("existing smoke is bound to another environment")
    else:
        bootstrap_workspace(root)
        manifest = {"schema_version": "ts-scientific-remote-smoke/1", "environment": environment, "purpose": "real small-system integration smoke; no mechanism acceptance", "attempts": []}
    water = "3\nWater integration probe\nO 0 0 0\nH 0.757 0 0.586\nH -0.757 0 0.586\n"
    for capability in ("gaussian.opt_freq", "xtb.sp", "crest.conformer_search", "ase.neb"):
        previous = [record for record in manifest["attempts"] if record["capability"] == capability]
        if previous and capability != retry_capability:
            continue  # Never replay a prior submission, including an unknown result.
        if previous:
            if previous[-1].get("state") != "collection_error":
                raise ValueError("explicit retry requires a recorded collection error")
            status = calculation_status(root, previous[-1]["intent_id"])
            if status["state"] != "completed":
                raise ValueError("prior job must be confirmed completed before the explicit integration retry")
        node = ensure_research_node(root, capability + " integration smoke", "Verify selected software interface on a small molecule.")
        geometry = xyz(root, node, "water.xyz", water)
        parameters = {"charge": 0, "uhf": 0, "method": "gfn2"}
        inputs = [{"input_role": "xyz", "artifact_id": geometry}]
        if capability == "gaussian.opt_freq":
            built = run_analysis(root, request(node, "gaussian.input.build", {"task": "opt_freq", "method": "HF", "basis": "STO-3G", "charge": 0, "multiplicity": 1, "nproc": 2, "memory_mb": 512}, {"structures": [geometry]}))
            inputs = [{"input_role": "gjf", "artifact_id": built["output_artifacts"]["calculation.gjf"]["artifact_id"]}]
            parameters = {}
        elif capability == "crest.conformer_search":
            parameters.update({"search_level": "mquick", "threads": 2})
        elif capability == "ase.neb":
            product = xyz(root, node, "water_distorted.xyz", water.replace("0.757", "0.85").replace("probe", "distorted endpoint"))
            inputs = [{"input_role": "reactant", "artifact_id": geometry}, {"input_role": "product", "artifact_id": product}]
            parameters.update({"images": 3, "max_steps": 20, "fmax": 0.5, "interpolation": "linear"})
        intent = create_calculation_intent(root, {"schema_version": "ts-calculation-request/5", "node_id": node, "purpose": "Bounded small-system release integration smoke", "attempt_kind": "primary", "lineage": None,
            "capability": capability, "capability_version": "1", "input_artifacts": inputs, "parameters": parameters,
            "execution_target": {"kind": "remote", "environment": environment, "resources": {"queue": "batch", "nodes": 1, "ncpus": 2, "memory": "1gb", "walltime": "00:10:00", "ngpus": 0, "mpiprocs": None, "ompthreads": 2}}, "dry_run": False})
        record = {"node": node, "intent_id": intent["intent_id"], "capability": capability}
        if previous:
            record["retry_of"] = previous[-1]["intent_id"]
        manifest["attempts"].append(record)
        write_json(root / "smoke_manifest.json", manifest)
        prepare_calculation(root, intent["intent_ref"], intent["intent_digest"])
        submitted = submit_calculation(root, intent["intent_id"])
        record.update({"state": submitted["state"], "job_id": submitted.get("job_id")})
        write_json(root / "smoke_manifest.json", manifest)
        print(json.dumps(record), flush=True)


def advance(root):
    manifest = read_json(root / "smoke_manifest.json")
    for record in manifest["attempts"]:
        if record.get("state") in {"parsed", "failed", "stopped"}:
            print(json.dumps(record), flush=True)
            continue
        status = calculation_status(root, record["intent_id"])
        record["state"] = status["state"]
        if status["state"] == "completed":
            try:
                collected = collect_calculation(root, record["intent_id"])
            except Exception as exc:
                record.update({"state": "collection_error", "error": str(exc), "program_state": status["state"]})
                write_json(root / "smoke_manifest.json", manifest)
                print(json.dumps(record), flush=True)
                continue
            parsed = parse_calculation(root, record["intent_id"])
            record.update({"state": parsed["state"], "task_validation": parsed.get("task_validation"), "artifacts": collected["artifact_refs"]})
            if record["capability"] == "gaussian.opt_freq":
                primary = next(ref for ref in collected["artifact_refs"] if ref.endswith((".out", ".log")))
                artifact = resolve_artifact_ref(root, primary)
                analyzed = run_analysis(root, request(record["node"], "thermochemistry.evaluate", {
                    "species_key": "water", "quantity": "G", "stationary_kind": "minimum", "electronic_state": {"charge": 0, "multiplicity": 1},
                    "methods": {"electronic": "HF/STO-3G"}, "conditions": {"temperature_k": 298.15, "phase": "gas", "source_standard_state": {"kind": "pressure", "unit": "atm", "value": 1}, "standard_state": {"kind": "concentration", "unit": "mol/L", "value": 1}}}, {"electronic": [artifact["artifact_id"]]}))
                record["thermochemistry"] = analyzed
        write_json(root / "smoke_manifest.json", manifest)
        print(json.dumps(record), flush=True)
    if all(row.get("state") in {"parsed", "failed", "stopped", "collection_error"} for row in manifest["attempts"]):
        signature = [[row["intent_id"], row["state"]] for row in manifest["attempts"]]
        if manifest.get("report_signature") == signature:
            return
        report_dir = root / "reports" / ("smoke-" + "-".join(row["intent_id"] + "-" + row["state"] for row in manifest["attempts"]))
        manifest["report"] = build_report_package(root, report_dir)
        manifest["report_signature"] = signature
        write_json(root / "smoke_manifest.json", manifest)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("launch", "advance"))
    parser.add_argument("root", type=Path)
    parser.add_argument("--environment")
    parser.add_argument("--retry-capability", choices=("crest.conformer_search",), help="Explicitly retry a settled smoke after fixing its recorded output-capture error")
    args = parser.parse_args()
    if args.operation == "launch":
        if not args.environment:
            parser.error("launch requires --environment")
        launch(args.root, args.environment, args.retry_capability)
    else:
        advance(args.root)
