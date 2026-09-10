from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
REVIEW_ROOT = ROOT / "packages" / "ts-agent-runtime" / "agents" / "review"
ROLE = REVIEW_ROOT / "roles" / "general.json"
ROLES = REVIEW_ROOT / "roles.cjs"
AGGREGATOR = REVIEW_ROOT / "aggregator.cjs"


def node_json(source: str) -> dict:
    completed = subprocess.run(
        ["node", "-e", source], cwd=ROOT, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def test_general_reviewer_role_is_versioned_and_advisory() -> None:
    role = json.loads(ROLE.read_text(encoding="utf-8"))
    assert role["schema_version"] == "ts-reviewer-role/1"
    assert role["role_id"] == "general"
    assert role["authority"] == "advisory"
    assert role["model_policy"] == {"mode": "inherit_parent", "allow_override": False}


def test_role_loader_rejects_unknown_role_and_accepts_general() -> None:
    result = node_json(
        f"const r=require({str(ROLES)!r});"
        "let error; try { r.loadReviewerRole('missing'); } catch (e) { error=e.message; }"
        "process.stdout.write(JSON.stringify({role:r.loadReviewerRole('general').role_id,error}));"
    )
    assert result == {"role": "general", "error": "unknown reviewer role: missing"}


def test_review_aggregator_preserves_failure_and_reports_disagreement() -> None:
    result = node_json(
        f"const {{aggregateReviewResults}}=require({str(AGGREGATOR)!r});"
        f"const role=require({str(ROLES)!r}).loadReviewerRole('general');"
        "const task={schema_version:'ts-agent-task/2',task_id:'sub_1',role:'review',authority:'advisory',operation:'claim_review',objective:'Review',"
        "workspace:{root:'/tmp/workspace',report_id:null,revision:null},scope:{report_id:null,node_refs:['node_1'],claim_refs:['claim_1']},"
        "inputs:{review_snapshot:{ref:'review-snapshot.json',schema_version:'ts-review-task-snapshot/3',sha256:'sha256:'+'a'.repeat(64),bytes:1},provider_input:{ref:'provider-input.json',schema_version:'ts-review-provider-input/5',sha256:'sha256:'+'b'.repeat(64),bytes:1}},"
        "capabilities:['ts_review_result'],constraints:{canonical_workspace_mutation:false,scientific_decision:false,recursive_delegation:false,remote_authority:'execution_mirror',external_side_effects:false},output_contract:'ts-agent-result/1'};"
        "const base=(summary,status)=>({schema_version:'ts-agent-result/1',task_id:'sub_1',role:'review',authority:'advisory',operation:'claim_review',outcome:'success',summary,scope:{report_id:null,node_refs:['node_1'],claim_refs:['claim_1']},facts:[{kind:'review',statement:summary,status,basis_refs:['claim_1']}],artifact_refs:[],program:null,payload:{missing_evidence:[],conflicts:[],options:[]},limitations:[],provenance:{source:'test'}});"
        "const output=aggregateReviewResults({task,reviewerResults:[{reviewer_role:'general',role_descriptor:role,result:base('one','supported')},{reviewer_role:'general',role_descriptor:role,result:base('two','contradicted')},{reviewer_role:'general',role_descriptor:role,failure:{kind:'provider_error',message:'provider failed'}}]});"
        "process.stdout.write(JSON.stringify(output));"
    )
    assert result["outcome"] == "partial"
    assert len(result["reviews"]) == 3
    assert len(result["disagreements"]) == 1
    assert result["failures"][0]["failure"]["kind"] == "provider_error"


def test_aggregator_rejects_invalid_role_descriptor() -> None:
    completed = subprocess.run(
        ["node", "-e", f"const r=require({str(ROLES)!r}); r.validateReviewerRole({{role_id:'bad'}});"],
        cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    assert completed.returncode != 0
    assert "unsupported reviewer role schema" in completed.stderr
