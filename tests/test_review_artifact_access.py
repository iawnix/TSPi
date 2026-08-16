from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ACCESS = ROOT / "src" / "agents" / "review" / "artifact-access.cjs"
ARTIFACT_TOOL = ROOT / "src" / "agents" / "review" / "artifact-tool.ts"
TS_LOADER = ROOT / "tests" / "typescript_loader.mjs"


def test_reader_revalidates_digest_and_rejects_unavailable_section(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = workspace / "diagnostic.log"
    source.write_text("normal termination\n", encoding="utf-8")
    manifest = [_manifest(source, "diagnostic.log")]

    unavailable = _read(workspace, manifest, [{"artifact_id": manifest[0]["artifact_id"], "section": "frequencies"}])
    assert unavailable.returncode == 2
    assert "section is unavailable" in unavailable.stderr

    source.write_text("changed after binding\n", encoding="utf-8")
    drifted = _read(workspace, manifest, [{"artifact_id": manifest[0]["artifact_id"], "section": "tail"}])
    assert drifted.returncode == 2
    assert "size changed" in drifted.stderr or "content changed" in drifted.stderr

    source.unlink()
    missing = _read(workspace, manifest, [{"artifact_id": manifest[0]["artifact_id"], "section": "tail"}])
    assert missing.returncode == 2
    assert "artifact is unavailable" in missing.stderr
    assert str(workspace) not in missing.stderr


def test_reader_rejects_symlink_escape(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.log"
    outside.write_text("outside\n", encoding="utf-8")
    (workspace / "escape.log").symlink_to(outside)
    manifest = [_manifest(outside, "escape.log")]

    completed = _read(workspace, manifest, [{"artifact_id": manifest[0]["artifact_id"], "section": "tail"}])
    assert completed.returncode == 2
    assert "symlink escapes workspace" in completed.stderr


def test_empty_artifact_reports_no_section_without_false_truncation(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = workspace / "empty.log"
    source.write_bytes(b"")
    manifest = [_manifest(source, "empty.log")]

    completed = _read(workspace, manifest, [{"artifact_id": manifest[0]["artifact_id"], "section": "tail"}])
    assert completed.returncode == 0, completed.stderr
    excerpt = json.loads(completed.stdout)[0]
    assert excerpt["found"] is False
    assert excerpt["truncated"] is False
    assert excerpt["text"] == ""


def test_artifact_tool_allows_one_bounded_batch_and_keeps_audit_private(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = workspace / "diagnostic.txt"
    source.write_text(("warning: bounded diagnostic\n" * 2000), encoding="utf-8")
    manifest = [_manifest(source, "diagnostic.txt")]
    payload = tmp_path / "payload.json"
    payload.write_text(json.dumps({"workspace": str(workspace), "manifest": manifest}), encoding="utf-8")
    script = f"""
import {{ readFileSync }} from "node:fs";
import {{ createReviewArtifactReadCapture, createReviewArtifactReadTool }} from {json.dumps(ARTIFACT_TOOL.as_uri())};
const value=JSON.parse(readFileSync(process.argv[1],"utf8"));
const capture=createReviewArtifactReadCapture();
const tool=createReviewArtifactReadTool(value.workspace,value.manifest,capture);
const requests=["document","overview","diagnostics","head","tail"].map(section=>({{artifact_id:value.manifest[0].artifact_id,section}}));
const first=await tool.execute("call_1",{{requests}});
let secondError=null;
try{{await tool.execute("call_2",{{requests:[requests[0]]}});}}catch(error){{secondError=error.message;}}
process.stdout.write(JSON.stringify({{first,capture:{{completed:capture.completed,actions:capture.actions,readArtifactIds:[...capture.readArtifactIds]}},secondError}}));
"""
    completed = _node_ts(script, str(payload))
    value = json.loads(completed.stdout)
    result = json.loads(value["first"]["content"][0]["text"])

    assert value["capture"]["completed"] is True
    assert value["capture"]["readArtifactIds"] == [manifest[0]["artifact_id"]]
    assert "one successful batch" in value["secondError"]
    assert len(result["excerpts"]) == 5
    assert sum(item["excerpt_bytes"] for item in result["excerpts"]) <= 12 * 1024
    assert all(item["excerpt_bytes"] <= 4 * 1024 for item in result["excerpts"])
    assert all("path" not in item for item in result["excerpts"])
    assert len(value["capture"]["actions"]) == 5
    assert all("path" not in item and "text" not in item for item in value["capture"]["actions"])


def test_provider_manifest_omits_physical_path(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = workspace / "gaussian.out"
    source.write_text("Normal termination of Gaussian\n", encoding="utf-8")
    manifest = [_manifest(source, "gaussian.out", artifact_type="gaussian_output")]
    payload = tmp_path / "manifest.json"
    payload.write_text(json.dumps(manifest), encoding="utf-8")
    script = (
        f"const fs=require('node:fs');const access=require({json.dumps(str(ACCESS))});"
        "process.stdout.write(JSON.stringify(access.providerArtifactManifest(JSON.parse(fs.readFileSync(process.argv[1],'utf8')))));"
    )
    completed = _node(script, str(payload))
    provider = json.loads(completed.stdout)

    assert provider[0]["artifact_id"] == manifest[0]["artifact_id"]
    assert "path" not in provider[0]
    assert "gaussian.out" not in completed.stdout


def _manifest(source: Path, relative_path: str, *, artifact_type: str = "text_document") -> dict[str, object]:
    digest = "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest()
    sections = {
        "text_document": ["document", "overview", "diagnostics", "head", "tail"],
        "gaussian_output": [
            "overview",
            "route",
            "termination",
            "optimization",
            "frequencies",
            "final_geometry",
            "irc",
            "diagnostics",
            "head",
            "tail",
        ],
    }[artifact_type]
    return {
        "artifact_id": "art_" + hashlib.sha256(f"{relative_path}:{digest}".encode()).hexdigest()[:24],
        "path": relative_path,
        "sha256": digest,
        "size_bytes": source.stat().st_size,
        "owner_act": None,
        "source_intent_id": None,
        "artifact_type": artifact_type,
        "available_sections": sections,
    }


def _read(
    workspace: Path,
    manifest: list[dict[str, object]],
    requests: list[dict[str, str]],
) -> subprocess.CompletedProcess[str]:
    payload = workspace.parent / "read.json"
    payload.write_text(json.dumps({"workspace": str(workspace), "manifest": manifest, "requests": requests}), encoding="utf-8")
    script = (
        f"const fs=require('node:fs');const access=require({json.dumps(str(ACCESS))});"
        "const value=JSON.parse(fs.readFileSync(process.argv[1],'utf8'));"
        "try{process.stdout.write(JSON.stringify(access.readArtifactSections({workspaceRoot:value.workspace,artifactManifest:value.manifest,requests:value.requests})));}"
        "catch(error){process.stderr.write(error.message);process.exitCode=2;}"
    )
    return _node(script, str(payload), check=False)


def _node(script: str, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ["node", "-e", script, *args],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
    )
    if check:
        assert completed.returncode == 0, completed.stderr
    return completed


def _node_ts(script: str, *args: str) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ["node", "--experimental-loader", str(TS_LOADER), "--input-type=module", "--eval", script, *args],
        cwd=ROOT,
        env={**os.environ},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return completed
