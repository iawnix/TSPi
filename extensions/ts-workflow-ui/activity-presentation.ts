import { tspiIcon, type TspiIconName, type TspiIconStyle } from "../shared/icons.ts";
import type { TsSubagentState } from "../shared/subagent-status.ts";

const TERMINAL_STATES = new Set<TsSubagentState>([
  "completed",
  "partial",
  "failed",
  "cancelled",
  "unknown",
]);

export interface TsSubagentPresentationSource {
  task_id: string;
  task_id_pending?: boolean;
  role: "review" | "compute";
  operation: string;
  backend?: string;
  state: TsSubagentState;
  node_refs?: readonly string[];
  claim_refs?: readonly string[];
  target_ref?: string;
  wait_reason?: string;
  failure_kind?: string;
  started_at?: string;
  updated_at?: string;
  finished_at?: string;
}

export function subagentRunLabel(value: Pick<TsSubagentPresentationSource, "task_id" | "task_id_pending">): string {
  return value.task_id_pending ? "ID pending" : value.task_id;
}

export function subagentRoleLabel(role: TsSubagentPresentationSource["role"]): string {
  return role === "compute" ? "Compute" : "Review";
}

export function subagentOwnerLabel(value: TsSubagentPresentationSource): string {
  if (value.role === "review") {
    const targetClaim = value.target_ref?.startsWith("claim_") ? value.target_ref : undefined;
    return targetClaim || value.claim_refs?.[0] || value.node_refs?.[0] || "workspace";
  }
  return value.node_refs?.[0] || "workspace";
}

export function subagentActionLabel(
  value: Pick<TsSubagentPresentationSource, "role" | "operation" | "backend">,
): string {
  if (value.operation === "claim_review") return "claim review";
  if (value.role === "review") return humanizeToken(value.operation || "review");
  const known = {
    launch: { backend: "launch", generic: "launch calculation" },
    inspect: { backend: "inspect", generic: "inspect calculation" },
    finalize: { backend: "collect and parse", generic: "collect and parse" },
    cancel: { backend: "cancel", generic: "cancel calculation" },
  }[value.operation];
  const backend = backendLabel(value.backend);
  if (known) return backend ? `${backend} ${known.backend}` : known.generic;
  const operation = humanizeToken(value.operation || `${value.role} operation`);
  return backend ? `${backend} ${operation}` : operation;
}

export function subagentStateLabel(
  value: Pick<TsSubagentPresentationSource, "state" | "wait_reason" | "failure_kind">,
): string {
  if (value.state === "waiting") return waitReasonLabel(value.wait_reason);
  if (value.state === "failed" && value.failure_kind === "timeout") return "timeout";
  return {
    queued: "queued",
    starting: "starting",
    running: "running",
    validating: "validating",
    completed: "done",
    partial: "partial",
    failed: "failed",
    cancelled: "cancelled",
    unknown: "unknown",
  }[value.state];
}

export function subagentElapsedLabel(
  value: Pick<TsSubagentPresentationSource, "state" | "started_at" | "updated_at" | "finished_at">,
  now = Date.now(),
): string | undefined {
  if (!value.started_at) return undefined;
  const started = Date.parse(value.started_at);
  if (!Number.isFinite(started)) return undefined;
  const terminalTimestamp = value.finished_at || (TERMINAL_STATES.has(value.state) ? value.updated_at : undefined);
  const ended = terminalTimestamp ? Date.parse(terminalTimestamp) : now;
  if (!Number.isFinite(ended)) return undefined;
  return formatElapsed(Math.max(0, ended - started));
}

export function formatElapsed(milliseconds: number): string {
  const totalSeconds = Math.max(0, Math.floor(milliseconds / 1000));
  const seconds = totalSeconds % 60;
  const totalMinutes = Math.floor(totalSeconds / 60);
  if (totalMinutes < 60) return `${pad(totalMinutes)}:${pad(seconds)}`;
  return `${pad(Math.floor(totalMinutes / 60))}:${pad(totalMinutes % 60)}:${pad(seconds)}`;
}

export function formatLocalDateTime(value: string): string | undefined {
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return undefined;
  const date = new Date(timestamp);
  return [
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`,
    `${pad(date.getHours())}:${pad(date.getMinutes())}`,
  ].join(" ");
}

export function stateSymbol(state: TsSubagentState, style?: TspiIconStyle): string {
  return tspiIcon(stateIconName(state), style);
}

export function humanizeToken(value: string): string {
  return value.replaceAll("_", " ").replaceAll("-", " ").replace(/\s+/g, " ").trim();
}

function stateIconName(state: TsSubagentState): TspiIconName {
  return state === "starting" ? "queued" : state;
}

function waitReasonLabel(value?: string): string {
  return {
    model_response: "waiting · model",
    typed_tool: "waiting · result",
    parent_coordination: "waiting · root",
  }[value || ""] || "waiting";
}

function backendLabel(value?: string): string | undefined {
  if (!value) return undefined;
  return {
    gaussian: "Gaussian",
    xtb: "xTB",
    crest: "CREST",
    ase: "ASE",
  }[value.toLowerCase()] || humanizeToken(value);
}

function pad(value: number): string {
  return String(value).padStart(2, "0");
}
