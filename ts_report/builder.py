"""Build immutable Markdown packages from the v4 report projection."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from ts_workspace.refs import act_sort_key

from .context import collect_report_context


def build_final_report(root: str | Path) -> str:
    return render_final_report(collect_report_context(root))


def build_report_package(root: str | Path, output_dir: str | Path | None = None) -> dict[str, str]:
    root_path = Path(root).expanduser().resolve()
    package_dir = Path(output_dir).expanduser().resolve() if output_dir is not None else root_path / "reports" / "final-report"
    if package_dir.parent != (root_path / "reports").resolve():
        raise ValueError("report package must be a direct child of workspace reports/")
    context = collect_report_context(root_path)
    if package_dir.exists():
        raise ValueError(f"report package already exists: {package_dir}")
    package_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{package_dir.name}.tmp-", dir=package_dir.parent))
    try:
        (staging / "assets").mkdir()
        _write_json(staging / "report_context.json", context)
        _write_json(staging / "claim_graph.json", {
            "claims": context["claims"],
            "relations": context["claim_relations"],
        })
        _write_json(staging / "research_acts.json", {"acts": context["research_acts"]})
        _write_json(staging / "observation_index.json", {"observations": context["observations"]})
        _write_json(staging / "validation.json", {
            "specs": context["validation_specs"],
            "results": context["validation_results"],
        })
        _write_json(staging / "findings.json", {"findings": context["findings"]})
        _write_json(staging / "acceptances.json", {
            "acceptances": context["acceptances"],
            "current_acceptance_refs": context["acceptance_summary"]["current_refs"],
        })
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
    focus_claims = set(context["focus"]["claim_refs"])
    focus_acts = set(context["focus"]["act_refs"])
    accepted_claims = {item["claim_ref"] for item in context["current_acceptances"]}
    lines = [
        "# Transition-State Research Report",
        "",
        "## Executive Status",
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| Workspace | `{context['workspace_id']}` |",
        f"| Revision | `{context['workspace_revision']}` |",
        f"| Report | `{context['report_id']}` |",
        f"| Focus Claims | `{', '.join(sorted(focus_claims)) or 'none'}` |",
        f"| Focus ResearchActs | `{', '.join(sorted(focus_acts, key=act_sort_key)) or 'none'}` |",
        f"| Claims / Acts / Observations / Findings | {len(context['claims'])} / {len(context['research_acts'])} / {len(context['observations'])} / {len(context['findings'])} |",
        "",
        _executive_sentence(context["claims"], focus_claims, accepted_claims),
        "",
        "## Claim Graph",
        "",
        "| Claim | Type | Status | Statement |",
        "| --- | --- | --- | --- |",
    ]
    for claim in context["claims"]:
        marker = " (focus)" if claim["claim_id"] in focus_claims else ""
        lines.append(
            f"| `{claim['claim_id']}`{marker} | `{claim['claim_type']}` | `{claim['status']}` | {_escape(claim['statement'])} |"
        )
    lines.extend(["", "### Relations", "", "| Relation | Source | Type | Target | Rationale |", "| --- | --- | --- | --- | --- |"])
    for relation in context["claim_relations"]:
        lines.append(
            f"| `{relation['relation_id']}` | `{relation['source_claim_ref']}` | `{relation['relation_type']}` | "
            f"`{relation['target_claim_ref']}` | {_escape(relation['rationale'])} |"
        )
    if not context["claim_relations"]:
        lines.append("| _none_ |  |  |  |  |")

    lines.extend(["", "## ResearchAct DAG", "", "| ResearchAct | Status | Dependencies | Claims | Objective | Outcome |", "| --- | --- | --- | --- | --- | --- |"])
    for act in context["research_acts"]:
        marker = " (focus)" if act["act_id"] in focus_acts else ""
        outcome = act["result"]["outcome"] if isinstance(act.get("result"), dict) else "pending"
        lines.append(
            f"| `{act['act_id']}`{marker} | `{act['status']}` | `{', '.join(act['dependency_refs']) or 'none'}` | "
            f"`{', '.join(act['claim_refs']) or 'none'}` | {_escape(act['objective'])} | `{outcome}` |"
        )

    lines.extend(["", "### ResearchAct Review", ""])
    for act in context["research_acts"]:
        hypothesis = act.get("hypothesis") if isinstance(act.get("hypothesis"), dict) else None
        result = act.get("result") if isinstance(act.get("result"), dict) else None
        lines.extend([
            f"#### `{act['act_id']}` - {_escape(act['objective'])}",
            "",
            f"- Status: `{act['status']}`; dependencies: `{', '.join(act['dependency_refs']) or 'none'}`; Claims: `{', '.join(act['claim_refs']) or 'none'}`.",
            f"- Hypothesis: {_escape(hypothesis['statement']) if hypothesis else '_not recorded_'}",
            f"- Assumptions: {_markdown_items(hypothesis.get('assumptions', [])) if hypothesis else '_none recorded_'}",
            f"- Predictions: {_markdown_items(hypothesis.get('predictions', [])) if hypothesis else '_none recorded_'}",
            f"- Falsifiers: {_markdown_items(hypothesis.get('falsifiers', [])) if hypothesis else '_none recorded_'}",
            f"- Outcome: {_escape(result['summary']) if result else '_pending_'}",
            f"- Open questions: {_markdown_items(result.get('open_questions', [])) if result else '_not yet recorded_'}",
            f"- Linked records: {len(act['operation_refs'])} operations, {len(act['observation_refs'])} Observations, "
            f"{len(act['finding_refs'])} Findings, {len(act['validation_spec_refs'])} GateSpecs, "
            f"{len(act['validation_result_refs'])} ValidationResults.",
            "",
        ])

    lines.extend(["", "## Semantic Observations", "", "| Observation | Concept | Subject | Value | Unit | ResearchAct | Artifacts |", "| --- | --- | --- | --- | --- | --- | --- |"])
    for observation in context["observations"]:
        value = json.dumps(observation["value"], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        lines.append(
            f"| `{observation['observation_id']}` | `{observation['concept_id']}` | `{observation['subject_ref']}` | "
            f"`{_escape(value)}` | `{observation['unit'] or ''}` | `{observation['created_by_act']}` | "
            f"`{', '.join(observation['artifact_refs']) or 'none'}` |"
        )

    lines.extend(["", "## Frozen Validation", "", "| GateSpec | Dimension | Target Claim | Checks | Latest Verdict |", "| --- | --- | --- | --- | --- |"])
    results_by_spec: dict[str, list[dict[str, Any]]] = {}
    for result in context["validation_results"]:
        results_by_spec.setdefault(result["spec_ref"], []).append(result)
    for spec in context["validation_specs"]:
        rows = results_by_spec.get(spec["spec_id"], [])
        latest = rows[-1]["verdict"] if rows else "not evaluated"
        lines.append(
            f"| `{spec['spec_id']}` | `{spec['dimension']}` | `{spec['target_claim_ref']}` | "
            f"{len(spec['checks'])} | `{latest}` |"
        )

    lines.extend(["", "## Findings", "", "| Finding | Severity | Status | Claims | Statement |", "| --- | --- | --- | --- | --- |"])
    for finding in context["findings"]:
        lines.append(
            f"| `{finding['finding_id']}` | `{finding['severity']}` | `{finding['status']}` | "
            f"`{', '.join(finding['claim_refs']) or 'none'}` | {_escape(finding['statement'])} |"
        )
    if not context["findings"]:
        lines.append("| _none_ |  |  |  |  |")

    lines.extend(["", "## Claim Acceptance", ""])
    if context["acceptances"]:
        for acceptance in context["acceptances"]:
            profile = acceptance["profile_ref"]
            state = "current" if acceptance["current"] else "historical"
            stale = "" if acceptance["current"] else f"; stale because `{', '.join(acceptance['stale_reasons'])}`"
            lines.append(
                f"- `{acceptance['acceptance_id']}` is `{state}` for `{acceptance['claim_ref']}` under "
                f"`{profile['profile_id']}@{profile['version']}` with ValidationResults "
                f"`{', '.join(acceptance['validation_result_refs'])}`{stale}."
            )
    else:
        lines.append("- No acceptance assessment has been recorded.")
    if context["acceptances"] and not context["current_acceptances"]:
        lines.append("- No historical acceptance remains current at this workspace revision.")

    lines.extend(["", "## Operational Follow-up", ""])
    if context["unresolved_controls"]:
        lines.append(f"- {len(context['unresolved_controls'])} unresolved compute control record(s) remain.")
    if context["pending_review_dispositions"]:
        lines.append(f"- {len(context['pending_review_dispositions'])} advisory Review response(s) remain pending.")
    open_findings = [item for item in context["findings"] if item["status"] == "open"]
    lines.extend(f"- Open Finding `{item['finding_id']}`: {_escape(item['statement'])}" for item in open_findings)
    if not context["unresolved_controls"] and not context["pending_review_dispositions"] and not open_findings:
        lines.append("- No unresolved operational control, Review response, or open Finding is recorded.")
    lines.extend([
        "",
        "The Root Agent owns research strategy. The Research Kernel owns canonical mutation, provenance, frozen validation, and acceptance.",
    ])
    return "\n".join(lines) + "\n"


def render_email_summary(context: dict[str, Any]) -> str:
    focus = set(context["focus"]["claim_refs"])
    focus_rows = [item for item in context["claims"] if item["claim_id"] in focus]
    accepted = {item["claim_ref"] for item in context["current_acceptances"]}
    return "\n".join([
        "Subject: TS research workspace update",
        "",
        _executive_sentence(context["claims"], focus, accepted),
        "",
        f"Workspace: {context['workspace_id']}",
        f"Revision: {context['workspace_revision']}",
        "Focus Claims:",
        *(f"- {item['claim_id']}: {item['status']} - {item['statement']}" for item in focus_rows),
        "",
        f"Open Findings: {sum(item['status'] == 'open' for item in context['findings'])}",
        "Main report: final_report.md",
        "",
    ])


def _executive_sentence(claims: list[dict[str, Any]], focus: set[str], accepted: set[str]) -> str:
    rows = [item for item in claims if item["claim_id"] in focus]
    if rows and all(item["claim_id"] in accepted for item in rows):
        return "All focus Claims have current, immutable acceptance snapshots under versioned profiles."
    if rows:
        states = ", ".join(f"{item['claim_id']}={item['status']}" for item in rows)
        return f"Focus Claim status: {states}. No current acceptance covers every focus Claim."
    return "No focus Claim is selected; this report records the current graph without selecting a path."


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
    return {"schema_version": "ts-report-package/2", "workspace_revision": revision, "files": files}


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _escape(value: str) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _markdown_items(values: list[Any]) -> str:
    return "; ".join(_escape(str(value)) for value in values) or "_none_"
