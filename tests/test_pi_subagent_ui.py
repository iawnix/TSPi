from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TS_LOADER = ROOT / "tests" / "typescript_loader.mjs"
STATUS = ROOT / "extensions" / "shared" / "subagent-status.ts"
STORE = ROOT / "extensions" / "ts-workflow-ui" / "activity-store.ts"
PANEL = ROOT / "extensions" / "ts-workflow-ui" / "activity-panel.ts"
DETAILS = ROOT / "extensions" / "ts-workflow-ui" / "agent-details.ts"
HISTORY = ROOT / "extensions" / "ts-workflow-ui" / "subagent-history.ts"
UI = ROOT / "extensions" / "ts-workflow-ui" / "index.ts"


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
start("review","ts_subagent_review",{{targetClaimRef:"claim_1"}},1000);
reduceTsToolActivity(store,{{type:"tool_execution_update",toolCallId:"review",toolName:"ts_subagent_review",partialResult:{{details:{{schema_version:"ts-subagent-status/2",seq:1,tool_call_id:"review",task_id:"sub_1",role:"review",operation:"claim_review",state:"waiting",started_at:new Date(1000).toISOString(),updated_at:new Date(2000).toISOString(),node_refs:["node_1"],claim_refs:["claim_1"],wait_reason:"model_response"}}}}}},2000);
start("compute","ts_subagent_compute",{{operation:"launch",backend:"gaussian",nodeId:"node_1"}},3000);
start("structure","ts_structure_seed",{{operation:"generate",optimization:"uff",nodeId:"node_1"}},3250);
start("artifact","ts_artifact_import",{{operation:"import",format:"xyz_structure",nodeId:"node_1"}},3500);
start("render","ts_render",{{operation:"compare",nodeId:"node_1",outputName:"compare.png"}},4000);
reduceTsToolActivity(store,{{type:"tool_execution_end",toolCallId:"render",toolName:"ts_render",result:{{}},isError:false}},5000);
const stale=reduceTsToolActivity(store,{{type:"tool_execution_update",toolCallId:"review",toolName:"ts_subagent_review",partialResult:{{details:{{schema_version:"ts-subagent-status/2",seq:0,tool_call_id:"review",task_id:"sub_1",role:"review",operation:"claim_review",state:"running",started_at:new Date(1000).toISOString(),updated_at:new Date(6000).toISOString()}}}}}},6000);
const before=sortedTsActivities(store);const pruned=pruneTsActivities(store,20001);const after=sortedTsActivities(store);
process.stdout.write(JSON.stringify({{before,after,summary:summarizeTsActivities(store),stale,pruned}}));
"""
    result = _node_json(script)
    by_id = {item["id"]: item for item in result["before"]}
    assert by_id["subagent:review"]["status"]["node_refs"] == ["node_1"]
    assert by_id["subagent:compute"]["status"]["operation"] == "launch"
    assert by_id["tool:structure"]["detail"] == "SMILES · uff"
    assert by_id["tool:artifact"]["detail"] == "xyz_structure · node_1"
    assert by_id["tool:render"]["detail"] == "compare.png"
    assert result["stale"] is False
    assert result["pruned"] is True
    assert all(item.get("activityKind") != "render" for item in result["after"])
    assert result["summary"]["active"] == 4


def test_activity_panel_renders_compact_review_compute_and_failure_rows() -> None:
    script = f"""
import {{ createTsActivityStore,reduceTsToolActivity }} from {json.dumps(STORE.as_uri())};
import {{ renderTsActivityPanel }} from {json.dumps(PANEL.as_uri())};
const store=createTsActivityStore();
for (const [id,name,args,time] of [
 ["review","ts_subagent_review",{{targetClaimRef:"claim_1"}},1000],
 ["compute","ts_subagent_compute",{{operation:"launch",backend:"gaussian",nodeId:"node_1"}},2000],
 ["report","ts_report",{{operation:"build",packageName:"final"}},3000],
]) reduceTsToolActivity(store,{{type:"tool_execution_start",toolCallId:id,toolName:name,args}},time);
reduceTsToolActivity(store,{{type:"tool_execution_end",toolCallId:"report",toolName:"ts_report",result:{{}},isError:true}},4000);
const widths=[38,64,100].map((width)=>({{width,lines:renderTsActivityPanel(store,width,5000,4,"ascii")}}));
process.stdout.write(JSON.stringify(widths));
"""
    rows = _node_json(script)
    for row in rows:
        text = "\n".join(item["text"] for item in row["lines"])
        assert "TS Activity" in text
        assert "Review" in text
        assert "Compute" in text
        assert "Report" in text
        assert all(len(item["text"]) <= row["width"] for item in row["lines"])


def test_subagent_history_merges_live_and_durable_roles_with_owner_paths() -> None:
    script = f"""
import {{ createTsActivityStore,reduceTsToolActivity }} from {json.dumps(STORE.as_uri())};
import {{ collectTsSubagentRecords,subagentSelectionLabel }} from {json.dumps(DETAILS.as_uri())};
const store=createTsActivityStore();
reduceTsToolActivity(store,{{type:"tool_execution_start",toolCallId:"live",toolName:"ts_subagent_review",args:{{targetClaimRef:"claim_1"}}}},1000);
const report={{agent_runs:[
  {{task_id:"sub_1",role:"review",authority:"advisory",operation:"claim_review",status:"completed",result_outcome:"success",node_refs:["node_1"],claim_refs:["claim_2"],run_ref:"reviews/claim_2/runs/sub_1",summary:"Completed review.",finished_at:"2026-08-16T00:00:00Z"}},
  {{task_id:"sub_2",role:"compute",authority:"operational",operation:"finalize",status:"completed",result_outcome:"success",node_refs:["node_2"],claim_refs:[],run_ref:"nodes/node_2/attempts/calc_1/runs/sub_2",summary:"Collected and parsed.",finished_at:"2026-08-16T00:01:00Z"}},
]}};
const records=collectTsSubagentRecords(store,report);
process.stdout.write(JSON.stringify({{records,labels:records.map(subagentSelectionLabel)}}));
"""
    result = _node_json(script)
    assert {item["task_id"] for item in result["records"]} == {"live", "sub_1", "sub_2"}
    durable = next(item for item in result["records"] if item["task_id"] == "sub_1")
    assert durable["run_ref"] == "reviews/claim_2/runs/sub_1"
    assert any("Review" in label for label in result["labels"])
    assert any("Compute" in label for label in result["labels"])


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
    assert "TS Subagent Run Details" in result["detail"][0]
    assert result["closed"] == 1


def test_ui_tracks_current_tools_and_history_covers_compute_and_review() -> None:
    source = UI.read_text(encoding="utf-8")
    assert 'const WIDGET_KEY = "ts-activity"' in source
    assert 'pi.registerCommand("ts-subagent-history"' in source
    assert "TS Subagent History" in source
    assert "Compute and Review subagent runs" in source
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
