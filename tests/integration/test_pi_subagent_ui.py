from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TS_LOADER = ROOT / "tests" / "support" / "typescript_loader.mjs"
STATUS = ROOT / "extensions" / "pi" / "shared" / "subagent-status.ts"
STORE = ROOT / "extensions" / "pi" / "ui" / "activity-store.ts"
DETAILS = ROOT / "extensions" / "pi" / "ui" / "agent-details.ts"
HISTORY = ROOT / "extensions" / "pi" / "ui" / "subagent-history.ts"
UI = ROOT / "extensions" / "pi" / "ui" / "index.ts"
UI_EXTENSION = ROOT / "extensions" / "pi" / "ui" / "extension.ts"


def test_subagent_status_reporter_is_monotonic_and_supports_both_roles() -> None:
    script = f"""
import {{ createSubagentStatusReporter,isTsSubagentStatus,terminalStateForReport,terminalStatusForError }} from {json.dumps(STATUS.as_uri())};
const times=[0,1000,2000,3000].map((value)=>new Date(value));let index=0;const updates=[];
const report=createSubagentStatusReporter({{tool_call_id:"call-1",task_id:"sub_1",role:"review",operation:"claim_review",target_ref:"claim_1"}},(value)=>updates.push(value.details),()=>times[index++]);
const waiting=report("waiting",{{wait_reason:"model_response",node_refs:["node_1"],claim_refs:["claim_1"]}});
const complete=report("completed",{{run_ref:"reviews/claim_1/runs/sub_1"}});
process.stdout.write(JSON.stringify({{waiting,complete,updates,valid:isTsSubagentStatus(complete),computeValid:isTsSubagentStatus({{...complete,role:"compute"}}),invalidRole:isTsSubagentStatus({{...complete,role:"render"}}),partial:terminalStateForReport({{outcome:"partial"}}),timeout:terminalStatusForError({{code:"TS_SUBAGENT_TIMEOUT"}})}}));
"""
    result = _node_json(script)
    assert result["waiting"]["seq"] == 1
    assert result["waiting"]["wait_reason"] == "model_response"
    assert result["complete"]["seq"] == 2
    assert "wait_reason" not in result["complete"]
    assert result["valid"] is True
    assert result["computeValid"] is True
    assert result["invalidRole"] is False
    assert result["partial"] == "partial"
    assert result["timeout"] == {"state": "failed", "failure_kind": "timeout"}


def test_activity_store_unifies_review_and_deterministic_tools_without_losing_identity() -> None:
    script = f"""
import {{ createTsActivityStore,reduceTsToolActivity,summarizeTsActivities,sortedTsActivities,pruneTsActivities }} from {json.dumps(STORE.as_uri())};
const store=createTsActivityStore();
const start=(id,name,args,now)=>reduceTsToolActivity(store,{{type:"tool_execution_start",toolCallId:id,toolName:name,args}},now);
start("review","ts_review",{{targetClaimId:"claim_1"}},1000);
reduceTsToolActivity(store,{{type:"tool_execution_update",toolCallId:"review",toolName:"ts_review",partialResult:{{details:{{schema_version:"ts-subagent-status/2",seq:1,tool_call_id:"review",task_id:"sub_1",role:"review",operation:"claim_review",state:"waiting",started_at:new Date(1000).toISOString(),updated_at:new Date(2000).toISOString(),node_refs:["node_1"],claim_refs:["claim_1"],wait_reason:"model_response"}}}}}},2000);
start("compute","ts_calc",{{operation:"launch",capability:"gaussian",nodeId:"node_1"}},3000);
start("structure","ts_seed",{{operation:"generate",optimization:"uff",nodeId:"node_1"}},3250);
start("analysis","ts_compare",{{operation:"compare",nodeId:"node_1"}},3375);
start("artifact","ts_import",{{operation:"import",format:"xyz_structure",inputName:"reference.xyz",nodeId:"node_1"}},3500);
start("render","ts_render",{{operation:"compare",nodeId:"node_1",outputName:"compare.png"}},4000);
reduceTsToolActivity(store,{{type:"tool_execution_end",toolCallId:"render",toolName:"ts_render",result:{{}},isError:false}},5000);
const stale=reduceTsToolActivity(store,{{type:"tool_execution_update",toolCallId:"review",toolName:"ts_review",partialResult:{{details:{{schema_version:"ts-subagent-status/2",seq:0,tool_call_id:"review",task_id:"sub_1",role:"review",operation:"claim_review",state:"running",started_at:new Date(1000).toISOString(),updated_at:new Date(6000).toISOString()}}}}}},6000);
const before=sortedTsActivities(store);const pruned=pruneTsActivities(store,20001);const after=sortedTsActivities(store);
process.stdout.write(JSON.stringify({{before,after,summary:summarizeTsActivities(store),stale,pruned}}));
"""
    result = _node_json(script)
    by_id = {item["id"]: item for item in result["before"]}
    assert by_id["subagent:review"]["status"]["node_refs"] == ["node_1"]
    assert by_id["subagent:compute"]["status"]["operation"] == "launch"
    assert by_id["subagent:compute"]["capability"] == "gaussian"
    assert by_id["tool:structure"]["detail"] == "SMILES · uff"
    assert by_id["tool:analysis"]["detail"] == "XYZ comparison"
    assert by_id["tool:artifact"]["detail"] == "reference.xyz"
    assert by_id["tool:render"]["detail"] == "compare.png"
    assert result["stale"] is False
    assert result["pruned"] is True
    assert all(item.get("activityKind") != "render" for item in result["after"])
    assert result["summary"]["active"] == 5


def test_subagent_history_merges_live_and_durable_roles_with_owner_paths() -> None:
    script = f"""
import {{ createTsActivityStore,reduceTsToolActivity }} from {json.dumps(STORE.as_uri())};
import {{ collectTsSubagentRecords,renderTsSubagentDetails,subagentRunLabel,subagentSelectionLabel,subagentSelectionParts }} from {json.dumps(DETAILS.as_uri())};
const store=createTsActivityStore();
const toolCallId="call_028def15-cbb5-42b4-bbfc-cfbd256c4a0b";
reduceTsToolActivity(store,{{type:"tool_execution_start",toolCallId,toolName:"ts_review",args:{{targetClaimId:"claim_1"}}}},1000);
const report={{agent_runs:[
  {{task_id:"sub_1",role:"review",authority:"advisory",operation:"claim_review",status:"completed",result_outcome:"success",node_refs:["node_1"],claim_refs:["claim_2"],run_ref:"reviews/claim_2/runs/sub_1",summary:"Completed review.",started_at:"2026-08-16T00:00:00Z",finished_at:"2026-08-16T00:02:14Z"}},
  {{task_id:"sub_2",role:"compute",authority:"operational",operation:"finalize",capability:"gaussian",intent_id:"calc_1",status:"completed",result_outcome:"success",node_refs:["node_2"],claim_refs:[],run_ref:"nodes/node_2/attempts/calc_1/runs/sub_2",summary:"Collected and parsed.",started_at:"2026-08-16T00:00:53Z",finished_at:"2026-08-16T00:01:00Z"}},
]}};
const records=collectTsSubagentRecords(store,report);
const pending=records.find((record)=>record.task_id===toolCallId);
process.stdout.write(JSON.stringify({{records,labels:records.map(subagentSelectionLabel),parts:records.map((record)=>subagentSelectionParts(record,Date.parse("2026-08-16T00:03:00Z"))),pendingLabel:subagentRunLabel(pending),pendingDetails:renderTsSubagentDetails(pending,{{}},80)}}));
"""
    result = _node_json(script)
    tool_call_id = "call_028def15-cbb5-42b4-bbfc-cfbd256c4a0b"
    assert {item["task_id"] for item in result["records"]} == {tool_call_id, "sub_1", "sub_2"}
    durable = next(item for item in result["records"] if item["task_id"] == "sub_1")
    assert durable["run_ref"] == "reviews/claim_2/runs/sub_1"
    pending = next(item for item in result["records"] if item["task_id"] == tool_call_id)
    assert pending["task_id_pending"] is True
    assert result["pendingLabel"] == "ID pending"
    assert tool_call_id not in "\n".join(result["labels"] + result["pendingDetails"])
    assert any("ID pending" in value for value in result["labels"])
    assert any("sub_1" in value for value in result["labels"])
    assert any("Review" in label for label in result["labels"])
    assert any("Compute" in label for label in result["labels"])
    assert any("claim_2" in label and "claim review" in label for label in result["labels"])
    assert any("Gaussian collect and parse" in label for label in result["labels"])
    assert any(part["right"] == "done · 02:14" for part in result["parts"])
    assert result["pendingDetails"][0] == "ID pending · Review · queued"


def test_review_history_browser_pages_eight_runs_and_opens_details() -> None:
    script = f"""
import {{ SubagentHistoryBrowser,SUBAGENT_HISTORY_PAGE_SIZE }} from {json.dumps(HISTORY.as_uri())};
const records=Array.from({{length:10}},(_,i)=>{{const ordinal=i+1;const compute=i%2===1;return {{task_id:`sub_${{ordinal}}`,role:compute?"compute":"review",authority:compute?"operational":"advisory",operation:compute?"inspect":"claim_review",state:i===9?"failed":"completed",node_refs:[`node_${{ordinal}}`],claim_refs:compute?[]:[`claim_${{ordinal}}`],run_ref:compute?`nodes/node_${{ordinal}}/attempts/calc_${{ordinal}}/runs/sub_${{ordinal}}`:`reviews/claim_${{ordinal}}/runs/sub_${{ordinal}}`,live:false}}}});
let renders=0;let closed=0;const keybindings={{matches:(data,action)=>data===action}};const theme={{fg:(_c,t)=>t,bg:(_c,t)=>t}};
const browser=new SubagentHistoryBrowser({{records,workspaceRoot:"/tmp/workspace",tui:{{requestRender:()=>renders++}},theme,keybindings,done:()=>closed++,notifyWarning:()=>{{}},readDocuments:()=>({{result:{{summary:"Bounded review."}},run:{{metadata:{{}}}}}})}});
const first=browser.render(64);browser.handleInput("tui.select.pageDown");const second=browser.render(64);browser.handleInput("tui.select.confirm");const detail=browser.render(64);browser.handleInput("tui.select.cancel");browser.handleInput("tui.select.cancel");
process.stdout.write(JSON.stringify({{pageSize:SUBAGENT_HISTORY_PAGE_SIZE,first,second,detail,snapshot:browser.getSnapshot(),renders,closed}}));
"""
    result = _node_json(script)
    assert result["pageSize"] == 8
    assert "Page 1/2" in "\n".join(result["first"])
    assert "Page 2/2" in "\n".join(result["second"])
    assert "sub_9 · Review · done" in result["detail"][0]
    assert result["closed"] == 1


def test_subagent_details_prioritize_outcome_and_error_before_scope_and_audit() -> None:
    script = f"""
import {{ renderTsSubagentDetails }} from {json.dumps(DETAILS.as_uri())};
const record={{task_id:"sub_7",role:"compute",authority:"operational",operation:"finalize",capability:"gaussian",state:"failed",node_refs:["node_3"],claim_refs:[],target_ref:"calc_4",run_ref:"nodes/node_3/attempts/calc_4/runs/sub_7",started_at:"2026-08-26T07:42:00Z",finished_at:"2026-08-26T07:42:07Z",summary:"Collection stopped before parsing.",error_code:"PROGRAM_OUTPUT_MISSING",error_message:"gaussian.out was not created",live:false}};
const documents={{result:{{summary:"Collection stopped before parsing.",artifact_refs:["art_0123456789abcdef01234567"]}},actions:{{actions:[{{tool:"collect",result:{{action_status:"failed"}}}}]}},run:{{error:{{code:"PROGRAM_OUTPUT_MISSING",message:"gaussian.out was not created"}},metadata:{{failure_stage:"collect"}}}}}};
process.stdout.write(JSON.stringify(renderTsSubagentDetails(record,documents,80)));
"""
    lines = _node_json(script)
    assert lines[0] == "sub_7 · Compute · failed"
    assert lines.index("Outcome") < lines.index("Error") < lines.index("Scope") < lines.index("Audit")
    assert any("Gaussian collect and parse" in line for line in lines)
    assert any("calc_4" in line for line in lines)
    assert any("PROGRAM_OUTPUT_MISSING" in line for line in lines)
    assert any("Journal" in line for line in lines)


def test_rpc_subagent_history_uses_run_owner_action_and_audit_sections() -> None:
    script = f"""
import {{ formatTsSubagentHistoryMarkdown }} from {json.dumps(UI.as_uri())};
const record={{task_id:"sub_3",role:"review",authority:"advisory",operation:"claim_review",state:"completed",node_refs:["node_2"],claim_refs:["claim_1"],run_ref:"reviews/claim_1/runs/sub_3",started_at:"2026-08-26T07:40:00Z",finished_at:"2026-08-26T07:42:14Z",summary:"The cited observations support the scoped claim.",live:false}};
process.stdout.write(formatTsSubagentHistoryMarkdown([record]));
"""
    completed = subprocess.run(
        ["node", "--experimental-loader", str(TS_LOADER), "--input-type=module", "--eval", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    text = completed.stdout
    assert "## `sub_3` · Review · done" in text
    assert "- Owner: `claim_1`" in text
    assert "- Action: claim review" in text
    assert "- Elapsed: `02:14`" in text
    assert "Outcome" in text
    assert "Audit journal: `reviews/claim_1/runs/sub_3`" in text
    assert "- Task:" not in text


def test_ui_tracks_current_tools_and_history_covers_compute_and_review() -> None:
    source = UI_EXTENSION.read_text(encoding="utf-8")
    catalog = json.loads((ROOT / "packages" / "ts-agent-kernel" / "ts_agent" / "command_catalog.json").read_text(encoding="utf-8"))
    assert "setWidget" not in source
    assert 'pi.registerCommand("runs"' in source
    assert "TS Subagent History" in source
    assert catalog["slash_commands"]["runs"]["description"] == "Browse active and recorded Compute and Review runs."
    assert "ts-workspace-compute-operator-run" not in source
    assert "ts-workspace-artifact-operator-run" not in source
    assert "ts_subagent_render" not in source
    assert "ts_subagent_report" not in source


def _node_json(script: str):
    completed = subprocess.run(
        ["node", "--experimental-loader", str(TS_LOADER), "--input-type=module", "--eval", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)
