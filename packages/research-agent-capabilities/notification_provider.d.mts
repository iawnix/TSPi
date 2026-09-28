import type { CapabilityDescriptor, CapabilityProvider } from "./tool_gateway.mjs";

export const NOTIFICATION_CAPABILITY_ID: "notification_send";
export const NOTIFICATION_CAPABILITY_VERSION: "1";
export const NOTIFICATION_EVENTS: readonly [
  "progress",
  "node_completed",
  "calculation_failed",
  "calculation_ambiguous",
  "study_completed",
];
export const NOTIFICATION_DESCRIPTOR: CapabilityDescriptor;

export interface NotificationRequest {
  readonly protocol: "notification_request";
  readonly version: 1;
  readonly operation: "send";
  readonly event: (typeof NOTIFICATION_EVENTS)[number];
  readonly subject: string;
  readonly summary: string;
  readonly report_refs: readonly string[];
}

export interface NotificationResult {
  readonly protocol: "notification_result";
  readonly version: 1;
  readonly operation: "send";
  readonly state: "sent" | "already_sent";
  readonly receipt_ref: string;
  readonly external_side_effects: boolean;
  readonly event?: (typeof NOTIFICATION_EVENTS)[number];
  readonly subject?: string;
  readonly report_refs?: readonly string[];
  readonly notification_digest?: string;
  readonly artifact_refs?: readonly string[];
}

export function normalize_notification_request(value: unknown): NotificationRequest;
export function normalize_notification_result(value: unknown): NotificationResult;

export interface NotificationProvider extends CapabilityProvider {
  readonly provider_id: string;
  readonly provider_version: string;
}

export function create_notification_provider(options: {
  readonly send: (request: NotificationRequest) => Promise<NotificationResult | Record<string, unknown>> | NotificationResult | Record<string, unknown>;
  readonly provider_id?: string;
  readonly provider_version?: string;
}): NotificationProvider;
