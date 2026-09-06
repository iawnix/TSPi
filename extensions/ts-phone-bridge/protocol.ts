export const BRIDGE_PROTOCOL_VERSION = "ts-phone-bridge/3" as const;

export interface BridgeIdentity {
  workspaceId: string;
  sessionId: string;
  instanceEpoch: string;
  sessionGeneration: number;
}

export interface BridgeRegisteredRecord {
  protocolVersion: typeof BRIDGE_PROTOCOL_VERSION;
  type: "bridge.registered";
  workspaceId: string;
  sessionId: string;
  instanceEpoch: string;
}

export interface BridgePromptCommand extends BridgeIdentity {
  protocolVersion: typeof BRIDGE_PROTOCOL_VERSION;
  type: "command.prompt";
  requestId: string;
  clientMessageId: string;
  message: string;
}

export interface BridgeAbortCommand extends BridgeIdentity {
  protocolVersion: typeof BRIDGE_PROTOCOL_VERSION;
  type: "command.abort";
  requestId: string;
  agentRunId: string;
}

export interface BridgeApprovalResponse extends BridgeIdentity {
  protocolVersion: typeof BRIDGE_PROTOCOL_VERSION;
  type: "approval.respond";
  requestId: string;
  approvalId: string;
  approved: boolean;
}

export type BridgeServerRecord = BridgeRegisteredRecord | BridgePromptCommand | BridgeAbortCommand | BridgeApprovalResponse;

export function parseBridgeServerRecord(value: unknown): BridgeServerRecord {
  const record = asObject(value);
  if (record.protocolVersion !== BRIDGE_PROTOCOL_VERSION) throw new Error("Unsupported TS Phone bridge protocol");
  const type = requiredString(record.type, "type", 100);
  if (type === "bridge.registered") {
    return {
      protocolVersion: BRIDGE_PROTOCOL_VERSION,
      type,
      workspaceId: requiredWorkspaceId(record.workspaceId),
      sessionId: requiredId(record.sessionId, "sessionId"),
      instanceEpoch: requiredId(record.instanceEpoch, "instanceEpoch"),
    };
  }
  const identity = {
    protocolVersion: BRIDGE_PROTOCOL_VERSION,
    workspaceId: requiredWorkspaceId(record.workspaceId),
    sessionId: requiredId(record.sessionId, "sessionId"),
    instanceEpoch: requiredId(record.instanceEpoch, "instanceEpoch"),
    sessionGeneration: positiveInteger(record.sessionGeneration, "sessionGeneration"),
  };
  if (type === "command.prompt") {
    return {
      ...identity,
      type,
      requestId: requiredId(record.requestId, "requestId"),
      clientMessageId: requiredId(record.clientMessageId, "clientMessageId"),
      message: requiredString(record.message, "message", 65_536),
    };
  }
  if (type === "command.abort") {
    return {
      ...identity,
      type,
      requestId: requiredId(record.requestId, "requestId"),
      agentRunId: requiredId(record.agentRunId, "agentRunId"),
    };
  }
  if (type === "approval.respond") {
    if (typeof record.approved !== "boolean") throw new Error("approved must be boolean");
    return {
      ...identity,
      type,
      requestId: requiredId(record.requestId, "requestId"),
      approvalId: requiredId(record.approvalId, "approvalId"),
      approved: record.approved,
    };
  }
  throw new Error(`Unsupported TS Phone bridge record: ${type}`);
}

function asObject(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Bridge record must be an object");
  return value as Record<string, unknown>;
}

function requiredString(value: unknown, name: string, max: number): string {
  if (typeof value !== "string" || value.length === 0 || value.length > max) {
    throw new Error(`${name} must be a non-empty bounded string`);
  }
  return value;
}

function requiredId(value: unknown, name: string): string {
  const parsed = requiredString(value, name, 160);
  if (!/^[A-Za-z0-9._:-]+$/.test(parsed)) throw new Error(`${name} is invalid`);
  return parsed;
}

function requiredWorkspaceId(value: unknown): string {
  const parsed = requiredString(value, "workspaceId", 80);
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$/.test(parsed)) throw new Error("workspaceId is invalid");
  return parsed;
}

function positiveInteger(value: unknown, name: string): number {
  if (!Number.isSafeInteger(value) || (value as number) <= 0) throw new Error(`${name} must be positive`);
  return value as number;
}
