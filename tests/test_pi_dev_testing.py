from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TS_LOADER = ROOT / "tests" / "typescript_loader.mjs"


def test_development_cases_are_bounded_pytest_selectors() -> None:
    script = (
        f"const module=await import({json.dumps((ROOT / 'src/testing/cases.ts').as_uri())});"
        "process.stdout.write(JSON.stringify(module.DEVELOPMENT_TEST_CASES));"
    )
    cases = _node_json(script)

    assert {case["id"] for case in cases} == {
        "subagent-review",
        "subagent-compute",
        "subagent-artifacts",
        "subagent-lifecycle",
        "subagent-contracts",
        "subagent-all",
        "package-inventory",
        "workspace-contracts",
        "mcp-contracts",
    }
    assert all(case["selectors"] for case in cases)
    assert all(selector.startswith("tests/") for case in cases for selector in case["selectors"])
    compute = next(case for case in cases if case["id"] == "subagent-compute")
    assert compute["selectors"] == [
        "tests/test_pi_runtime_integration.py::test_real_pi_public_compute_prepare_uses_canonical_cli_result"
    ]


def test_development_extension_is_not_loaded_or_packed_by_default() -> None:
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))

    assert not any("ts-workflow-dev" in entry for entry in package["pi"]["extensions"])
    assert not any("ts-workflow-dev" in entry or "src/testing" in entry for entry in package["files"])


def test_development_extension_runs_registered_case_through_package_runtime() -> None:
    script = f"""
const module=await import({json.dumps((ROOT / 'extensions/ts-workflow-dev/index.ts').as_uri())});
const commands={{}};
const entries=[];
const execCalls=[];
const pi={{
  registerCommand:(name,value)=>commands[name]=value,
  registerEntryRenderer:()=>{{}},
  appendEntry:(type,data)=>entries.push({{type,data}}),
  exec:async(command,args,options)=>{{
    execCalls.push({{command,args,options}});
    return {{stdout:'1 passed in 0.10s',stderr:'',code:0,killed:false}};
  }},
}};
module.default(pi);
const uiCalls=[];
const ctx={{ui:{{
  setStatus:(...args)=>uiCalls.push(['status',...args]),
  setWidget:(...args)=>uiCalls.push(['widget',...args]),
  notify:(...args)=>uiCalls.push(['notify',...args]),
}}}};
await commands['ts-test'].handler('run subagent-review',ctx);
process.stdout.write(JSON.stringify({{commandNames:Object.keys(commands),entries,execCalls,uiCalls}}));
"""
    result = _node_json(script)

    assert result["commandNames"] == ["ts-test"]
    assert result["entries"][0]["data"]["outcome"] == "passed"
    assert result["entries"][0]["data"]["caseId"] == "subagent-review"
    call = result["execCalls"][0]
    assert call["command"] == "python3"
    assert call["args"][1:5] == ["run-isolated", "-m", "pytest", "-q"]
    assert call["args"][-1].endswith("test_real_pi_review_child_session_has_no_tools")
    assert any(item[0] == "status" and item[2] is None for item in result["uiCalls"])


def _node_json(script: str):
    completed = subprocess.run(
        ["node", "--experimental-loader", str(TS_LOADER), "--input-type=module", "--eval", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)
