from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from tests.workspace_helpers import bootstrap_workspace_fixture, start_research_node
from ts_compute.artifacts import list_calculation_artifacts
from ts_email.delivery import notify_user
from ts_email.errors import NotificationError
from ts_report import build_report_package


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "src" / "artifacts" / "request-contract.cjs"
TS_LOADER = ROOT / "tests" / "typescript_loader.mjs"
ARTIFACT_EXTENSION = ROOT / "extensions" / "ts-workflow-artifacts" / "index.ts"


def test_public_import_tool_materializes_seed_without_journaling_body(tmp_path: Path) -> None:
    workspace = bootstrap_workspace_fixture(tmp_path / "workspace")
    refs = start_research_node(workspace)
    content = "2\nH2\nH 0 0 0\nH 0 0 0.74\n"
    script = f"""
import install from {json.dumps(ARTIFACT_EXTENSION.as_uri())};
import {{ spawnSync }} from "node:child_process";
process.env.TS_AGENT_PYTHON={json.dumps(sys.executable)};
const tools={{}};const entries=[];const updates=[];
const pi={{
  registerTool:(tool)=>tools[tool.name]=tool,
  appendEntry:(type,data)=>entries.push({{type,data}}),
  exec:async(command,args)=>{{
    const value=spawnSync(command,args,{{encoding:"utf8",env:process.env}});
    return {{code:value.status,stdout:value.stdout,stderr:value.stderr}};
  }},
}};
install(pi);
await tools.ts_artifact_import.execute("call-import",{{
  operation:"import",nodeId:{json.dumps(refs['node_id'])},format:"xyz_structure",
  content:{json.dumps(content)},charge:0,multiplicity:1,
}},undefined,(value)=>updates.push(value),{{cwd:{json.dumps(str(workspace))}}});
process.stdout.write(JSON.stringify({{entries,updates}}));
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
    value = json.loads(completed.stdout)
    result = value["entries"][0]["data"]
    assert value["entries"][0]["type"] == "ts-deterministic-activity"
    assert result["schema_version"] == "ts-artifact-import-result/1"
    assert result["artifact"]["artifact_id"].startswith("art_")
    activity = workspace / result["activity_ref"]
    request = json.loads((activity / "request.json").read_text(encoding="utf-8"))
    status = json.loads((activity / "status.json").read_text(encoding="utf-8"))
    assert request["kind"] == "artifact_import"
    assert "content" not in json.dumps(request)
    assert content not in json.dumps(request)
    assert status["status"] == "completed"
    assert stat.S_IMODE((activity / "request.json").stat().st_mode) == 0o600


def test_public_structure_seed_tool_generates_xyz_without_journaling_smiles(tmp_path: Path) -> None:
    workspace = bootstrap_workspace_fixture(tmp_path / "workspace")
    refs = start_research_node(workspace)
    smiles = "C1=CCCCC1"
    script = f"""
import install from {json.dumps(ARTIFACT_EXTENSION.as_uri())};
import {{ spawnSync }} from "node:child_process";
process.env.TS_AGENT_PYTHON={json.dumps(sys.executable)};
const tools={{}};const entries=[];const updates=[];
const pi={{
  registerTool:(tool)=>tools[tool.name]=tool,
  appendEntry:(type,data)=>entries.push({{type,data}}),
  exec:async(command,args)=>{{
    const value=spawnSync(command,args,{{encoding:"utf8",env:process.env}});
    return {{code:value.status,stdout:value.stdout,stderr:value.stderr}};
  }},
}};
install(pi);
await tools.ts_structure_seed.execute("call-seed",{{
  operation:"generate",nodeId:{json.dumps(refs['node_id'])},smiles:{json.dumps(smiles)},
  charge:0,multiplicity:1,optimization:"uff",
}},undefined,(value)=>updates.push(value),{{cwd:{json.dumps(str(workspace))}}});
process.stdout.write(JSON.stringify({{entries,updates}}));
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
    value = json.loads(completed.stdout)
    result = value["entries"][0]["data"]
    assert value["entries"][0]["type"] == "ts-deterministic-activity"
    assert result["schema_version"] == "ts-structure-seed-result/1"
    assert result["artifact"]["artifact_id"].startswith("art_")
    assert result["provenance_artifact"]["artifact_id"].startswith("art_")
    activity = workspace / result["activity_ref"]
    request = json.loads((activity / "request.json").read_text(encoding="utf-8"))
    status = json.loads((activity / "status.json").read_text(encoding="utf-8"))
    assert request["kind"] == "structure_seed"
    assert request["request"]["source_format"] == "smiles"
    assert request["request"]["optimization"] == "uff"
    assert "smiles" not in request["request"]
    assert smiles not in json.dumps(request)
    assert status["status"] == "completed"


def test_render_request_resolves_logical_ids_and_host_owns_output_path(tmp_path: Path) -> None:
    workspace, refs, artifacts = _workspace_with_xyz(tmp_path)
    request = {
        "operation": "compare",
        "nodeId": refs["node_id"],
        "inputArtifactIds": [item["artifact_id"] for item in artifacts],
        "outputName": "candidate-comparison.png",
    }
    result = _contract_call("validateRenderRequest", workspace, request, artifacts)
    assert result["operation"] == "compare"
    assert result["nodeId"] == refs["node_id"]
    assert result["outputRef"] == f"nodes/{refs['node_id']}/outputs/render/candidate-comparison.png"
    assert result["artifacts"][0]["artifactId"].startswith("art_")
    assert all(Path(item["path"]).is_absolute() for item in result["artifacts"])


def test_mechanism_request_requires_ordered_reactant_ts_product(tmp_path: Path) -> None:
    workspace, refs, artifacts = _workspace_with_xyz(tmp_path)
    request = {
        "operation": "mechanism",
        "nodeId": refs["node_id"],
        "inputArtifactIds": [item["artifact_id"] for item in artifacts],
        "outputName": "mechanism.png",
    }

    result = _contract_call("validateRenderRequest", workspace, request, artifacts)
    assert len(result["artifacts"]) == 3

    rejected = _contract_call(
        "validateRenderRequest",
        workspace,
        {**request, "inputArtifactIds": request["inputArtifactIds"][:2]},
        artifacts[:2],
        check=False,
    )
    assert isinstance(rejected, subprocess.CompletedProcess)
    assert rejected.returncode == 2
    assert "reactant, transition state, product" in rejected.stderr


@pytest.mark.parametrize("output_name", ["../escape.png", "/tmp/escape.png", "result.xyz", "nested/result.png"])
def test_render_request_rejects_agent_selected_paths(tmp_path: Path, output_name: str) -> None:
    workspace, refs, artifacts = _workspace_with_xyz(tmp_path)
    request = {
        "operation": "compare",
        "nodeId": refs["node_id"],
        "inputArtifactIds": [item["artifact_id"] for item in artifacts],
        "outputName": output_name,
    }
    completed = _contract_call("validateRenderRequest", workspace, request, artifacts, check=False)
    assert isinstance(completed, subprocess.CompletedProcess)
    assert completed.returncode == 2


def test_render_output_must_be_new_nonempty_regular_file(tmp_path: Path) -> None:
    workspace, refs, _artifacts = _workspace_with_xyz(tmp_path)
    output_ref = f"nodes/{refs['node_id']}/outputs/render/candidate.png"
    missing = _contract_call("validateCreatedRenderOutput", workspace, output_ref, check=False)
    assert isinstance(missing, subprocess.CompletedProcess)
    assert missing.returncode == 2
    output = workspace / output_ref
    output.parent.mkdir(parents=True)
    output.write_bytes(b"PNG payload")
    result = _contract_call("validateCreatedRenderOutput", workspace, output_ref)
    assert result["size_bytes"] == len(b"PNG payload")
    assert result["sha256"] == "sha256:" + hashlib.sha256(b"PNG payload").hexdigest()


def test_render_tool_persists_bounded_backend_failure_details(tmp_path: Path) -> None:
    workspace, refs, artifacts = _workspace_with_xyz(tmp_path)
    fake = tmp_path / "xyzrender"
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "print('xyzrender: error: deliberate adapter failure', file=sys.stderr)\n"
        "raise SystemExit(2)\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    script = f"""
import install from {json.dumps(ARTIFACT_EXTENSION.as_uri())};
import {{ spawnSync }} from "node:child_process";
process.env.TS_AGENT_PYTHON={json.dumps(sys.executable)};
process.env.TS_AGENT_DISABLE_RUNTIME_REEXEC="1";
process.env.TS_RENDER_XYZRENDER={json.dumps(str(fake))};
const tools={{}};const entries=[];
const pi={{
  registerTool:(tool)=>tools[tool.name]=tool,
  appendEntry:(type,data)=>entries.push({{type,data}}),
  exec:async(command,args)=>{{
    const value=spawnSync(command,args,{{encoding:"utf8",env:process.env}});
    return {{code:value.status,stdout:value.stdout,stderr:value.stderr}};
  }},
}};
install(pi);
try {{
  await tools.ts_render.execute("call-render",{{
    operation:"compare",nodeId:{json.dumps(refs['node_id'])},
    inputArtifactIds:{json.dumps([item['artifact_id'] for item in artifacts])},
    outputName:"failed-comparison.png",
  }},undefined,undefined,{{cwd:{json.dumps(str(workspace))}}});
}} catch (error) {{
  process.stdout.write(JSON.stringify({{name:error.name,message:error.message,entries}}));
}}
"""

    completed = _node_ts(script)
    value = json.loads(completed.stdout)
    assert value["name"] == "RenderBackendError"
    assert "exit 2" in value["message"]
    assert "deliberate adapter failure" in value["message"]
    activity = workspace / "nodes" / refs["node_id"] / "activities" / "op_1"
    status = json.loads((activity / "status.json").read_text(encoding="utf-8"))
    result = json.loads((activity / "result.json").read_text(encoding="utf-8"))
    assert status["status"] == "failed"
    assert status["error"]["name"] == "RenderBackendError"
    assert result["backend_failure"]["backend"] == "xyzrender"
    assert result["backend_failure"]["stage"] == "xyzrender"
    assert result["backend_failure"]["returncode"] == 2
    assert "deliberate adapter failure" in result["backend_failure"]["stderr_tail"]
    assert len(result["backend_failure"]["stderr_tail"]) <= 8192


def test_report_package_is_verified_against_manifest_and_workspace_revision(tmp_path: Path) -> None:
    workspace = bootstrap_workspace_fixture(tmp_path / "workspace")
    start_research_node(workspace)
    package = workspace / "reports" / "study-report"
    built = build_report_package(workspace, package)
    manifest = Path(built["manifest"])
    digest = "sha256:" + hashlib.sha256(manifest.read_bytes()).hexdigest()
    result = _contract_call(
        "validateCreatedReportPackage",
        workspace,
        "reports/study-report",
        digest,
        built["workspace_revision"],
        built["operational_revision"],
    )
    assert result["package_ref"] == "reports/study-report"
    assert result["manifest_digest"] == digest
    assert result["file_count"] >= 8

    tampered = package / "final_report.md"
    tampered.write_text(tampered.read_text(encoding="utf-8") + "tampered\n", encoding="utf-8")
    # The manifest digest alone is not enough: every listed file remains checked by the report builder tests.
    # Adding an unlisted file is rejected directly at this host boundary.
    (package / "unlisted.txt").write_text("unexpected\n", encoding="utf-8")
    rejected = _contract_call(
        "validateCreatedReportPackage",
        workspace,
        "reports/study-report",
        digest,
        built["workspace_revision"],
        built["operational_revision"],
        check=False,
    )
    assert isinstance(rejected, subprocess.CompletedProcess)
    assert rejected.returncode == 2
    assert "contents do not match" in rejected.stderr


def test_notification_uses_fixed_installation_recipient_and_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = bootstrap_workspace_fixture(tmp_path / "workspace")
    start_research_node(workspace)
    capture = tmp_path / "clawemail-args.json"
    config = _notification_install(tmp_path, capture=capture)
    monkeypatch.setenv("TS_NOTIFICATION_CONFIG", str(config))
    request = tmp_path / "notification.json"
    request.write_text(
        json.dumps(
            {
                "schema_version": "ts-user-notification/1",
                "event": "node_completed",
                "subject": "Research node completed",
                "summary": "The bounded research node completed.",
                "report_refs": [],
            }
        ),
        encoding="utf-8",
    )

    first = notify_user(workspace, request)
    second = notify_user(workspace, request)
    args = json.loads(capture.read_text(encoding="utf-8"))
    assert first["state"] == "sent"
    assert second["state"] == "already_sent"
    assert first["notification_digest"] == second["notification_digest"]
    assert args[args.index("--to") + 1] == "researcher@example.org"
    assert stat.S_IMODE((workspace / first["receipt_ref"]).stat().st_mode) == 0o600


def test_notification_rejects_removed_act_event_and_unsafe_report_ref(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = bootstrap_workspace_fixture(tmp_path / "workspace")
    config = _notification_install(tmp_path)
    monkeypatch.setenv("TS_NOTIFICATION_CONFIG", str(config))
    request = tmp_path / "notification.json"
    base = {
        "schema_version": "ts-user-notification/1",
        "subject": "Progress",
        "summary": "Bounded progress update.",
        "report_refs": [],
    }
    request.write_text(json.dumps({**base, "event": "act_completed"}), encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported notification event"):
        notify_user(workspace, request)
    request.write_text(
        json.dumps({**base, "event": "progress", "report_refs": ["../outside.md"]}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="safe reports/"):
        notify_user(workspace, request)


def test_notification_accepts_only_unchanged_manifested_report_members(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = bootstrap_workspace_fixture(tmp_path / "workspace")
    start_research_node(workspace)
    package = workspace / "reports" / "progress-report"
    build_report_package(workspace, package)
    capture = tmp_path / "clawemail-args.json"
    config = _notification_install(tmp_path, capture=capture)
    monkeypatch.setenv("TS_NOTIFICATION_CONFIG", str(config))
    request = tmp_path / "notification.json"
    request.write_text(json.dumps({
        "schema_version": "ts-user-notification/1",
        "event": "progress",
        "subject": "Research progress",
        "summary": "A manifest-bound report is attached.",
        "report_refs": ["reports/progress-report/final_report.md"],
    }), encoding="utf-8")

    result = notify_user(workspace, request)

    assert result["ok"] is True
    assert result["attachment_refs"] == ["reports/progress-report/final_report.md"]
    args = json.loads(capture.read_text(encoding="utf-8"))
    assert Path(args[args.index("--attach") + 1]).name == "00-final_report.md"

    loose = workspace / "reports" / "loose" / "final_report.md"
    loose.parent.mkdir()
    loose.write_text("not packaged\n", encoding="utf-8")
    request.write_text(json.dumps({
        "schema_version": "ts-user-notification/1",
        "event": "progress",
        "subject": "Unbound report",
        "summary": "This must be rejected.",
        "report_refs": ["reports/loose/final_report.md"],
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="manifest"):
        notify_user(workspace, request)


def test_notification_cli_json_failure_is_structured(tmp_path: Path) -> None:
    workspace = bootstrap_workspace_fixture(tmp_path / "workspace")
    request = tmp_path / "notification.json"
    request.write_text(json.dumps({
        "schema_version": "ts-user-notification/1",
        "event": "progress",
        "subject": "Progress",
        "summary": "No notification installation is configured.",
        "report_refs": [],
    }), encoding="utf-8")
    environment = dict(os.environ)
    environment.pop("TS_NOTIFICATION_CONFIG", None)

    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "ts_email.py"),
            "notify",
            "--root",
            str(workspace),
            "--request-file",
            str(request),
            "--json",
        ],
        cwd=ROOT,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert completed.returncode == 2
    assert completed.stderr == ""
    payload = json.loads(completed.stdout)
    assert payload["schema_version"] == "ts-user-notification-error/1"
    assert payload["ok"] is False
    assert payload["retry_disposition"] == "fix_request"
    assert payload["error"]["code"] == "NOTIFICATION_REQUEST_REJECTED"


def test_notification_preserves_bounded_provider_diagnostic_without_retrying(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = bootstrap_workspace_fixture(tmp_path / "workspace")
    start_research_node(workspace)
    config = _notification_install(tmp_path)
    manager = tmp_path / "clawemail" / "bin" / "clawemail-manager"
    manager.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "print('Body: private-preview-text')\n"
        "print('error: not authorized; token=private-value; Authorization: Bearer bearer-secret; "
        "url=https://user:password@example.org/send', file=sys.stderr)\n"
        "raise SystemExit(2)\n",
        encoding="utf-8",
    )
    manager.chmod(0o755)
    monkeypatch.setenv("TS_NOTIFICATION_CONFIG", str(config))
    request = tmp_path / "notification.json"
    request.write_text(json.dumps({
        "schema_version": "ts-user-notification/1",
        "event": "progress",
        "subject": "Progress",
        "summary": "The provider should reject this test message.",
        "report_refs": [],
    }), encoding="utf-8")

    with pytest.raises(NotificationError) as captured:
        notify_user(workspace, request)

    assert captured.value.error_class == "delivery_ambiguous"
    assert captured.value.retry_disposition == "reconcile_only"
    assert "error: not authorized" in str(captured.value)
    assert "private-value" not in str(captured.value)
    assert "bearer-secret" not in str(captured.value)
    assert "user:password" not in str(captured.value)
    assert "private-preview-text" not in str(captured.value)
    receipt = json.loads((workspace / str(captured.value.receipt_ref)).read_text(encoding="utf-8"))
    assert receipt["state"] == "unknown"
    assert receipt["error_class"] == "delivery_ambiguous"
    assert "error: not authorized" in receipt["error"]
    assert "private-value" not in receipt["error"]
    assert "bearer-secret" not in receipt["error"]
    assert "user:password" not in receipt["error"]
    assert "private-preview-text" not in receipt["error"]


def test_json_adapter_preserves_plain_command_error_without_syntax_noise() -> None:
    script = (
        f"const summary=require({json.dumps(str(ROOT / 'extensions' / 'ts-workflow-control' / 'summary.cjs'))});"
        "try{summary.parseJsonOutput({stderr:'error: not authorized'});}"
        "catch(error){process.stdout.write(error.message);process.exitCode=2;}"
    )
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert completed.returncode == 2
    assert completed.stdout == "error: not authorized"
    assert "Unexpected token" not in completed.stdout


def test_notification_adapter_preserves_structured_failure_semantics() -> None:
    workspace_cli = ROOT / "extensions" / "shared" / "workspace-cli.ts"
    script = f"""
import {{ runNotifyUserJson }} from {json.dumps(workspace_cli.as_uri())};
process.env.TS_AGENT_PYTHON = process.execPath;
const payload = {{
  schema_version: "ts-user-notification-error/1",
  ok: false,
  state: "failed",
  retry_disposition: "retry_after_fix",
  receipt_ref: "reports/email/deliveries/test.json",
  error: {{
    code: "NOTIFICATION_DELIVERY_NOT_STARTED",
    class: "delivery_not_started",
    message: "email notification was not started: authorization rejected",
  }},
}};
const pi = {{exec: async () => ({{stdout: JSON.stringify(payload)}})}};
try {{
  await runNotifyUserJson(pi, "/tmp/workspace", {{schema_version:"ts-user-notification/1"}});
}} catch (error) {{
  process.stdout.write(JSON.stringify({{
    name: error.name,
    message: error.message,
    code: error.code,
    error_class: error.error_class,
    state: error.state,
    retry_disposition: error.retry_disposition,
    receipt_ref: error.receipt_ref,
  }}));
}}
"""
    result = json.loads(_node_ts(script).stdout)
    assert result == {
        "name": "NotificationError",
        "message": "email notification was not started: authorization rejected",
        "code": "NOTIFICATION_DELIVERY_NOT_STARTED",
        "error_class": "delivery_not_started",
        "state": "failed",
        "retry_disposition": "retry_after_fix",
        "receipt_ref": "reports/email/deliveries/test.json",
    }


def _workspace_with_xyz(tmp_path: Path) -> tuple[Path, dict[str, str], list[dict]]:
    workspace = bootstrap_workspace_fixture(tmp_path / "workspace")
    refs = start_research_node(workspace)
    inputs = workspace / "inputs"
    inputs.mkdir(exist_ok=True)
    (inputs / "reactant.xyz").write_text("1\nR\nH 0 0 0\n", encoding="utf-8")
    (inputs / "candidate.xyz").write_text("1\nTS\nH 0 0 0.2\n", encoding="utf-8")
    (inputs / "product.xyz").write_text("1\nP\nH 0 0 0.4\n", encoding="utf-8")
    catalog = list_calculation_artifacts(workspace)["artifacts"]
    artifacts = [
        item
        for item in catalog
        if item["path"] in {"inputs/reactant.xyz", "inputs/candidate.xyz", "inputs/product.xyz"}
    ]
    order = {
        "inputs/reactant.xyz": 0,
        "inputs/candidate.xyz": 1,
        "inputs/product.xyz": 2,
    }
    artifacts.sort(key=lambda item: order[item["path"]])
    return workspace, refs, artifacts


def _contract_call(function_name: str, *args: object, check: bool = True) -> object:
    encoded = [json.dumps(str(value) if isinstance(value, Path) else value) for value in args]
    script = (
        f"const helper=require({json.dumps(str(CONTRACT))});"
        f"const args=[{','.join(encoded)}];"
        f"try{{const value=helper[{json.dumps(function_name)}](...args);"
        "process.stdout.write(JSON.stringify(value,(key,item)=>key.endsWith('Path')?String(item):item));}"
        "catch(error){process.stderr.write(error.message);process.exitCode=2;}"
    )
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if check:
        assert completed.returncode == 0, completed.stderr
        return json.loads(completed.stdout)
    return completed


def _node_ts(script: str) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ["node", "--experimental-loader", str(TS_LOADER), "--input-type=module", "--eval", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return completed


def _notification_install(tmp_path: Path, *, capture: Path | None = None) -> Path:
    claw = tmp_path / "clawemail"
    (claw / "bin").mkdir(parents=True)
    (claw / ".clawemail").mkdir()
    (claw / "SKILL.md").write_text("---\nname: clawemail\n---\n", encoding="utf-8")
    manager = claw / "bin" / "clawemail-manager"
    capture_line = f"Path({str(capture)!r}).write_text(json.dumps(sys.argv[1:]))\n" if capture else ""
    manager.write_text(
        "#!/usr/bin/env python3\n"
        "import json,sys\n"
        "from pathlib import Path\n"
        + capture_line
        + "print(json.dumps({'ok': True}))\n",
        encoding="utf-8",
    )
    manager.chmod(0o755)
    for name in ("skill.json", "mail-cli.json"):
        path = claw / ".clawemail" / name
        path.write_text("{}\n", encoding="utf-8")
        path.chmod(0o600)
    config = tmp_path / "notifications.toml"
    config.write_text(
        "[notifications.email]\n"
        "enabled = true\n"
        'recipient = "researcher@example.org"\n'
        f'clawemail_root = "{claw}"\n',
        encoding="utf-8",
    )
    config.chmod(0o600)
    return config
