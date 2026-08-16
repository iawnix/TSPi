from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from tests.v4_helpers import bootstrap_v4_workspace, start_research_act
from ts_compute.artifacts import list_calculation_artifacts
from ts_email.delivery import notify_user
from ts_report import build_report_package


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "src" / "artifacts" / "request-contract.cjs"
TS_LOADER = ROOT / "tests" / "typescript_loader.mjs"
ARTIFACT_EXTENSION = ROOT / "extensions" / "ts-workflow-artifacts" / "index.ts"


def test_public_import_tool_materializes_seed_without_journaling_body(tmp_path: Path) -> None:
    workspace = bootstrap_v4_workspace(tmp_path / "workspace")
    refs = start_research_act(workspace)
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
  operation:"import",actId:{json.dumps(refs['act_id'])},format:"xyz_structure",
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
    workspace = bootstrap_v4_workspace(tmp_path / "workspace")
    refs = start_research_act(workspace)
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
  operation:"generate",actId:{json.dumps(refs['act_id'])},smiles:{json.dumps(smiles)},
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
        "actId": refs["act_id"],
        "inputArtifactIds": [item["artifact_id"] for item in artifacts],
        "outputName": "candidate-comparison.png",
    }
    result = _contract_call("validateRenderRequest", workspace, request, artifacts)
    assert result["operation"] == "compare"
    assert result["actId"] == refs["act_id"]
    assert result["outputRef"] == f"acts/{refs['act_id']}/outputs/render/candidate-comparison.png"
    assert result["artifacts"][0]["artifactId"].startswith("art_")
    assert all(Path(item["path"]).is_absolute() for item in result["artifacts"])


@pytest.mark.parametrize("output_name", ["../escape.png", "/tmp/escape.png", "result.xyz", "nested/result.png"])
def test_render_request_rejects_agent_selected_paths(tmp_path: Path, output_name: str) -> None:
    workspace, refs, artifacts = _workspace_with_xyz(tmp_path)
    request = {
        "operation": "compare",
        "actId": refs["act_id"],
        "inputArtifactIds": [item["artifact_id"] for item in artifacts],
        "outputName": output_name,
    }
    completed = _contract_call("validateRenderRequest", workspace, request, artifacts, check=False)
    assert isinstance(completed, subprocess.CompletedProcess)
    assert completed.returncode == 2


def test_render_output_must_be_new_nonempty_regular_file(tmp_path: Path) -> None:
    workspace, refs, _artifacts = _workspace_with_xyz(tmp_path)
    output_ref = f"acts/{refs['act_id']}/outputs/render/candidate.png"
    missing = _contract_call("validateCreatedRenderOutput", workspace, output_ref, check=False)
    assert isinstance(missing, subprocess.CompletedProcess)
    assert missing.returncode == 2
    output = workspace / output_ref
    output.parent.mkdir(parents=True)
    output.write_bytes(b"PNG payload")
    result = _contract_call("validateCreatedRenderOutput", workspace, output_ref)
    assert result["size_bytes"] == len(b"PNG payload")
    assert result["sha256"] == "sha256:" + hashlib.sha256(b"PNG payload").hexdigest()


def test_report_package_is_verified_against_manifest_and_workspace_revision(tmp_path: Path) -> None:
    workspace = bootstrap_v4_workspace(tmp_path / "workspace")
    start_research_act(workspace)
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
    workspace = bootstrap_v4_workspace(tmp_path / "workspace")
    start_research_act(workspace)
    capture = tmp_path / "clawemail-args.json"
    config = _notification_install(tmp_path, capture=capture)
    monkeypatch.setenv("TS_NOTIFICATION_CONFIG", str(config))
    request = tmp_path / "notification.json"
    request.write_text(
        json.dumps(
            {
                "schema_version": "ts-user-notification/1",
                "event": "act_completed",
                "subject": "Research act completed",
                "summary": "The bounded research act completed.",
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


def test_notification_rejects_legacy_node_event_and_unsafe_report_ref(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = bootstrap_v4_workspace(tmp_path / "workspace")
    config = _notification_install(tmp_path)
    monkeypatch.setenv("TS_NOTIFICATION_CONFIG", str(config))
    request = tmp_path / "notification.json"
    base = {
        "schema_version": "ts-user-notification/1",
        "subject": "Progress",
        "summary": "Bounded progress update.",
        "report_refs": [],
    }
    request.write_text(json.dumps({**base, "event": "node_completed"}), encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported notification event"):
        notify_user(workspace, request)
    request.write_text(
        json.dumps({**base, "event": "progress", "report_refs": ["../outside.md"]}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="safe reports/"):
        notify_user(workspace, request)


def _workspace_with_xyz(tmp_path: Path) -> tuple[Path, dict[str, str], list[dict]]:
    workspace = bootstrap_v4_workspace(tmp_path / "workspace")
    refs = start_research_act(workspace)
    inputs = workspace / "inputs"
    inputs.mkdir(exist_ok=True)
    (inputs / "reactant.xyz").write_text("1\nR\nH 0 0 0\n", encoding="utf-8")
    (inputs / "candidate.xyz").write_text("1\nTS\nH 0 0 0.2\n", encoding="utf-8")
    catalog = list_calculation_artifacts(workspace)["artifacts"]
    artifacts = [item for item in catalog if item["path"] in {"inputs/reactant.xyz", "inputs/candidate.xyz"}]
    artifacts.sort(key=lambda item: item["path"])
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
