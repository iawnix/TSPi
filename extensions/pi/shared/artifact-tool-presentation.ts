import type {
  AgentToolResult,
  Theme,
  ToolRenderResultOptions,
} from "@earendil-works/pi-coding-agent";
import { Text } from "@earendil-works/pi-tui";
import { tspiIcon } from "./icons.ts";
import {
  collectArtifactDisplayLabels,
  createDisplayRefFormatter,
} from "./ref-presentation.ts";

export type ArtifactToolKind = "seed" | "compare" | "analyze" | "import" | "render" | "report";

const TOOL_LABELS: Record<ArtifactToolKind, string> = {
  seed: "Structure seed",
  compare: "Structure compare",
  analyze: "Scientific analysis",
  import: "Artifact import",
  render: "Render",
  report: "Report",
};

export function renderTsArtifactCall(
  kind: ArtifactToolKind,
  args: Record<string, unknown>,
  theme: Theme,
): Text {
  const formatter = createDisplayRefFormatter();
  const parts = [
    `${tspiIcon("running")} ${TOOL_LABELS[kind]}`,
    callOperation(kind, args, formatter),
    formatter.format(stringValue(args.nodeId), "node_ref"),
    callSubject(kind, args, formatter),
  ];
  return new Text(theme.fg("accent", compact(parts)), 1, 0);
}

export function renderTsArtifactResult(
  kind: ArtifactToolKind,
  result: AgentToolResult<unknown>,
  options: ToolRenderResultOptions,
  theme: Theme,
  isError: boolean,
): Text {
  if (options.isPartial) return new Text("", 0, 0);
  const parsed = parseContent(result);
  const details = isObject(result.details) ? result.details : {};
  const canonical = firstObject(
    details.result,
    details,
    parsed,
  );
  const formatter = createDisplayRefFormatter({
    artifactLabels: collectArtifactDisplayLabels([details, canonical, parsed]),
  });
  const status = isError ? "failed" : resultStatus(canonical);
  const color = status === "failed" ? "error" : status === "partial" ? "warning" : "success";
  const parts = [
    `${tspiIcon(status === "failed" ? "failed" : status === "partial" ? "partial" : "completed")} ${TOOL_LABELS[kind]}`,
    status,
    formatter.format(stringValue(canonical.node_id), "node_ref"),
    resultSubject(kind, canonical, formatter),
    resultArtifacts(canonical, formatter),
  ];
  const message = isError
    ? formatter.formatText(stringValue(canonical.message) || stringValue(canonical.error_message) || "")
    : "";
  if (message) parts.push(firstLine(message));
  const summary = compact(parts);
  const raw = options.expanded ? formatter.formatText(textContent(result) || "") : undefined;
  return new Text(
    raw ? `${theme.fg(color, summary)}\n${theme.fg("dim", raw)}` : theme.fg(color, summary),
    1,
    0,
  );
}

function callOperation(
  kind: ArtifactToolKind,
  args: Record<string, unknown>,
  formatter: ReturnType<typeof createDisplayRefFormatter>,
): string | undefined {
  if (kind === "render") return formatter.formatText(stringValue(args.operation) || "render");
  if (kind === "analyze") return formatter.formatText(stringValue(args.capability) || "run");
  if (kind === "import") return formatter.formatText(stringValue(args.operation) || "import");
  if (kind === "report") return formatter.formatText(stringValue(args.operation) || "build");
  return formatter.formatText(stringValue(args.operation) || "");
}

function callSubject(
  kind: ArtifactToolKind,
  args: Record<string, unknown>,
  formatter: ReturnType<typeof createDisplayRefFormatter>,
): string | undefined {
  if (kind === "seed") return formatter.formatText(stringValue(args.optimization) || "");
  if (kind === "compare") {
    return compact([
      formatter.format(stringValue(args.referenceArtifactId), "artifact_ref"),
      formatter.format(stringValue(args.targetArtifactId), "artifact_ref"),
    ], " ↔ ");
  }
  if (kind === "import") return formatter.formatText(stringValue(args.inputName) || "");
  if (kind === "render") return formatter.formatText(stringValue(args.outputName) || "");
  if (kind === "report") return formatter.formatText(stringValue(args.packageName) || "");
  return undefined;
}

function resultSubject(
  kind: ArtifactToolKind,
  result: Record<string, unknown>,
  formatter: ReturnType<typeof createDisplayRefFormatter>,
): string | undefined {
  if (kind === "render") return formatter.formatText(stringValue(result.operation) || "");
  if (kind === "analyze") return formatter.formatText(stringValue(result.capability) || "");
  if (kind === "import" || kind === "report") {
    return formatter.formatText(stringValue(result.input_name) || stringValue(result.package_name) || "");
  }
  return undefined;
}

function resultArtifacts(
  result: Record<string, unknown>,
  formatter: ReturnType<typeof createDisplayRefFormatter>,
): string | undefined {
  const refs = new Set<string>();
  const visit = (value: unknown, key = "") => {
    if (typeof value === "string" && isArtifactKey(key) && /^art_[0-9a-f]{12,}$/i.test(value)) {
      refs.add(value);
      return;
    }
    if (Array.isArray(value)) {
      for (const item of value) visit(item, key);
    } else if (isObject(value)) {
      for (const [childKey, child] of Object.entries(value)) visit(child, childKey);
    }
  };
  visit(result);
  const values = [...refs].slice(0, 3).map((value) => formatter.format(value, "artifact_ref"));
  return values.length ? values.join(", ") : undefined;
}

function isArtifactKey(key: string): boolean {
  return key === "artifact_id"
    || key === "artifactId"
    || key.endsWith("_artifact_id")
    || key.endsWith("_artifact_ids")
    || key === "artifact_refs"
    || key === "asset_refs";
}

function resultStatus(result: Record<string, unknown>): string {
  const value = stringValue(result.outcome)
    || stringValue(result.status)
    || stringValue(result.state)
    || (result.ok === true ? "completed" : undefined)
    || "completed";
  if (["success", "completed", "done", "ok"].includes(value)) return "done";
  if (["failure", "failed", "error", "not_run"].includes(value)) return "failed";
  if (["partial", "warning"].includes(value)) return "partial";
  return value;
}

function parseContent(result: AgentToolResult<unknown>): Record<string, unknown> | undefined {
  const text = textContent(result);
  if (!text) return undefined;
  try {
    const value: unknown = JSON.parse(text);
    return isObject(value) ? value : undefined;
  } catch {
    return undefined;
  }
}

function textContent(result: AgentToolResult<unknown>): string | undefined {
  const values = result.content
    .filter((item): item is Extract<typeof item, { type: "text" }> => item.type === "text")
    .map((item) => item.text)
    .filter(Boolean);
  return values.length ? values.join("\n") : undefined;
}

function firstObject(...values: unknown[]): Record<string, unknown> {
  return values.find(isObject) || {};
}

function firstLine(value: string): string {
  return value.split(/\r?\n/, 1)[0]?.trim() || value;
}

function compact(values: Array<string | undefined>, separator = " · "): string {
  return values.filter((value): value is string => Boolean(value)).join(separator);
}

function stringValue(value: unknown): string | undefined {
  return typeof value === "string" && value ? value : undefined;
}

function isObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
