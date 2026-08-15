import { randomUUID } from "node:crypto";
import { constants } from "node:fs";
import { open } from "node:fs/promises";
import { createConnection, type Socket } from "node:net";
import { StringDecoder } from "node:string_decoder";
import {
  BRIDGE_PROTOCOL_VERSION,
  parseBridgeServerRecord,
  type BridgeAbortCommand,
  type BridgePromptCommand,
} from "./protocol.ts";

const HEARTBEAT_MS = 15_000;
const APPROVAL_TIMEOUT_MS = 5 * 60_000;
const MAX_SERVER_RECORD_BYTES = 256 * 1024;

interface PendingApproval {
  resolve: (approved: boolean) => void;
  timer: NodeJS.Timeout;
}

export interface BridgeClientOptions {
  workspaceId: string;
  workspaceRoot: string;
  socketPath: string;
  secretPath: string;
  getSessionGeneration(): number;
  onCommand(command: BridgePromptCommand | BridgeAbortCommand): Promise<void> | void;
  onConnected(): void;
  onConnectionChanged(connected: boolean): void;
}

export class TsPhoneBridgeClient {
  readonly instanceEpoch = randomUUID();
  readonly #options: BridgeClientOptions;
  readonly #pendingApprovals = new Map<string, PendingApproval>();
  #socket: Socket | undefined;
  #sequence = 0;
  #running = false;
  #connected = false;
  #reconnectDelayMs = 1_000;
  #reconnectTimer: NodeJS.Timeout | undefined;
  #heartbeat: NodeJS.Timeout | undefined;

  constructor(options: BridgeClientOptions) {
    this.#options = options;
  }

  get connected(): boolean {
    return this.#connected;
  }

  start(): void {
    if (this.#running) return;
    this.#running = true;
    void this.#connect();
  }

  stop(): void {
    this.#running = false;
    if (this.#reconnectTimer) clearTimeout(this.#reconnectTimer);
    if (this.#heartbeat) clearInterval(this.#heartbeat);
    this.#reconnectTimer = undefined;
    this.#heartbeat = undefined;
    this.#socket?.destroy();
    this.#socket = undefined;
    this.#setConnected(false);
    this.#rejectApprovals();
  }

  publishSnapshot(snapshot: Record<string, unknown>): boolean {
    return this.#publish("session.snapshot", { snapshot });
  }

  publishEvent(eventType: string, payload: unknown): boolean {
    return this.#publish("event.publish", { eventType, payload });
  }

  requestApproval(input: {
    turnId: string;
    toolCallId: string;
    toolName: string;
    preview: string;
  }): Promise<boolean> {
    if (!this.#connected) return Promise.resolve(false);
    const approvalId = randomUUID();
    const expiresAt = new Date(Date.now() + APPROVAL_TIMEOUT_MS).toISOString();
    return new Promise<boolean>((resolve) => {
      const timer = setTimeout(() => {
        this.#pendingApprovals.delete(approvalId);
        resolve(false);
      }, APPROVAL_TIMEOUT_MS);
      timer.unref();
      this.#pendingApprovals.set(approvalId, { resolve, timer });
      if (!this.#publish("approval.request", { approvalId, expiresAt, ...input })) {
        clearTimeout(timer);
        this.#pendingApprovals.delete(approvalId);
        resolve(false);
      }
    });
  }

  async #connect(): Promise<void> {
    if (!this.#running || this.#socket) return;
    try {
      const secret = await readSecureSecret(this.#options.secretPath);
      if (!this.#running) return;
      const socket = createConnection(this.#options.socketPath);
      this.#socket = socket;
      socket.setNoDelay(true);
      attachServerReader(socket, (record) => void this.#handleRecord(record), () => socket.destroy());
      await new Promise<void>((resolve, reject) => {
        socket.once("connect", resolve);
        socket.once("error", reject);
      });
      this.#write({
        protocolVersion: BRIDGE_PROTOCOL_VERSION,
        type: "bridge.register",
        workspaceId: this.#options.workspaceId,
        workspaceRoot: this.#options.workspaceRoot,
        instanceEpoch: this.instanceEpoch,
        sessionGeneration: this.#options.getSessionGeneration(),
        secret,
        pid: process.pid,
      });
      socket.once("close", () => this.#handleDisconnect(socket));
      socket.once("error", () => this.#handleDisconnect(socket));
    } catch {
      this.#socket?.destroy();
      this.#socket = undefined;
      this.#scheduleReconnect();
    }
  }

  async #handleRecord(value: unknown): Promise<void> {
    try {
      const record = parseBridgeServerRecord(value);
      if (record.workspaceId !== this.#options.workspaceId || record.instanceEpoch !== this.instanceEpoch) {
        throw new Error("TS Phone bridge server changed connection identity");
      }
      if (record.type === "bridge.registered") {
        this.#reconnectDelayMs = 1_000;
        this.#setConnected(true);
        if (this.#heartbeat) clearInterval(this.#heartbeat);
        this.#heartbeat = setInterval(() => this.#publish("bridge.heartbeat", {}), HEARTBEAT_MS);
        this.#heartbeat.unref();
        this.#options.onConnected();
        return;
      }
      if (record.sessionGeneration !== this.#options.getSessionGeneration()) return;
      if (record.type === "approval.respond") {
        const pending = this.#pendingApprovals.get(record.approvalId);
        if (!pending) {
          this.#acknowledge(record.requestId, false, "approval_not_found");
          return;
        }
        clearTimeout(pending.timer);
        this.#pendingApprovals.delete(record.approvalId);
        pending.resolve(record.approved);
        this.#acknowledge(record.requestId, true);
        return;
      }
      try {
        await this.#options.onCommand(record);
        this.#acknowledge(record.requestId, true);
      } catch (error) {
        this.#acknowledge(record.requestId, false, errorCode(error));
      }
    } catch {
      this.#socket?.destroy();
    }
  }

  #publish(type: string, extra: Record<string, unknown>): boolean {
    if (!this.#connected || !this.#socket || this.#socket.destroyed) return false;
    this.#sequence += 1;
    this.#write({
      protocolVersion: BRIDGE_PROTOCOL_VERSION,
      type,
      workspaceId: this.#options.workspaceId,
      instanceEpoch: this.instanceEpoch,
      sessionGeneration: this.#options.getSessionGeneration(),
      sequence: this.#sequence,
      ...extra,
    });
    return true;
  }

  #acknowledge(requestId: string, ok: boolean, errorCodeValue?: string): void {
    const record: Record<string, unknown> = {
      protocolVersion: BRIDGE_PROTOCOL_VERSION,
      type: "command.ack",
      workspaceId: this.#options.workspaceId,
      instanceEpoch: this.instanceEpoch,
      sessionGeneration: this.#options.getSessionGeneration(),
      requestId,
      ok,
    };
    if (errorCodeValue) record.errorCode = errorCodeValue;
    this.#write(record);
  }

  #write(record: Record<string, unknown>): void {
    if (!this.#socket || this.#socket.destroyed) throw new Error("TS Phone bridge is offline");
    this.#socket.write(`${JSON.stringify(record)}\n`);
  }

  #handleDisconnect(socket: Socket): void {
    if (this.#socket !== socket) return;
    this.#socket = undefined;
    if (this.#heartbeat) clearInterval(this.#heartbeat);
    this.#heartbeat = undefined;
    this.#setConnected(false);
    this.#rejectApprovals();
    this.#scheduleReconnect();
  }

  #scheduleReconnect(): void {
    if (!this.#running || this.#reconnectTimer) return;
    this.#reconnectTimer = setTimeout(() => {
      this.#reconnectTimer = undefined;
      void this.#connect();
    }, this.#reconnectDelayMs);
    this.#reconnectTimer.unref();
    this.#reconnectDelayMs = Math.min(this.#reconnectDelayMs * 2, 15_000);
  }

  #setConnected(connected: boolean): void {
    if (this.#connected === connected) return;
    this.#connected = connected;
    this.#options.onConnectionChanged(connected);
  }

  #rejectApprovals(): void {
    for (const pending of this.#pendingApprovals.values()) {
      clearTimeout(pending.timer);
      pending.resolve(false);
    }
    this.#pendingApprovals.clear();
  }
}

async function readSecureSecret(path: string): Promise<string> {
  const handle = await open(path, constants.O_RDONLY | constants.O_NOFOLLOW);
  try {
    const stat = await handle.stat();
    if (!stat.isFile() || (typeof process.getuid === "function" && stat.uid !== process.getuid())) {
      throw new Error("TS Phone bridge secret must be an owner-controlled file");
    }
    if ((stat.mode & 0o077) !== 0) throw new Error("TS Phone bridge secret permissions must be 0600");
    const secret = (await handle.readFile("utf8")).trim();
    if (!/^[A-Za-z0-9_-]{40,100}$/.test(secret)) throw new Error("TS Phone bridge secret is invalid");
    return secret;
  } finally {
    await handle.close();
  }
}

function attachServerReader(socket: Socket, onValue: (value: unknown) => void, onError: () => void): void {
  const decoder = new StringDecoder("utf8");
  let buffer = "";
  socket.on("data", (chunk: Buffer | string) => {
    buffer += typeof chunk === "string" ? chunk : decoder.write(chunk);
    while (true) {
      const newline = buffer.indexOf("\n");
      if (newline < 0) break;
      const line = buffer.slice(0, newline).replace(/\r$/, "");
      buffer = buffer.slice(newline + 1);
      if (!line) continue;
      try {
        onValue(JSON.parse(line));
      } catch {
        onError();
        return;
      }
    }
    if (Buffer.byteLength(buffer) > MAX_SERVER_RECORD_BYTES) onError();
  });
}

function errorCode(error: unknown): string {
  if (error instanceof Error && /^[A-Za-z0-9._:-]{1,160}$/.test(error.message)) return error.message;
  return "bridge_command_failed";
}
