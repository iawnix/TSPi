import { existsSync, lstatSync, readFileSync, realpathSync } from "node:fs";
import { isAbsolute, relative, resolve, sep } from "node:path";
import { truncateToWidth, wrapTextWithAnsi } from "@earendil-works/pi-tui";
import type { TsSubagentState } from "../shared/subagent-status.ts";
import {
  formatLocalDateTime,
  stateSymbol,
  subagentActionLabel,
  subagentElapsedLabel,
  subagentOwnerLabel,
  subagentRoleLabel,
  subagentRunLabel as presentationRunLabel,
  subagentStateLabel,
} from "./activity-presentation.ts";
import {
  sortedTsSubagentActivities,
  type TsActivityStore,
} from "./activity-store.ts";

const SAFE_RUN_REF = /^(?:nodes\/node_[1-9][0-9]*\/attempts\/calc_[1-9][0-9]*|reviews\/claim_[1-9][0-9]*)\/runs\/sub_[1-9][0-9]*$/;
const CANONICAL_TASK_ID = /^sub_[1-9][0-9]*$/;
const MAX_DETAIL_FILE_BYTES = 1024 * 1024;

export interface TsSubagentRecord {
  task_id: string;
  role: "review" | "compute";
  authority: "advisory" | "operational";
  operation: string;
  capability?: string;
  capability_version?: string;
  state: TsSubagentState;
  node_refs: string[];
  claim_refs: string[];
  target_ref?: string;
  wait_reason?: string;
  failure_kind?: string;
  run_ref?: string;
  started_at?: string;
  updated_at?: string;
  finished_at?: string;
  summary?: string;
  error_code?: string;
  error_message?: string;
  task_id_pending?: boolean;
  live: boolean;
}

export interface TsSubagentRunDocuments {
  task?: Record<string, unknown>;
  researchMap?: Record<string, unknown>;
  reviewContext?: Record<string, unknown>;
  actions?: Record<string, unknown>;
  result?: Record<string, unknown>;
  run?: Record<string, unknown>;
}

export function collectTsSubagentRecords(
  state: TsActivityStore,
  report: Record<string, unknown> | undefined,
): TsSubagentRecord[] {
  const byTask = new Map<string, TsSubagentRecord>();
  const durable = report && Array.isArray(report.agent_runs) ? report.agent_runs : [];
  for (const value of durable) {
    if (!isPlainObject(value)) continue;
    const taskId = stringValue(value.task_id);
    if (!taskId) continue;
    byTask.set(taskId, {
      task_id: taskId,
      role: subagentRole(value.role),
      authority: value.role === "compute" ? "operational" : "advisory",
      operation: stringValue(value.operation) || "operation",
      capability: stringValue(value.capability),
      capability_version: stringValue(value.capability_version),
      state: durableState(value.status, value.result_outcome),
      node_refs: stringArray(value.node_refs),
      claim_refs: stringArray(value.claim_refs),
      target_ref: stringValue(value.intent_id),
      run_ref: stringValue(value.run_ref),
      started_at: stringValue(value.started_at),
      updated_at: stringValue(value.finished_at),
      finished_at: stringValue(value.finished_at),
      summary: stringValue(value.summary),
      error_code: stringValue(value.error_code),
      error_message: stringValue(value.error_message),
      failure_kind: failureKindFromError(value.error_code),
      task_id_pending: false,
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
      authority: status.role === "compute" ? "operational" : "advisory",
      operation: status.operation,
      capability: activity.capability || previous?.capability,
      capability_version: previous?.capability_version,
      state: status.state,
      node_refs: status.node_refs || previous?.node_refs || [],
      claim_refs: status.claim_refs || previous?.claim_refs || [],
      target_ref: status.target_ref || previous?.target_ref,
      wait_reason: status.wait_reason,
      failure_kind: status.failure_kind || previous?.failure_kind,
      run_ref: status.run_ref || previous?.run_ref,
      started_at: status.started_at,
      updated_at: status.updated_at,
      task_id_pending: status.task_id === status.tool_call_id && !CANONICAL_TASK_ID.test(status.task_id),
      live: true,
    });
  }
  return [...byTask.values()].sort(compareRecords);
}

export function subagentSelectionLabel(record: TsSubagentRecord): string {
  const parts = subagentSelectionParts(record);
  return `${parts.left} · ${parts.right}`;
}

export function subagentSelectionParts(record: TsSubagentRecord, now = Date.now()): { left: string; right: string } {
  const left = [
    `${stateSymbol(record.state)} ${subagentRunLabel(record)}`,
    subagentRoleLabel(record.role),
    subagentOwnerLabel(record),
    subagentActionLabel(record),
  ].join(" · ");
  const right = compact([subagentStateLabel(record), subagentElapsedLabel(record, now)]);
  return { left, right };
}

export function subagentRunLabel(record: TsSubagentRecord): string {
  return presentationRunLabel(record);
}

export function readTsSubagentRunDocuments(root: string, runRef?: string): TsSubagentRunDocuments {
  if (!runRef) return {};
  if (!isAbsolute(root) || !SAFE_RUN_REF.test(runRef)) throw new Error("invalid TS subagent run reference");
  const realRoot = realpathSync(root);
  const runDir = resolve(realRoot, ...runRef.split("/"));
  assertWithin(realRoot, runDir);
  if (!existsSync(runDir)) {
    throw new Error(`TS subagent run directory is unavailable: ${runRef}`);
  }
  const runStat = lstatSync(runDir);
  if (!runStat.isDirectory() || runStat.isSymbolicLink() || realpathSync(runDir) !== runDir) {
    throw new Error(`invalid TS subagent run directory: ${runRef}`);
  }
  return {
    task: readBoundJson(runDir, "task.json"),
    researchMap: readBoundJson(runDir, "research-map.json"),
    reviewContext: readBoundJson(runDir, "review-context.json"),
    actions: readBoundJson(runDir, "actions.json"),
    result: readBoundJson(runDir, "result.json"),
    run: readBoundJson(runDir, "run.json"),
  };
}

export function renderTsSubagentDetails(
  record: TsSubagentRecord,
  documents: TsSubagentRunDocuments,
  width: number,
  now = Date.now(),
): string[] {
  const safeWidth = Math.max(16, Math.floor(width));
  const result = documents.result || {};
  const run = documents.run || {};
  const metadata = isPlainObject(run.metadata) ? run.metadata : {};
  const summary = stringValue(result.summary) || record.summary;
  const title = compact([
    subagentRunLabel(record),
    subagentRoleLabel(record.role),
    subagentStateLabel(record),
  ]);
  const lines = [truncateToWidth(title || "TS Subagent Run", safeWidth, "")];
  if (summary) addSection(lines, "Outcome", summary, safeWidth);

  const error = isPlainObject(run.error) ? run.error : {};
  const errorText = stringValue(error.message) || record.error_message;
  if (errorText) {
    const code = stringValue(error.code) || record.error_code;
    addSection(lines, "Error", code ? `${code}: ${errorText}` : errorText, safeWidth);
  }

  const resultFields: Array<[string, string]> = [];
  for (const [label, key] of [
    ["Action outcome", "action_outcome"],
    ["Program status", "program_status"],
    ["Failure stage", "failure_stage"],
  ] as const) {
    const value = findFirstString([metadata, result, documents.actions || {}], key);
    if (value) resultFields.push([label, value]);
  }
  if (resultFields.length > 0) {
    lines.push("", "Result");
    for (const [label, value] of resultFields) addField(lines, label, value, safeWidth);
  }

  lines.push("", "Scope");
  const owner = subagentOwnerLabel(record);
  addField(lines, "Owner", owner, safeWidth);
  if (record.node_refs.length > 1 || (record.node_refs[0] && record.node_refs[0] !== owner)) {
    addField(lines, "Node scope", record.node_refs.join(", "), safeWidth);
  }
  if (record.claim_refs.length > 1 || (record.claim_refs[0] && record.claim_refs[0] !== owner)) {
    addField(lines, "Claim scope", record.claim_refs.join(", "), safeWidth);
  }
  addField(lines, "Action", subagentActionLabel(record), safeWidth);
  if (record.role === "compute" && readableCalculationRef(record.target_ref)) {
    addField(lines, "Calculation", record.target_ref || "", safeWidth);
  }
  const started = record.started_at ? formatLocalDateTime(record.started_at) : undefined;
  const finished = record.finished_at ? formatLocalDateTime(record.finished_at) : undefined;
  const elapsed = subagentElapsedLabel(record, now);
  if (started) addField(lines, "Started", started, safeWidth);
  if (finished) addField(lines, "Finished", finished, safeWidth);
  if (elapsed) addField(lines, "Elapsed", elapsed, safeWidth);

  const actions = actionSummaries(documents.actions);
  if (actions.length > 0) addSection(lines, "Actions", actions.join("\n"), safeWidth);
  const refs = collectRefs([result, documents.actions || {}]);
  if (refs.length > 0) addSection(lines, "Artifacts", refs.join("\n"), safeWidth);
  const fileNames: Record<keyof TsSubagentRunDocuments, string> = {
    task: "task.json",
    researchMap: "research-map.json",
    reviewContext: "review-context.json",
    actions: "actions.json",
    result: "result.json",
    run: "run.json",
  };
  const files = Object.entries(documents)
    .filter(([, value]) => value)
    .map(([name]) => fileNames[name as keyof TsSubagentRunDocuments]);
  if (record.run_ref || files.length > 0) {
    lines.push("", "Audit");
    addField(lines, "Authority", record.authority, safeWidth);
    if (record.run_ref) addField(lines, "Journal", record.run_ref, safeWidth);
    if (files.length > 0) addField(lines, "Files", files.join(", "), safeWidth);
  }
  return lines;
}

function compareRecords(left: TsSubagentRecord, right: TsSubagentRecord): number {
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

function failureKindFromError(value: unknown): string | undefined {
  const code = String(value || "").toUpperCase();
  if (code.includes("TIMEOUT")) return "timeout";
  if (code.includes("ABORT")) return "aborted";
  return undefined;
}

function readableCalculationRef(value?: string): boolean {
  return Boolean(value && /^calc_[1-9][0-9]*$/.test(value));
}

function readBoundJson(runDir: string, name: string): Record<string, unknown> | undefined {
  const path = resolve(runDir, name);
  assertWithin(runDir, path);
  if (!existsSync(path)) return undefined;
  const stat = lstatSync(path);
  if (!stat.isFile() || stat.isSymbolicLink() || stat.size > MAX_DETAIL_FILE_BYTES) {
    throw new Error(`invalid TS subagent detail file: ${name}`);
  }
  const value: unknown = JSON.parse(readFileSync(path, "utf8"));
  if (!isPlainObject(value)) throw new Error(`invalid TS subagent detail JSON: ${name}`);
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

function compact(values: Array<string | undefined>): string {
  return values.filter((value): value is string => Boolean(value)).join(" · ");
}

function subagentRole(value: unknown): "review" | "compute" {
  return value === "compute" ? "compute" : "review";
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
