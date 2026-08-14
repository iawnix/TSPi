"""Build immutable v3 Markdown report packages from validated facts."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .context import collect_report_context, node_label, node_program_outcome


def build_final_report(root: str | Path) -> str:
    return render_final_report(collect_report_context(root))


def build_report_package(root: str | Path, output_dir: str | Path | None = None) -> dict[str, str]:
    root_path = Path(root).resolve()
    package_dir = Path(output_dir).resolve() if output_dir is not None else root_path / "reports" / "final_report_package"
    context = collect_report_context(root_path)
    if package_dir.exists():
        raise ValueError(f"report package already exists: {package_dir}")
    package_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{package_dir.name}.tmp-", dir=package_dir.parent))
    try:
        (staging / "assets").mkdir()
        _write_json(staging / "report_context.json", context)
        _write_json(staging / "claims.json", {"claims": context["claims"], "focus_claim_refs": context["focus_claim_refs"]})
        _write_json(staging / "gate_results.json", {"gate_results": context["gate_results"]})
        _write_json(
            staging / "evidence_index.json",
            {
                "evidence": [
                    {
                        "evidence_id": row.get("evidence_id"),
                        "node_id": row.get("node_id"),
                        "kind": row.get("kind"),
                        "summary": row.get("summary"),
                        "artifact_refs": row.get("artifact_refs", []),
                    }
                    for row in context["evidence_records"]
                ]
            },
        )
        (staging / "final_report.md").write_text(render_final_report(context), encoding="utf-8")
        (staging / "email_summary.md").write_text(render_email_summary(context), encoding="utf-8")
        manifest = _package_manifest(staging, context["workspace_revision"])
        _write_json(staging / "package_manifest.json", manifest)
        manifest_digest = _sha256_file(staging / "package_manifest.json")
        os.rename(staging, package_dir)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return {
        "package_dir": str(package_dir),
        "report": str(package_dir / "final_report.md"),
        "context": str(package_dir / "report_context.json"),
        "email_summary": str(package_dir / "email_summary.md"),
        "assets_dir": str(package_dir / "assets"),
        "manifest": str(package_dir / "package_manifest.json"),
        "manifest_digest": manifest_digest,
        "workspace_revision": str(context["workspace_revision"]),
    }


def render_final_report(context: dict[str, Any]) -> str:
    claims = context.get("claims", [])
    gates = context.get("gate_results", [])
    evidence = context.get("evidence_records", [])
    accepted = context.get("accepted_artifacts", [])
    focus = set(context.get("focus_claim_refs", []))
    lines = [
        "# Transition-State Research Report",
        "",
        "## Executive Status",
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| Workspace | `{context['workspace_root']}` |",
        f"| Workspace revision | `{context['workspace_revision']}` |",
        f"| Focus claims | `{', '.join(context.get('focus_claim_refs', [])) or 'none'}` |",
        f"| Accepted artifacts | `{', '.join(context.get('accepted_refs', [])) or 'none'}` |",
        f"| Nodes / claims / evidence / gates | {len(context.get('nodes', []))} / {len(claims)} / {len(evidence)} / {len(gates)} |",
        "",
        _executive_sentence(claims, accepted, focus),
        "",
        "## Scientific Claims",
        "",
        "| Claim | Kind | Status | Statement | Required gates |",
        "| --- | --- | --- | --- | --- |",
    ]
    for claim in claims:
        marker = " (focus)" if claim.get("claim_id") in focus else ""
        lines.append(
            f"| `{claim.get('claim_id', '')}`{marker} | `{claim.get('kind', '')}` | `{claim.get('status', '')}` | "
            f"{_escape(str(claim.get('statement', '')))} | `{', '.join(claim.get('required_gates', [])) or 'none'}` |"
        )
    lines.extend([
        "",
        "## Deterministic Gate Results",
        "",
        "| Gate result | Gate / policy | Verdict | Target | Evidence | Diagnostics |",
        "| --- | --- | --- | --- | --- | --- |",
    ])
    for gate in gates:
        lines.append(
            f"| `{gate.get('gate_result_id', '')}` | `{gate.get('gate', '')}` / `{gate.get('policy', '')}` | "
            f"`{gate.get('verdict', '')}` | `{gate.get('target_ref') or ''}` | "
            f"`{', '.join(gate.get('evidence_refs', []))}` | {_escape('; '.join(gate.get('diagnostics', [])))} |"
        )
    lines.extend([
        "",
        "## Evidence Facts",
        "",
        "| Evidence | Kind / tier | Owner node | Summary | Facts | Artifacts |",
        "| --- | --- | --- | --- | --- | --- |",
    ])
    for row in evidence:
        facts = json.dumps(row.get("facts", {}), sort_keys=True, separators=(",", ":"))
        lines.append(
            f"| `{row.get('evidence_id', '')}` | `{row.get('kind', '')}` / `{row.get('evidence_tier', '')}` | "
            f"`{row.get('node_id', '')}` | {_escape(str(row.get('summary', '')))} | `{_escape(facts)}` | "
            f"`{', '.join(row.get('artifact_refs', [])) or 'none'}` |"
        )
    lines.extend([
        "",
        "## Research Nodes",
        "",
        "| Node | Parent | State | Tags | Outcome | Objective |",
        "| --- | --- | --- | --- | --- | --- |",
    ])
    for node in context.get("nodes", []):
        lines.append(
            f"| `{node.get('node_id', '')}` | `{node.get('parent_node') or ''}` | `{node.get('state', '')}` | "
            f"{_escape(node_label(node))} | `{node_program_outcome(node)}` | {_escape(str(node.get('objective', '')))} |"
        )
    lines.extend(["", "## Accepted Artifacts", ""])
    if accepted:
        for artifact in accepted:
            lines.append(
                f"- `{artifact.get('acceptance_id')}`: target `{artifact.get('target_ref')}`, policy "
                f"`{artifact.get('policy')}`, gates `{', '.join(artifact.get('gate_result_refs', []))}`."
            )
    else:
        lines.append("- No claim has an accepted artifact.")
    lines.extend(["", "## Limitations And Operational Follow-up", ""])
    unresolved = context.get("unresolved_controls", [])
    pending_reviews = context.get("pending_review_dispositions", [])
    if unresolved:
        lines.append(f"- {len(unresolved)} unresolved compute control record(s) remain.")
    if pending_reviews:
        lines.append(f"- {len(pending_reviews)} advisory Review response(s) remain pending.")
    open_questions = [
        question
        for node in context.get("nodes", [])
        if isinstance(node.get("result"), dict)
        for question in node["result"].get("open_questions", [])
    ]
    lines.extend(f"- {question}" for question in open_questions)
    if not unresolved and not pending_reviews and not open_questions:
        lines.append("- No additional operational or recorded scientific limitation is open.")
    lines.extend([
        "",
        "The Root Agent owns research strategy and claim updates. Gate verdicts above are deterministic evaluations of registered facts.",
    ])
    return "\n".join(lines) + "\n"


def render_email_summary(context: dict[str, Any]) -> str:
    claims = context.get("claims", [])
    focus = set(context.get("focus_claim_refs", []))
    focus_rows = [row for row in claims if row.get("claim_id") in focus]
    return "\n".join(
        [
            "Subject: TS research workspace update",
            "",
            _executive_sentence(claims, context.get("accepted_artifacts", []), focus),
            "",
            f"Workspace: {context.get('workspace_root')}",
            f"Revision: {context.get('workspace_revision')}",
            "Focus claims:",
            *(f"- {row.get('claim_id')}: {row.get('status')} - {row.get('statement')}" for row in focus_rows),
            "",
            "Main report: final_report.md",
            "",
        ]
    )


def _executive_sentence(claims: list[dict[str, Any]], accepted: list[dict[str, Any]], focus: set[str]) -> str:
    focus_rows = [row for row in claims if row.get("claim_id") in focus]
    accepted_targets = {row.get("target_ref") for row in accepted}
    if focus_rows and all(row.get("claim_id") in accepted_targets for row in focus_rows):
        return "All focus claims have policy-bound accepted artifacts."
    if focus_rows:
        states = ", ".join(f"{row.get('claim_id')}={row.get('status')}" for row in focus_rows)
        return f"Focus claim status: {states}. Acceptance requires the configured deterministic gate policy."
    return "No focus claim is selected. The report records facts without choosing a research path."


def _package_manifest(package_dir: Path, revision: str) -> dict[str, Any]:
    files = []
    for path in sorted(package_dir.rglob("*")):
        if not path.is_file() or path.is_symlink() or path.name == "package_manifest.json":
            continue
        files.append({
            "ref": path.relative_to(package_dir).as_posix(),
            "sha256": _sha256_file(path),
            "size_bytes": path.stat().st_size,
        })
    return {"schema_version": "ts-report-package/1", "workspace_revision": revision, "files": files}


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _escape(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
