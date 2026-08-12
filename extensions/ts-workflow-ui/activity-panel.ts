import { truncateToWidth, visibleWidth } from "@earendil-works/pi-tui";
import { tspiIcon, type TspiIconName, type TspiIconStyle } from "../shared/icons.ts";
import type { TsSubagentRole, TsSubagentState, TsSubagentStatus } from "../shared/subagent-status.ts";
import {
  activityState,
  sortedTsActivities,
  summarizeTsActivities,
  type TsActivity,
  type TsActivityStore,
  type TsActivitySummary,
  type TsSubagentActivity,
} from "./activity-store.ts";

export type TsActivityTone = "muted" | "accent" | "warning" | "success" | "error";

export interface TsActivityPanelLine {
  text: string;
  tone: TsActivityTone;
}

export function renderTsActivityPanel(
  store: TsActivityStore,
  width: number,
  now = Date.now(),
  maxActivities = 4,
  iconStyle?: TspiIconStyle,
): TsActivityPanelLine[] {
  const safeWidth = Math.max(1, Math.floor(width));
  const activities = sortedTsActivities(store);
  if (activities.length === 0) return [];
  const visible = activities.slice(0, Math.max(1, maxActivities));
  const summary = summarizeTsActivities(store);
  const lines: TsActivityPanelLine[] = [{
    text: formatPanelHeader(summary, safeWidth, iconStyle),
    tone: summary.attention > 0 ? "warning" : "accent",
  }];
  for (const activity of visible) lines.push(...renderActivity(activity, safeWidth, now, iconStyle));
  if (activities.length > visible.length) {
    lines.push({
      text: truncateToWidth(`  +${activities.length - visible.length} more activities`, safeWidth, ""),
      tone: "muted",
    });
  }
  return lines;
}

export function roleLabel(role: TsSubagentRole): string {
  return {
    review: "Review",
    backend: "Compute",
    render: "Render",
    report: "Report",
  }[role];
}

export function stateSymbol(state: TsSubagentState, style?: TspiIconStyle): string {
  return tspiIcon(stateIconName(state), style);
}

export function stateTone(state: TsSubagentState): TsActivityTone {
  if (state === "failed" || state === "cancelled") return "error";
  if (state === "partial" || state === "unknown" || state === "waiting") return "warning";
  if (state === "completed") return "success";
  if (state === "queued" || state === "starting") return "muted";
  return "accent";
}

export function detailLabel(status: TsSubagentStatus): string {
  if (status.role === "backend") return compact([backendLabel(status.backend), status.operation, status.intent_id]);
  return compact([status.operation, status.target_ref]);
}

export function formatElapsed(milliseconds: number): string {
  const totalSeconds = Math.max(0, Math.floor(milliseconds / 1000));
  const seconds = totalSeconds % 60;
  const totalMinutes = Math.floor(totalSeconds / 60);
  if (totalMinutes < 60) return `${pad(totalMinutes)}:${pad(seconds)}`;
  return `${pad(Math.floor(totalMinutes / 60))}:${pad(totalMinutes % 60)}:${pad(seconds)}`;
}

function renderActivity(
  activity: TsActivity,
  width: number,
  now: number,
  iconStyle?: TspiIconStyle,
): TsActivityPanelLine[] {
  const state = activityState(activity);
  const tone = stateTone(state);
  const right = rightLabel(activity, now, iconStyle, width >= 72);
  const role = activity.kind === "subagent" ? roleLabel(activity.status.role) : "Remote";
  const node = activity.kind === "subagent" ? activity.status.node_id : undefined;
  const detail = activity.kind === "subagent"
    ? detailLabel(activity.status) || activity.status.operation
    : compact([activity.mode, activity.detail]);
  const statusIcon = stateSymbol(state, iconStyle);
  if (width < 58) {
    const first = compact([`${statusIcon} ${role}`, node]);
    return [
      { text: fitSides(first, right, width), tone },
      { text: truncateToWidth(`  ${detail}`, width, "..."), tone: "muted" },
    ];
  }
  const roleIcon = tspiIcon(roleIconName(activity), iconStyle);
  const identity = `${statusIcon} ${roleIcon} ${role}`;
  return [{ text: fitSides(compact([identity, node, detail]), right, width), tone }];
}

function formatPanelHeader(
  summary: TsActivitySummary,
  width: number,
  iconStyle?: TspiIconStyle,
): string {
  const counts = [
    summary.active > 0 ? `${summary.active} active` : undefined,
    summary.attention > 0 ? `${summary.attention} attention` : undefined,
    summary.done > 0 ? `${summary.done} done` : undefined,
  ].filter((value): value is string => Boolean(value));
  const left = `${tspiIcon("activity", iconStyle)} TS Activity`;
  const right = counts.join(" · ");
  if (visibleWidth(left) >= width) return truncateToWidth(left, width, "");
  if (visibleWidth(left) + visibleWidth(right) + 1 <= width) return fitSides(left, right, width);
  return `${left} ${truncateToWidth(right, width - visibleWidth(left) - 1, "...")}`;
}

function rightLabel(activity: TsActivity, now: number, style: TspiIconStyle | undefined, showIcon: boolean): string {
  const state = activityState(activity);
  if (state === "completed") return "done";
  if (state === "partial") return "partial";
  if (state === "failed") return activity.kind === "subagent" ? activity.status.failure_kind || "failed" : "failed";
  if (state === "cancelled") return "cancelled";
  if (state === "unknown") return "unknown";
  if (state === "waiting" && activity.kind === "subagent") return waitReasonLabel(activity.status.wait_reason);
  const elapsed = formatElapsed(Math.max(0, now - activity.startedAt));
  return showIcon ? `${tspiIcon("elapsed", style)} ${elapsed}` : elapsed;
}

function roleIconName(activity: TsActivity): TspiIconName {
  if (activity.kind === "remote") return "remote";
  return {
    backend: "roleCompute",
    review: "roleReview",
    render: "roleRender",
    report: "roleReport",
  }[activity.status.role] as TspiIconName;
}

function stateIconName(state: TsSubagentState): TspiIconName {
  if (state === "starting") return "queued";
  return state;
}

function waitReasonLabel(value?: string): string {
  return {
    model_response: "waiting · model",
    typed_tool: "waiting · tool",
    remote_reconciliation: "waiting · remote",
    parent_coordination: "waiting · parent",
  }[value || ""] || "waiting";
}

function backendLabel(value?: string): string | undefined {
  if (!value) return undefined;
  return {
    gaussian: "Gaussian",
    ase_neb: "ASE NEB",
    xtb: "xTB",
    crest: "CREST",
    qbics_dmecp: "QBICS DMECp",
    rdkit: "RDKit",
  }[value] || value;
}

function fitSides(left: string, right: string, width: number): string {
  const safeWidth = Math.max(1, width);
  const rightWidth = visibleWidth(right);
  if (!right) return truncateToWidth(left, safeWidth, "...");
  const leftWidth = visibleWidth(left);
  if (leftWidth + rightWidth + 1 <= safeWidth) {
    return `${left}${" ".repeat(safeWidth - leftWidth - rightWidth)}${right}`;
  }
  if (rightWidth >= safeWidth) return truncateToWidth(left, safeWidth, "...");
  return `${truncateToWidth(left, Math.max(1, safeWidth - rightWidth - 1), "...")} ${right}`;
}

function compact(values: Array<string | undefined>): string {
  return values.filter((value): value is string => Boolean(value)).join(" · ");
}

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

export type { TsActivityStore, TsSubagentActivity };
