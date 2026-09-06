import { homedir } from "node:os";
import { resolve } from "node:path";
import type {
  ExtensionAPI,
  ExtensionContext,
  InputEvent,
} from "@earendil-works/pi-coding-agent";
import { TsPhoneBridgeClient } from "./bridge-client.ts";
import type { BridgeAbortCommand, BridgePromptCommand } from "./protocol.ts";
import { authorizeTsPhoneTool } from "./policy.ts";

type TurnOrigin =
  | { kind: "local" | "extension" | "unknown"; turnId: string }
  | { kind: "phone"; turnId: string; requestId: string; clientMessageId: string };

interface PendingPhoneInput {
  requestId: string;
  clientMessageId: string;
  text: string;
}

const MAX_SEEN_MESSAGE_IDS = 1_000;
const MAX_SNAPSHOT_MESSAGES = 500;
const MAX_SNAPSHOT_BYTES = 6 * 1024 * 1024;

interface SessionRuntimeSnapshot {
  schemaVersion: "ts-phone-session-runtime/1";
  model: {
    provider: string;
    id: string;
  };
  context?: {
    usedTokens: number | null;
    limitTokens: number;
    measurement: "pi_estimate";
  };
  updatedAt: string;
}

export default function installTsPhoneBridge(pi: ExtensionAPI) {
  if (process.env.TS_PHONE_MODE !== "bridge") return;
  const workspaceId = requireWorkspaceId(process.env.TS_PHONE_WORKSPACE_ID);
  const accessMode = requireAccessMode(process.env.TS_PHONE_ACCESS_MODE);
  const socketPath = process.env.TS_PHONE_BRIDGE_SOCKET || defaultSocketPath();
  const secretPath = process.env.TS_PHONE_BRIDGE_SECRET_FILE
    || resolve(homedir(), ".local/state/ts-phone/bridge.secret");
  let context: ExtensionContext | undefined;
  let sessionGeneration = 0;
  let turnSequence = 0;
  let agentRunSequence = 0;
  let activeAgentRunId: string | undefined;
  let activeOrigin: TurnOrigin = { kind: "unknown", turnId: "turn-0" };
  const pendingOrigins: TurnOrigin[] = [];
  const pendingPhoneInputs: PendingPhoneInput[] = [];
  const seenClientMessageIds = new Set<string>();

  const bridge = new TsPhoneBridgeClient({
    workspaceId,
    workspaceRoot: process.cwd(),
    accessMode,
    socketPath,
    secretPath,
    getSessionId: () => context?.sessionManager.getSessionId() || "",
    getSessionGeneration: () => sessionGeneration,
    onCommand: (command) => handleCommand(command),
    onConnected: () => publishSnapshot(),
    onConnectionChanged(connected) {
      const label = accessMode === "observer" ? "Phone observer" : "Phone connected";
      context?.ui.setStatus("ts-phone", connected ? label : "Phone offline");
    },
  });

  pi.on("session_start", (_event, ctx) => {
    context = ctx;
    sessionGeneration += 1;
    agentRunSequence = 0;
    activeAgentRunId = undefined;
    pendingOrigins.length = 0;
    pendingPhoneInputs.length = 0;
    activeOrigin = { kind: "unknown", turnId: nextTurnId() };
    bridge.start();
    if (bridge.connected) publishSnapshot();
  });
  pi.on("session_shutdown", () => {
    context?.ui.setStatus("ts-phone", undefined);
    context = undefined;
    activeAgentRunId = undefined;
    bridge.stop();
  });
  pi.on("session_info_changed", () => publishSnapshot());
  pi.on("model_select", (event) => {
    bridge.publishEvent("model_select", {
      type: event.type,
      model: { provider: event.model.provider, id: event.model.id },
    });
    publishSnapshot();
  });
  pi.on("input", (event) => {
    const origin = classifyInput(event);
    if (event.streamingBehavior !== "steer") pendingOrigins.push(origin);
    bridge.publishEvent("input", {
      type: event.type,
      text: event.text,
      source: event.source,
      streamingBehavior: event.streamingBehavior,
      origin: origin.kind,
      turnId: origin.turnId,
      ...(origin.kind === "phone" ? { clientMessageId: origin.clientMessageId } : {}),
    });
  });
  pi.on("agent_start", (event) => {
    activeOrigin = pendingOrigins.shift() || { kind: "unknown", turnId: nextTurnId() };
    agentRunSequence += 1;
    activeAgentRunId = buildAgentRunId(sessionGeneration, agentRunSequence);
    bridge.publishEvent("agent_start", {
      type: event.type,
      origin: activeOrigin.kind,
      turnId: activeOrigin.turnId,
      agentRunId: activeAgentRunId,
    });
    publishSnapshot();
  });
  pi.on("message_start", (event) => {
    bridge.publishEvent("message_start", { type: event.type, message: projectMessage(event.message) });
  });
  pi.on("message_update", (event) => {
    bridge.publishEvent("message_update", {
      type: event.type,
      assistantMessageEvent: event.assistantMessageEvent,
    });
  });
  pi.on("message_end", (event) => {
    bridge.publishEvent("message_end", { type: event.type, message: projectMessage(event.message) });
  });
  pi.on("tool_execution_start", (event) => {
    bridge.publishEvent("tool_execution_start", {
      type: event.type,
      toolCallId: event.toolCallId,
      toolName: event.toolName,
    });
  });
  pi.on("tool_execution_end", (event) => {
    bridge.publishEvent("tool_execution_end", {
      type: event.type,
      toolCallId: event.toolCallId,
      toolName: event.toolName,
      isError: event.isError,
    });
  });
  pi.on("agent_settled", (event) => {
    bridge.publishEvent("agent_settled", {
      type: event.type,
      origin: activeOrigin.kind,
      turnId: activeOrigin.turnId,
      agentRunId: activeAgentRunId,
    });
    activeAgentRunId = undefined;
    activeOrigin = { kind: "unknown", turnId: nextTurnId() };
    publishSnapshot();
  });
  pi.on("tool_call", (event) => authorizeTsPhoneTool(accessMode, event.toolName));

  async function handleCommand(command: BridgePromptCommand | BridgeAbortCommand): Promise<void> {
    const ctx = context;
    if (!ctx
      || command.sessionId !== ctx.sessionManager.getSessionId()
      || command.sessionGeneration !== sessionGeneration) {
      throw new Error("stale_session");
    }
    if (command.type === "command.abort") {
      const rejection = abortCommandRejection(ctx.isIdle(), activeAgentRunId, command.agentRunId);
      if (rejection) throw new Error(rejection);
      ctx.abort();
      return;
    }
    if (seenClientMessageIds.has(command.clientMessageId)) return;
    rememberClientMessageId(command.clientMessageId);
    const pending = {
      requestId: command.requestId,
      clientMessageId: command.clientMessageId,
      text: command.message,
    };
    pendingPhoneInputs.push(pending);
    try {
      pi.sendUserMessage(command.message, ctx.isIdle() ? undefined : { deliverAs: "followUp" });
    } catch (error) {
      const index = pendingPhoneInputs.indexOf(pending);
      if (index >= 0) pendingPhoneInputs.splice(index, 1);
      seenClientMessageIds.delete(command.clientMessageId);
      throw error;
    }
  }

  function classifyInput(event: InputEvent): TurnOrigin {
    if (event.source === "extension") {
      const index = pendingPhoneInputs.findIndex((pending) => pending.text === event.text);
      if (index >= 0) {
        const pending = pendingPhoneInputs.splice(index, 1)[0]!;
        return {
          kind: "phone",
          turnId: nextTurnId(),
          requestId: pending.requestId,
          clientMessageId: pending.clientMessageId,
        };
      }
      return { kind: "extension", turnId: nextTurnId() };
    }
    if (event.source === "interactive" || event.source === "rpc") {
      return { kind: "local", turnId: nextTurnId() };
    }
    return { kind: "unknown", turnId: nextTurnId() };
  }

  function publishSnapshot(): void {
    const ctx = context;
    if (!ctx || sessionGeneration <= 0) return;
    const model = ctx.model ? `${ctx.model.provider}/${ctx.model.id}` : undefined;
    const runtime = buildSessionRuntimeSnapshot(
      ctx.model,
      ctx.getContextUsage(),
    );
    bridge.publishSnapshot({
      sessionId: ctx.sessionManager.getSessionId(),
      sessionName: ctx.sessionManager.getSessionName(),
      model,
      ...(runtime ? { runtime } : {}),
      thinkingLevel: ctx.thinkingLevel,
      isStreaming: activeAgentRunId !== undefined,
      ...(activeAgentRunId ? { agentRunId: activeAgentRunId } : {}),
      ...buildSnapshotMessagePage(ctx.sessionManager.getBranch()),
    });
  }

  function rememberClientMessageId(id: string): void {
    seenClientMessageIds.add(id);
    while (seenClientMessageIds.size > MAX_SEEN_MESSAGE_IDS) {
      const oldest = seenClientMessageIds.values().next().value as string | undefined;
      if (!oldest) break;
      seenClientMessageIds.delete(oldest);
    }
  }

  function nextTurnId(): string {
    turnSequence += 1;
    return `turn-${sessionGeneration}-${turnSequence}`;
  }
}

export function buildAgentRunId(sessionGeneration: number, sequence: number): string {
  if (!Number.isSafeInteger(sessionGeneration) || sessionGeneration <= 0) {
    throw new Error("sessionGeneration must be a positive integer");
  }
  if (!Number.isSafeInteger(sequence) || sequence <= 0) {
    throw new Error("agent run sequence must be a positive integer");
  }
  return `run-${sessionGeneration}-${sequence}`;
}

export function abortCommandRejection(
  isIdle: boolean,
  activeAgentRunId: string | undefined,
  commandAgentRunId: string,
): "agent_not_running" | "agent_run_stale" | undefined {
  if (isIdle || !activeAgentRunId) return "agent_not_running";
  if (commandAgentRunId !== activeAgentRunId) return "agent_run_stale";
  return undefined;
}

export function buildSessionRuntimeSnapshot(
  model: ExtensionContext["model"],
  usage: ReturnType<ExtensionContext["getContextUsage"]>,
  updatedAt = new Date().toISOString(),
): SessionRuntimeSnapshot | undefined {
  if (!model) return undefined;
  const runtime: SessionRuntimeSnapshot = {
    schemaVersion: "ts-phone-session-runtime/1",
    model: {
      provider: model.provider,
      id: model.id,
    },
    updatedAt,
  };
  if (usage && Number.isSafeInteger(usage.contextWindow) && usage.contextWindow > 0) {
    runtime.context = {
      usedTokens: usage.tokens,
      limitTokens: usage.contextWindow,
      measurement: "pi_estimate",
    };
  }
  return runtime;
}

export function buildSnapshotMessagePage(entries: readonly unknown[]): {
  messages: unknown[];
  messageIds: string[];
  hasMore: boolean;
  nextBefore?: string;
} {
  const projected = entries.flatMap((entry) => {
    if (!entry || typeof entry !== "object" || Array.isArray(entry)) return [];
    const candidate = entry as { type?: unknown; id?: unknown; message?: unknown };
    if (candidate.type !== "message" || typeof candidate.id !== "string") return [];
    const message = projectMessage(candidate.message);
    return message === undefined ? [] : [{ id: candidate.id, message }];
  });
  const earliest = Math.max(0, projected.length - MAX_SNAPSHOT_MESSAGES);
  let start = projected.length;
  let serializedBytes = 2; // JSON array brackets.
  while (start > earliest) {
    const entry = projected[start - 1]!;
    const messageBytes = Buffer.byteLength(JSON.stringify(entry.message) ?? "null");
    const nextBytes = serializedBytes + messageBytes + (start < projected.length ? 1 : 0);
    if (nextBytes > MAX_SNAPSHOT_BYTES) break;
    serializedBytes = nextBytes;
    start -= 1;
  }
  const bounded = projected.slice(start);
  const hasMore = bounded.length > 0 && bounded.length < projected.length;
  return {
    messages: bounded.map((entry) => entry.message),
    messageIds: bounded.map((entry) => entry.id),
    hasMore,
    ...(hasMore && bounded[0] ? { nextBefore: bounded[0].id } : {}),
  };
}

function requireAccessMode(value: string | undefined): "controller" | "observer" {
  if (value === undefined || value === "controller") return "controller";
  if (value === "observer") return value;
  throw new Error("TS_PHONE_ACCESS_MODE must be controller or observer");
}

export function projectMessage(message: unknown): unknown {
  if (!message || typeof message !== "object" || Array.isArray(message)) return undefined;
  const candidate = message as Record<string, unknown>;
  if (candidate.role === "user") {
    return {
      role: candidate.role,
      content: projectContent(candidate.content, 256 * 1024),
      timestamp: candidate.timestamp,
    };
  }
  if (candidate.role === "assistant" && Array.isArray(candidate.content)) {
    const content: Array<Record<string, unknown>> = [];
    for (const value of candidate.content) {
      if (!value || typeof value !== "object" || Array.isArray(value)) continue;
      const block = value as Record<string, unknown>;
      if (block.type === "text" && typeof block.text === "string") {
        content.push({ type: "text", text: boundText(block.text, 256 * 1024) });
        continue;
      }
      if (block.type === "toolCall" && typeof block.name === "string") {
        content.push({ type: "toolCall", name: block.name, arguments: block.arguments });
      }
    }
    return { role: candidate.role, content, timestamp: candidate.timestamp };
  }
  if (candidate.role === "toolResult") {
    return {
      role: candidate.role,
      toolCallId: candidate.toolCallId,
      toolName: candidate.toolName,
      content: projectContent(candidate.content, 128 * 1024),
      isError: candidate.isError,
      timestamp: candidate.timestamp,
    };
  }
  return undefined;
}

function projectContent(content: unknown, maxText: number): unknown {
  if (typeof content === "string") return boundText(content, maxText);
  if (!Array.isArray(content)) return [];
  return content.flatMap((block) => {
    if (!block || typeof block !== "object") return [];
    const candidate = block as { type?: unknown; text?: unknown };
    if (candidate.type === "text" && typeof candidate.text === "string") {
      return [{ type: "text", text: boundText(candidate.text, maxText) }];
    }
    return [];
  });
}

function boundText(value: string, max: number): string {
  return value.length <= max ? value : `${value.slice(0, max)}\n... [truncated by TS Phone]`;
}

function requireWorkspaceId(value: string | undefined): string {
  if (!value || !/^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$/.test(value)) {
    throw new Error("TS_PHONE_WORKSPACE_ID is missing or invalid");
  }
  return value;
}

function defaultSocketPath(): string {
  const runtimeDir = process.env.XDG_RUNTIME_DIR;
  if (runtimeDir?.startsWith("/")) return resolve(runtimeDir, "ts-phone/bridge.sock");
  return resolve(homedir(), ".local/state/ts-phone/runtime/bridge.sock");
}
