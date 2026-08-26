import type { EventBus } from "@earendil-works/pi-coding-agent";

export const TS_ACTIVITY_STATES = ["running", "completed", "failed"] as const;
export const TS_REMOTE_ACTIVITY_MODES = ["status", "doctor", "queues", "nodes"] as const;
export const TS_ACTIVITY_EVENT_CHANNEL = "ts-workflow:activity/1";

export type TsPublishedActivityState = typeof TS_ACTIVITY_STATES[number];
export type TsRemoteActivityMode = typeof TS_REMOTE_ACTIVITY_MODES[number];

export interface TsRemoteActivity {
  kind: "remote";
  id: string;
  mode: TsRemoteActivityMode;
  state: TsPublishedActivityState;
  detail: string;
  startedAt: number;
  updatedAt: number;
  terminalAt?: number;
  error?: string;
}

export type TsActivityEvent =
  | { type: "upsert"; activity: TsRemoteActivity }
  | { type: "remove"; activityId: string };

export type TsActivityListener = (event: TsActivityEvent) => void;

export function publishTsActivity(events: EventBus, event: TsActivityEvent): void {
  events.emit(TS_ACTIVITY_EVENT_CHANNEL, event);
}

export function subscribeTsActivity(events: EventBus, listener: TsActivityListener): () => void {
  return events.on(TS_ACTIVITY_EVENT_CHANNEL, (candidate) => {
    if (isTsActivityEvent(candidate)) listener(candidate);
  });
}

function isTsActivityEvent(value: unknown): value is TsActivityEvent {
  if (!isObject(value)) return false;
  if (value.type === "remove") return typeof value.activityId === "string" && value.activityId.length > 0;
  if (value.type !== "upsert" || !isObject(value.activity)) return false;
  const activity = value.activity;
  return activity.kind === "remote"
    && typeof activity.id === "string"
    && (TS_REMOTE_ACTIVITY_MODES as readonly unknown[]).includes(activity.mode)
    && (TS_ACTIVITY_STATES as readonly unknown[]).includes(activity.state)
    && typeof activity.detail === "string"
    && typeof activity.startedAt === "number"
    && Number.isFinite(activity.startedAt)
    && typeof activity.updatedAt === "number"
    && Number.isFinite(activity.updatedAt)
    && (activity.terminalAt === undefined || (typeof activity.terminalAt === "number" && Number.isFinite(activity.terminalAt)))
    && (activity.error === undefined || typeof activity.error === "string");
}

function isObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
