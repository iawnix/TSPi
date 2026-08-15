import { homedir } from "node:os";
import { resolve } from "node:path";
import type {
  ExtensionAPI,
  ExtensionContext,
  InputEvent,
  ToolCallEvent,
} from "@earendil-works/pi-coding-agent";
import { TsPhoneBridgeClient } from "./bridge-client.ts";
import type { BridgeAbortCommand, BridgePromptCommand } from "./protocol.ts";
import { CONFIRMATION_REQUIRED_TOOLS, DIRECTLY_ALLOWED_TOOLS, formatConfirmation } from "./policy.ts";

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

export default function installTsPhoneBridge(pi: ExtensionAPI) {
  if (process.env.TS_PHONE_MODE !== "bridge") return;
  const workspaceId = requireWorkspaceId(process.env.TS_PHONE_WORKSPACE_ID);
  const socketPath = process.env.TS_PHONE_BRIDGE_SOCKET || defaultSocketPath();
  const secretPath = process.env.TS_PHONE_BRIDGE_SECRET_FILE
    || resolve(homedir(), ".local/state/ts-phone/bridge.secret");
  let context: ExtensionContext | undefined;
  let sessionGeneration = 0;
  let turnSequence = 0;
  let activeOrigin: TurnOrigin = { kind: "unknown", turnId: "turn-0" };
  const pendingOrigins: TurnOrigin[] = [];
  const pendingPhoneInputs: PendingPhoneInput[] = [];
  const seenClientMessageIds = new Set<string>();

  const bridge = new TsPhoneBridgeClient({
    workspaceId,
    workspaceRoot: process.cwd(),
    socketPath,
    secretPath,
    getSessionGeneration: () => sessionGeneration,
    onCommand: (command) => handleCommand(command),
    onConnected: () => publishSnapshot(),
    onConnectionChanged(connected) {
      context?.ui.setStatus("ts-phone", connected ? "Phone connected" : "Phone offline");
    },
  });

  pi.on("session_start", (_event, ctx) => {
    context = ctx;
    sessionGeneration += 1;
    pendingOrigins.length = 0;
    pendingPhoneInputs.length = 0;
    activeOrigin = { kind: "unknown", turnId: nextTurnId() };
    bridge.start();
    if (bridge.connected) publishSnapshot();
  });
  pi.on("session_shutdown", () => {
    context?.ui.setStatus("ts-phone", undefined);
    context = undefined;
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
    bridge.publishEvent("agent_start", { ...event, origin: activeOrigin.kind, turnId: activeOrigin.turnId });
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
    bridge.publishEvent("agent_settled", { ...event, origin: activeOrigin.kind, turnId: activeOrigin.turnId });
    activeOrigin = { kind: "unknown", turnId: nextTurnId() };
    publishSnapshot();
  });
  pi.on("tool_call", async (event) => authorizePhoneTool(event));

  async function handleCommand(command: BridgePromptCommand | BridgeAbortCommand): Promise<void> {
    const ctx = context;
    if (!ctx || command.sessionGeneration !== sessionGeneration) throw new Error("stale_session");
    if (command.type === "command.abort") {
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

  async function authorizePhoneTool(event: ToolCallEvent) {
    if (activeOrigin.kind !== "phone") return;
    if (DIRECTLY_ALLOWED_TOOLS.has(event.toolName)) return;
    if (!CONFIRMATION_REQUIRED_TOOLS.has(event.toolName)) {
      return { block: true, reason: `TS Phone blocked unclassified tool: ${event.toolName}` };
    }
    const approved = await bridge.requestApproval({
      turnId: activeOrigin.turnId,
      toolCallId: event.toolCallId,
      toolName: event.toolName,
      preview: formatConfirmation(event),
    });
    if (approved) return;
    return { block: true, reason: `TS Phone user did not approve tool: ${event.toolName}` };
  }

  function publishSnapshot(): void {
    const ctx = context;
    if (!ctx || sessionGeneration <= 0) return;
    const model = ctx.model ? `${ctx.model.provider}/${ctx.model.id}` : undefined;
    bridge.publishSnapshot({
      sessionId: ctx.sessionManager.getSessionId(),
      sessionName: ctx.sessionManager.getSessionName(),
      model,
      thinkingLevel: ctx.thinkingLevel,
      isStreaming: !ctx.isIdle(),
      messages: snapshotMessages(ctx),
    });
  }

  function snapshotMessages(ctx: ExtensionContext): unknown[] {
    const projected = ctx.sessionManager.getBranch()
      .filter((entry) => entry.type === "message")
      .map((entry) => projectMessage(entry.message))
      .filter((message) => message !== undefined)
      .slice(-MAX_SNAPSHOT_MESSAGES);
    while (projected.length > 1 && Buffer.byteLength(JSON.stringify(projected)) > MAX_SNAPSHOT_BYTES) {
      projected.shift();
    }
    return projected;
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
