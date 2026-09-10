import { truncateToWidth, visibleWidth } from "@earendil-works/pi-tui";
import { tspiIcon, type TspiIconName, type TspiIconStyle } from "../shared/icons.ts";
import type { TsSubagentState } from "../shared/subagent-status.ts";
import {
  activityState,
  sortedTsActivities,
  summarizeTsActivities,
  type TsActivity,
  type TsActivityStore,
  type TsActivitySummary,
  type TsDeterministicActivity,
  type TsSubagentActivity,
} from "./activity-store.ts";
import {
  formatElapsed,
  humanizeToken,
  stateSymbol,
  subagentActionLabel,
  subagentOwnerLabel,
  subagentStateLabel,
} from "./activity-presentation.ts";

export type TsActivityTone = "muted" | "accent" | "warning" | "success" | "error";
export interface TsActivityPanelLine { text: string; tone: TsActivityTone }

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
    lines.push({ text: truncateToWidth(`  +${activities.length - visible.length} more activities`, safeWidth, ""), tone: "muted" });
  }
  return lines;
}

export function stateTone(state: TsSubagentState): TsActivityTone {
  if (state === "failed" || state === "cancelled") return "error";
  if (state === "partial" || state === "unknown" || state === "waiting") return "warning";
  if (state === "completed") return "success";
  if (state === "queued" || state === "starting") return "muted";
  return "accent";
}

function renderActivity(activity: TsActivity, width: number, now: number, iconStyle?: TspiIconStyle): TsActivityPanelLine[] {
  const state = activityState(activity);
  const tone = stateTone(state);
  const right = rightLabel(activity, now, iconStyle, width >= 72);
  const role = activityLabel(activity);
  const owner = activityOwnerLabel(activity);
  const action = activityActionLabel(activity);
  const statusIcon = stateSymbol(state, iconStyle);
  if (width < 58) {
    return [
      { text: fitSides(compact([`${statusIcon} ${role}`, owner]), right, width), tone },
      { text: truncateToWidth(`  ${action}`, width, "..."), tone: "muted" },
    ];
  }
  const identity = `${statusIcon} ${tspiIcon(roleIconName(activity), iconStyle)} ${role}`;
  return [{ text: fitSides(compact([identity, owner, action]), right, width), tone }];
}

function activityLabel(activity: TsActivity): string {
  if (activity.kind === "subagent") return activity.status.role === "compute" ? "Compute" : "Review";
  if (activity.kind === "remote") return "Remote";
  return {
    structure: "Structure",
    analysis: "Analysis",
    artifact: "Artifact",
    render: "Render",
    report: "Report",
    notify: "Notify",
    remote: "Remote",
  }[activity.activityKind];
}

function activityOwnerLabel(activity: TsActivity): string | undefined {
  if (activity.kind === "subagent") return subagentOwnerLabel(activity.status);
  if (activity.kind === "deterministic") return activity.nodeRefs[0] || "workspace";
  return undefined;
}

function activityActionLabel(activity: TsActivity): string {
  if (activity.kind === "subagent") return subagentActionLabel({ ...activity.status, capability: activity.capability });
  if (activity.kind === "remote") return compact([activity.mode, activity.detail]);
  return compact([humanizeToken(activity.operation), activity.detail]);
}

function formatPanelHeader(summary: TsActivitySummary, width: number, iconStyle?: TspiIconStyle): string {
  const counts = [
    summary.active > 0 ? `${summary.active} active` : undefined,
    summary.attention > 0 ? `${summary.attention} attention` : undefined,
    summary.active === 0 && summary.attention === 0 && summary.done > 0 ? `${summary.done} recent` : undefined,
  ].filter((value): value is string => Boolean(value));
  const left = `${tspiIcon("activity", iconStyle)} TS Activity`;
  const right = counts.join(" · ");
  if (visibleWidth(left) >= width) return truncateToWidth(left, width, "");
  if (visibleWidth(left) + visibleWidth(right) + 1 <= width) return fitSides(left, right, width);
  return `${left} ${truncateToWidth(right, width - visibleWidth(left) - 1, "...")}`;
}

function rightLabel(activity: TsActivity, now: number, style: TspiIconStyle | undefined, showIcon: boolean): string {
  const state = activityState(activity);
  if (activity.kind === "subagent" && state !== "running") return subagentStateLabel(activity.status);
  if (state === "completed") return "done";
  if (state === "partial") return "partial";
  if (state === "failed") return "failed";
  if (state === "cancelled") return "cancelled";
  if (state === "unknown") return "unknown";
  const elapsed = formatElapsed(Math.max(0, now - activity.startedAt));
  return showIcon ? `${tspiIcon("elapsed", style)} ${elapsed}` : elapsed;
}

function roleIconName(activity: TsActivity): TspiIconName {
  if (activity.kind === "subagent") return activity.status.role === "compute" ? "roleCompute" : "roleReview";
  if (activity.kind === "remote") return "remote";
  return {
    structure: "tool",
    analysis: "tool",
    artifact: "tool",
    render: "roleRender",
    report: "roleReport",
    notify: "tool",
    remote: "remote",
  }[activity.activityKind] as TspiIconName;
}

function fitSides(left: string, right: string, width: number): string {
  const safeWidth = Math.max(1, width);
  const rightWidth = visibleWidth(right);
  if (!right) return truncateToWidth(left, safeWidth, "...");
  const leftWidth = visibleWidth(left);
  if (leftWidth + rightWidth + 1 <= safeWidth) return `${left}${" ".repeat(safeWidth - leftWidth - rightWidth)}${right}`;
  if (rightWidth >= safeWidth) return truncateToWidth(left, safeWidth, "...");
  return `${truncateToWidth(left, Math.max(1, safeWidth - rightWidth - 1), "...")} ${right}`;
}

function compact(values: Array<string | undefined>): string { return values.filter((value): value is string => Boolean(value)).join(" · "); }

export type { TsActivityStore, TsDeterministicActivity, TsSubagentActivity };
export { formatElapsed, stateSymbol } from "./activity-presentation.ts";
