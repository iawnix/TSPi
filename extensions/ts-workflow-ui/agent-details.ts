import { existsSync, lstatSync, readFileSync, realpathSync } from "node:fs";
import { isAbsolute, relative, resolve, sep } from "node:path";
import { truncateToWidth, wrapTextWithAnsi } from "@earendil-works/pi-tui";
import type { TsSubagentState } from "../shared/subagent-status.ts";
import {
  formatElapsed,
  roleLabel,
  stateSymbol,
} from "./activity-panel.ts";
import {
  sortedTsSubagentActivities,
  type TsActivityStore,
} from "./activity-store.ts";

const SAFE_RUN_REF = /^(?:nodes\/[A-Za-z0-9][A-Za-z0-9._-]*\/agent-runs|operations\/agent-runs)\/[A-Za-z0-9][A-Za-z0-9._-]*$/;
const MAX_DETAIL_FILE_BYTES = 1024 * 1024;

export interface TsAgentRecord {
  task_id: string;
  role: string;
  operation: string;
  state: TsSubagentState;
  node_ids: string[];
  backend?: string;
  intent_id?: string;
  target_ref?: string;
  wait_reason?: string;
  run_ref?: string;
  started_at?: string;
  updated_at?: string;
  finished_at?: string;
  summary?: string;
  error_code?: string;
  error_message?: string;
  live: boolean;
}

export interface TsAgentRunDocuments {
  task?: Record<string, unknown>;
  actions?: Record<string, unknown>;
  result?: Record<string, unknown>;
  run?: Record<string, unknown>;
}

export function collectTsAgentRecords(
  state: TsActivityStore,
  report: Record<string, unknown> | undefined,
): TsAgentRecord[] {
  const byTask = new Map<string, TsAgentRecord>();
  const durable = report && Array.isArray(report.agent_runs) ? report.agent_runs : [];
  for (const value of durable) {
    if (!isPlainObject(value)) continue;
    const taskId = stringValue(value.task_id);
    if (!taskId) continue;
    byTask.set(taskId, {
      task_id: taskId,
      role: stringValue(value.role) || "review",
      operation: stringValue(value.operation) || "operation",
      state: durableState(value.status, value.result_outcome),
      node_ids: stringArray(value.node_ids),
      run_ref: stringValue(value.run_ref),
      started_at: stringValue(value.started_at),
      updated_at: stringValue(value.finished_at),
      finished_at: stringValue(value.finished_at),
      summary: stringValue(value.summary),
      error_code: stringValue(value.error_code),
      error_message: stringValue(value.error_message),
      live: false,
    });
  }
  for (const activity of sortedTsSubagentActivities(state)) {
    const status = activity.status;
    const previous = byTask.get(status.task_id);
    byTask.set(status.task_id, {
      ...previous,
      task_id: status.task_id,
      role: status.role,
      operation: status.operation,
      state: status.state,
      node_ids: status.node_id ? [status.node_id] : previous?.node_ids || [],
      backend: status.backend,
      intent_id: status.intent_id,
      target_ref: status.target_ref,
      wait_reason: status.wait_reason,
      run_ref: status.run_ref || previous?.run_ref,
      started_at: status.started_at,
      updated_at: status.updated_at,
      live: true,
    });
  }
  return [...byTask.values()].sort(compareRecords);
}

export function agentSelectionLabel(record: TsAgentRecord): string {
  const node = record.node_ids[0];
  const detail = [record.backend, record.operation].filter(Boolean).join(" ");
  const identity = [roleLabel(normalizeRole(record.role)), node, detail].filter(Boolean).join(" · ");
  return `${stateSymbol(record.state)} ${identity} · ${record.state} · ${record.task_id.slice(-8)}`;
}

export function readTsAgentRunDocuments(root: string, runRef?: string): TsAgentRunDocuments {
  if (!runRef) return {};
  if (!isAbsolute(root) || !SAFE_RUN_REF.test(runRef)) throw new Error("invalid TS agent run reference");
  const realRoot = realpathSync(root);
  const runDir = resolve(realRoot, ...runRef.split("/"));
  assertWithin(realRoot, runDir);
  if (!existsSync(runDir)) {
    throw new Error(`TS agent run directory is unavailable: ${runRef}`);
  }
  const runStat = lstatSync(runDir);
  if (!runStat.isDirectory() || runStat.isSymbolicLink() || realpathSync(runDir) !== runDir) {
    throw new Error(`invalid TS agent run directory: ${runRef}`);
  }
  return {
    task: readBoundJson(runDir, "task.json"),
    actions: readBoundJson(runDir, "actions.json"),
    result: readBoundJson(runDir, "result.json"),
    run: readBoundJson(runDir, "run.json"),
  };
}

export function renderTsAgentDetails(
  record: TsAgentRecord,
  documents: TsAgentRunDocuments,
  width: number,
  now = Date.now(),
): string[] {
  const safeWidth = Math.max(16, Math.floor(width));
  const lines = [truncateToWidth(`TS Agent · ${roleLabel(normalizeRole(record.role))}`, safeWidth, "")];
  lines.push("");
  addField(lines, "Status", record.state, safeWidth);
  addField(lines, "Task", record.task_id, safeWidth);
  addField(lines, "Node", record.node_ids.join(", ") || "workspace", safeWidth);
  addField(lines, "Operation", record.operation, safeWidth);
  if (record.backend) addField(lines, "Backend", record.backend, safeWidth);
  if (record.intent_id) addField(lines, "Intent", record.intent_id, safeWidth);
  if (record.wait_reason) addField(lines, "Waiting", record.wait_reason.replaceAll("_", " "), safeWidth);
  if (record.started_at) addField(lines, "Started", record.started_at, safeWidth);
  if (record.started_at) {
    const end = record.finished_at ? Date.parse(record.finished_at) : now;
    const start = Date.parse(record.started_at);
    if (Number.isFinite(start) && Number.isFinite(end)) addField(lines, "Elapsed", formatElapsed(end - start), safeWidth);
  }
  if (record.run_ref) addField(lines, "Run record", record.run_ref, safeWidth);

  const result = documents.result || {};
  const run = documents.run || {};
  const metadata = isPlainObject(run.metadata) ? run.metadata : {};
  const summary = stringValue(result.summary) || record.summary;
  if (summary) addSection(lines, "Summary", summary, safeWidth);

  for (const [label, key] of [
    ["Action outcome", "action_outcome"],
    ["Program status", "program_status"],
    ["Failure stage", "failure_stage"],
  ] as const) {
    const value = findFirstString([metadata, result, documents.actions || {}], key);
    if (value) addField(lines, label, value, safeWidth);
  }

  const actions = actionSummaries(documents.actions);
  if (actions.length > 0) addSection(lines, "Actions", actions.join("\n"), safeWidth);
  const refs = collectRefs([result, documents.actions || {}]);
  if (refs.length > 0) addSection(lines, "Artifacts", refs.join("\n"), safeWidth);

  const error = isPlainObject(run.error) ? run.error : {};
  const errorText = stringValue(error.message) || record.error_message;
  if (errorText) {
    const code = stringValue(error.code) || record.error_code;
    addSection(lines, "Error", code ? `${code}: ${errorText}` : errorText, safeWidth);
  }
  const files = Object.entries(documents).filter(([, value]) => value).map(([name]) => `${name}.json`);
  if (files.length > 0) addField(lines, "Files", files.join(", "), safeWidth);
  lines.push("", truncateToWidth("Esc or Enter to close", safeWidth, ""));
  return lines;
}

function compareRecords(left: TsAgentRecord, right: TsAgentRecord): number {
  const priority = recordPriority(left.state) - recordPriority(right.state);
  if (priority) return priority;
  return Date.parse(right.updated_at || right.started_at || "") - Date.parse(left.updated_at || left.started_at || "");
}

function recordPriority(state: TsSubagentState): number {
  if (["partial", "failed", "cancelled", "unknown"].includes(state)) return 0;
  if (["running", "waiting", "validating"].includes(state)) return 1;
  if (["queued", "starting"].includes(state)) return 2;
  return 3;
}

function durableState(status: unknown, outcome: unknown): TsSubagentState {
  if (status === "failed") return "failed";
  if (status === "pending") return "unknown";
  if (status === "completed" && outcome === "success") return "completed";
  if (status === "completed" && outcome === "partial") return "partial";
  if (status === "completed" && ["failure", "not_run"].includes(String(outcome))) return "failed";
  return "unknown";
}

function readBoundJson(runDir: string, name: string): Record<string, unknown> | undefined {
  const path = resolve(runDir, name);
  assertWithin(runDir, path);
  if (!existsSync(path)) return undefined;
  const stat = lstatSync(path);
  if (!stat.isFile() || stat.isSymbolicLink() || stat.size > MAX_DETAIL_FILE_BYTES) {
    throw new Error(`invalid TS agent detail file: ${name}`);
  }
  const value: unknown = JSON.parse(readFileSync(path, "utf8"));
  if (!isPlainObject(value)) throw new Error(`invalid TS agent detail JSON: ${name}`);
  return value;
}

function addField(lines: string[], label: string, value: string, width: number): void {
  const prefix = `${label.padEnd(14, " ")} `;
  const wrapped = wrapTextWithAnsi(value, Math.max(1, width - prefix.length));
  lines.push(`${prefix}${wrapped[0] || ""}`);
  for (const line of wrapped.slice(1)) lines.push(`${" ".repeat(prefix.length)}${line}`);
}

function addSection(lines: string[], label: string, value: string, width: number): void {
  lines.push("", label);
  for (const sourceLine of value.split("\n")) {
    for (const line of wrapTextWithAnsi(sourceLine, Math.max(1, width - 2))) lines.push(`  ${line}`);
  }
}

function actionSummaries(document: Record<string, unknown> | undefined): string[] {
  if (!document || !Array.isArray(document.actions)) return [];
  return document.actions.filter(isPlainObject).map((action) => {
    const result = isPlainObject(action.result) ? action.result : {};
    const status = findFirstString([result], "action_status")
      || findFirstString([result], "state")
      || findFirstString([result], "program_status")
      || "recorded";
    return `${stringValue(action.tool) || "tool"} · ${status}`;
  });
}

function collectRefs(values: unknown[]): string[] {
  const refs = new Set<string>();
  const visit = (value: unknown, key = "") => {
    if (typeof value === "string" && (key.endsWith("_ref") || key === "artifact_refs")) refs.add(value);
    else if (Array.isArray(value)) for (const item of value) visit(item, key);
    else if (isPlainObject(value)) for (const [childKey, child] of Object.entries(value)) visit(child, childKey);
  };
  for (const value of values) visit(value);
  return [...refs].sort().slice(0, 32);
}

function findFirstString(values: Record<string, unknown>[], key: string): string | undefined {
  for (const value of values) {
    const found = findString(value, key);
    if (found) return found;
  }
  return undefined;
}

function findString(value: unknown, key: string): string | undefined {
  if (!isPlainObject(value)) return undefined;
  if (stringValue(value[key])) return stringValue(value[key]);
  for (const child of Object.values(value)) {
    if (isPlainObject(child)) {
      const found = findString(child, key);
      if (found) return found;
    }
  }
  return undefined;
}

function normalizeRole(value: string): "review" | "backend" | "render" | "report" {
  return ["review", "backend", "render", "report"].includes(value)
    ? value as "review" | "backend" | "render" | "report"
    : "review";
}

function assertWithin(root: string, path: string): void {
  const rel = relative(root, path);
  if (!rel || rel === ".." || rel.startsWith(`..${sep}`) || isAbsolute(rel)) {
    throw new Error("TS agent detail path escapes its root");
  }
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string" && Boolean(item)) : [];
}

function stringValue(value: unknown): string | undefined {
  return typeof value === "string" && value ? value : undefined;
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
