#!/usr/bin/env node
import { createHash, randomUUID } from "node:crypto";
import { link, lstat, mkdir, readFile, readdir, realpath, rename, unlink, writeFile } from "node:fs/promises";
import { basename, dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { protocolError } from "./tspi-host-client.mjs";

const PACKAGE_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$/u;
const WORKSPACE_ID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$/u;
const V4_SESSION_DIRECTORY_PREFIX = "--";

function canonicalSessionsRoot(installRoot) {
  return join(installRoot, ".pi", "app-server-host", "sessions");
}

function workspaceSessionsRoot(cwd) {
  return join(cwd, ".pi", "sessions");
}

function isContained(root, path) {
  const value = relative(root, path);
  return value === "" || (value !== ".." && !value.startsWith(`..${sep}`) && !isAbsolute(value));
}

function v4SessionDirectoryName(cwd) {
  return `${V4_SESSION_DIRECTORY_PREFIX}${cwd.replace(/^[/\\]/u, "").replace(/[/\\:]/gu, "-")}--`;
}

function v4SessionFileName(createdAt, id) {
  const timestamp = new Date(createdAt).toISOString().replace(/[:.]/gu, "-");
  return `${timestamp}_${encodeURIComponent(id)}.jsonl`;
}

/** Pure parsing: never use JsonlStorage.open, which repairs a torn source file. */
export function parseHistory(content, expectedCwd) {
  if (typeof content !== "string" || !content.endsWith("\n")) throw protocolError("incomplete_history", "History has an incomplete final transaction; stop its writer and inspect it before import");
  const lines = content.trimEnd().split("\n");
  let rows;
  try { rows = lines.map((line) => JSON.parse(line)); } catch { throw protocolError("invalid_history", "History contains invalid JSON; the source was left unchanged"); }
  const header = rows.shift();
  if (!header || typeof header.id !== "string" || !ID.test(header.id) || typeof header.cwd !== "string") throw protocolError("invalid_history", "History header has no valid session identity");
  if (expectedCwd !== undefined && header.cwd !== expectedCwd) throw protocolError("session_workspace_mismatch", "History header.cwd belongs to a different workspace");
  if (header.type === "session" && header.version === 3) {
    if (!Number.isFinite(Date.parse(header.timestamp))) throw protocolError("invalid_history", "Pi v3 history timestamp is invalid");
    const known = new Set();
    const supportedTypes = new Set(["message", "custom", "custom_message", "branch_summary", "compaction", "model_change", "thinking_level_change", "active_tools_change", "session_info", "label"]);
    for (const entry of rows) {
      if (!entry || typeof entry.type !== "string" || !supportedTypes.has(entry.type)
        || typeof entry.id !== "string" || !ID.test(entry.id) || known.has(entry.id)
        || (entry.parentId !== null && !known.has(entry.parentId))) {
        throw protocolError("invalid_history", "Pi v3 history contains an unsupported record, invalid parent chain, or duplicate entry");
      }
      known.add(entry.id);
    }
    return { version: 3, header, entries: rows, transactions: [], values: new Map(), sourceContent: content };
  }
  if (header.kind !== "header" || header.v !== 4 || header.storageVersion !== 1 || !Number.isSafeInteger(header.createdAt) || header.createdAt < 0) throw protocolError("unsupported_history", "Only ordinary Pi v3 and experimental Pi v4 storageVersion 1 can be inspected");
  const entries = new Map();
  const values = new Map();
  const knownIds = new Set();
  const transactions = [];
  let previousSeq = 0;
  let usageCount = 0;
  let listWriteCount = 0;
  for (const row of rows) {
    const writes = Array.isArray(row) ? row : [row];
    for (const item of writes) {
      if (!item || !Number.isSafeInteger(item.seq) || item.seq <= previousSeq) throw protocolError("invalid_history", "Pi v4 transaction sequence is invalid");
      previousSeq = item.seq;
      if (item.kind === "entry" || item.kind === "usage") {
        if (typeof item.id !== "string" || !ID.test(item.id) || knownIds.has(item.id)) throw protocolError("invalid_history", "Pi v4 entry identity is invalid or duplicated");
        knownIds.add(item.id);
      }
      if (item.kind === "entry") {
        if (!Number.isSafeInteger(item.timestamp) || item.timestamp < 0 || (item.parentId !== null && !entries.has(item.parentId))) throw protocolError("invalid_history", "Pi v4 entry has an invalid timestamp or missing parent");
        entries.set(item.id, item);
      } else if (item.kind === "value") {
        if (typeof item.namespace !== "string" || typeof item.key !== "string" || !["set", "delete"].includes(item.op)) throw protocolError("invalid_history", "Pi v4 value write is invalid");
        const key = `${item.namespace}\0${item.key}`;
        if (item.op === "delete") values.delete(key);
        else values.set(key, item.value);
      } else if (item.kind === "list") {
        if (typeof item.namespace !== "string" || typeof item.key !== "string" || !["append", "delete"].includes(item.op)) throw protocolError("invalid_history", "Pi v4 list write is invalid");
        listWriteCount += 1;
      } else if (item.kind === "usage") usageCount += 1;
      else throw protocolError("unsupported_history", `Unsupported Pi v4 transaction kind: ${String(item.kind)}`);
    }
    transactions.push(writes);
  }
  return { version: 4, header, entries: [...entries.values()], transactions, values, usageCount, listWriteCount, sourceContent: content };
}

/** Optional pinned SDK validation, replaying exclusively into an in-memory store. */
export async function validateWithPiSdk(parsed, sourceRoot) {
  if (parsed.version !== 4 || !sourceRoot) return false;
  const modulePath = join(sourceRoot, "packages/agent/src/harness/session/in-memory-storage-state.ts");
  const { InMemoryStorageState } = await import(pathToFileURL(modulePath).href);
  const state = new InMemoryStorageState();
  for (const writes of parsed.transactions) {
    state.validateCommitted(writes);
    state.applyValidated(writes);
  }
  return true;
}

/** Convert a settled main branch to a new v3 transcript; execution state is omitted. */
export function convertHistory(parsed, { sessionId, timestamp = new Date().toISOString() } = {}) {
  if (parsed.version === 3) return { content: parsed.sourceContent, session_id: parsed.header.id, report: { mode: "v3_exact_copy", lossless: true, imported_entries: parsed.entries.length, omitted: [] } };
  if (!sessionId || !ID.test(sessionId)) throw protocolError("invalid_identifier", "Import needs a new session_id");
  const lane = parsed.values.get("pi.lane.state\0main");
  if (lane?.currentOperationId) throw protocolError("session_busy", "The legacy main lane still has an active or suspended operation; settle it before importing history");
  if (!parsed.values.has("pi.branch.tip\0main")) throw protocolError("unsupported_history", "Legacy history has no explicit main branch tip");
  const indexed = new Map(parsed.entries.map((entry) => [entry.id, entry]));
  const selected = [];
  const visited = new Set();
  let cursor = parsed.values.get("pi.branch.tip\0main");
  while (cursor !== null) {
    if (typeof cursor !== "string" || visited.has(cursor) || !indexed.has(cursor)) throw protocolError("invalid_history", "Legacy main branch has a missing entry or cycle");
    visited.add(cursor);
    const entry = indexed.get(cursor);
    selected.unshift(entry);
    cursor = entry.parentId;
  }
  const output = [{ type: "session", version: 3, id: sessionId, timestamp, cwd: parsed.header.cwd }];
  let parentId = null;
  const append = (entry, data, at = timestamp) => {
    const id = output.length.toString(16).padStart(8, "0");
    output.push({ ...data, id, parentId, timestamp: at });
    parentId = id;
    return id;
  };
  const configuration = parsed.values.get("pi.lane.config\0main");
  if (configuration?.model?.provider && configuration.model.modelId) append(null, { type: "model_change", provider: configuration.model.provider, modelId: configuration.model.modelId });
  if (configuration?.thinkingLevel) append(null, { type: "thinking_level_change", thinkingLevel: configuration.thinkingLevel });
  let inertCustomCount = 0;
  for (const entry of selected) {
    const at = new Date(entry.timestamp).toISOString();
    if (entry.type === "message") {
      const message = entry.message;
      if (!message || typeof message.role !== "string") throw protocolError("invalid_history", "Legacy message has no role");
      if (message.role === "assistant" && message.stopReason === "pending") throw protocolError("session_busy", "Legacy main branch contains an unfinished assistant message");
      if (["user", "assistant", "toolResult", "bashExecution"].includes(message.role)) {
        append(entry, { type: "message", message }, at);
      } else if (message.role === "custom") {
        append(entry, { type: "custom_message", customType: "tspi.imported-message", content: message.content, display: message.display !== false, details: { source_custom_type: message.customType, source_details: message.details } }, at);
      } else {
        throw protocolError("unsupported_history", `Legacy message role cannot be imported safely: ${message.role}`);
      }
    } else if (entry.type === "custom") {
      inertCustomCount += 1;
      append(entry, { type: "custom", customType: "tspi.imported-entry", data: { source_id: entry.id, source_custom_type: entry.customType, source_data: entry.data } }, at);
    } else if (entry.type === "branch_summary") {
      append(entry, { type: "custom_message", customType: "tspi.imported-summary", content: `Legacy branch summary:\n${entry.summary}`, display: true, details: { source_id: entry.id, from_id: entry.fromId } }, at);
    } else if (entry.type === "compaction") {
      throw protocolError("unsupported_compaction", "This legacy branch contains v4 compaction retainedTail state. It cannot be mapped losslessly to a v3 firstKeptEntryId; use the read-only export and start a new conversation with an explicit summary");
    } else throw protocolError("unsupported_history", `Legacy entry type cannot be imported safely: ${String(entry.type)}`);
  }
  const name = parsed.values.get("pi.session.name\0");
  if (typeof name === "string") append(null, { type: "session_info", name: `${name} (imported)` });
  const report = {
    mode: "v4_main_branch_snapshot", lossless: false, branch: "main", source_session_id: parsed.header.id, source_sha256: sha256(parsed.sourceContent), source_tip_id: parsed.values.get("pi.branch.tip\0main"),
    imported_entries: selected.length, inert_custom_entries: inertCustomCount,
    omitted: ["other branches", "lane execution and operation checkpoints", "queued input and pending tool or assistant output", "standalone usage records", "client presentation and plugin selections"],
    omitted_entry_count: parsed.entries.length - selected.length,
    omitted_queue_count: Array.isArray(lane?.inbox) ? lane.inbox.length : 0,
    omitted_usage_record_count: parsed.usageCount,
    omitted_list_write_count: parsed.listWriteCount,
  };
  append(null, { type: "custom", customType: "tspi.history-import", data: report });
  return { content: `${output.map((row) => JSON.stringify(row)).join("\n")}\n`, session_id: sessionId, report };
}

/**
 * Convert a legacy Pi v3 transcript into the pinned Harness v4 JSONL
 * representation. The source remains untouched; the returned bytes are a
 * complete, independently durable v4 session that JsonlStorage can reopen.
 */
export function convertLegacyV3ToV4(parsed, { sessionId, timestamp, sourceSha256 } = {}) {
  if (!parsed || parsed.version !== 3) throw protocolError("unsupported_history", "v3 to v4 import requires a Pi v3 history");
  if (!sessionId || !ID.test(sessionId)) throw protocolError("invalid_identifier", "Import needs a new session_id");
  const createdAt = Number.isFinite(Date.parse(timestamp || parsed.header.timestamp))
    ? Date.parse(timestamp || parsed.header.timestamp)
    : NaN;
  if (!Number.isSafeInteger(createdAt) || createdAt < 0) throw protocolError("invalid_history", "Pi v3 history timestamp is invalid");

  const entriesById = new Map();
  for (const entry of parsed.entries) {
    if (entriesById.has(entry.id)) throw protocolError("invalid_history", "Pi v3 history contains duplicate entry IDs");
    entriesById.set(entry.id, entry);
  }
  const activeChain = [];
  const activeSeen = new Set();
  let activeCursor = parsed.entries.at(-1)?.id ?? null;
  while (activeCursor !== null && activeCursor !== undefined) {
    if (activeSeen.has(activeCursor)) throw protocolError("invalid_history", "Pi v3 history contains a parent cycle");
    const activeEntry = entriesById.get(activeCursor);
    if (!activeEntry) throw protocolError("invalid_history", "Pi v3 history references a missing active entry");
    activeSeen.add(activeCursor);
    activeChain.unshift(activeEntry);
    activeCursor = activeEntry.parentId;
  }
  const retained = parsed.entries.filter((entry) => ["message", "custom", "custom_message", "branch_summary", "compaction"].includes(entry.type));
  const reminted = new Map(retained.map((entry, index) => [entry.id, `v3-${index.toString(36)}-${sha256(entry.id).slice(0, 12)}`]));
  const resolveRetained = (legacyId) => {
    const visited = new Set();
    let cursor = legacyId;
    while (cursor !== null && cursor !== undefined) {
      if (reminted.has(cursor)) return reminted.get(cursor);
      if (visited.has(cursor)) throw protocolError("invalid_history", "Pi v3 history contains a parent cycle");
      visited.add(cursor);
      const parent = entriesById.get(cursor);
      if (!parent) throw protocolError("invalid_history", `Pi v3 history references missing entry ${cursor}`);
      cursor = parent.parentId;
    }
    return null;
  };
  const writes = [];
  const push = (write) => {
    const next = { ...write, seq: writes.length + 1 };
    writes.push(next);
    return next;
  };
  let importedEntries = 0;
  let omittedEntries = 0;
  for (const entry of retained) {
    const at = Date.parse(entry.timestamp);
    if (!Number.isSafeInteger(at) || at < 0) throw protocolError("invalid_history", "Pi v3 entry timestamp is invalid");
    const base = { kind: "entry", id: reminted.get(entry.id), parentId: resolveRetained(entry.parentId), timestamp: at };
    if (entry.type === "message") {
      if (!entry.message || typeof entry.message.role !== "string") throw protocolError("invalid_history", "Pi v3 message entry has no role");
      if (entry.message.role === "assistant" && entry.message.stopReason === "pending" && activeSeen.has(entry.id)) throw protocolError("session_busy", "Pi v3 history contains an unfinished assistant message");
      push({ ...base, type: "message", message: entry.message });
    } else if (entry.type === "custom_message") {
      push({ ...base, type: "message", message: { role: "custom", customType: entry.customType, content: entry.content, details: entry.details, display: entry.display !== false, timestamp: at } });
    } else if (entry.type === "custom") {
      push({ ...base, type: "custom", customType: entry.customType, data: entry.data });
    } else if (entry.type === "branch_summary") {
      const fromId = entry.fromId === "root" ? null : resolveRetained(entry.fromId);
      if (entry.fromId !== "root" && fromId === null) throw protocolError("invalid_history", "Pi v3 branch summary references no retained ancestor");
      push({ ...base, type: "branch_summary", fromId, summary: entry.summary, details: entry.details, usage: entry.usage, fromHook: entry.fromHook === true });
    } else if (entry.type === "compaction") {
      // v4 stores a materialized retained tail. Reconstruct the tail from the
      // source branch and keep only message-shaped context entries.
      const tail = [];
      let cursor = entry.parentId;
      const seen = new Set();
      while (cursor !== null && cursor !== undefined && cursor !== entry.firstKeptEntryId) {
        if (seen.has(cursor)) throw protocolError("invalid_history", "Pi v3 compaction parent chain contains a cycle");
        seen.add(cursor);
        const candidate = entriesById.get(cursor);
        if (!candidate) throw protocolError("invalid_history", "Pi v3 compaction references a missing parent");
        if (candidate.type === "message") tail.unshift(candidate.message);
        else if (candidate.type === "custom_message") tail.unshift({ role: "custom", customType: candidate.customType, content: candidate.content, details: candidate.details, display: candidate.display !== false, timestamp: Date.parse(candidate.timestamp) });
        cursor = candidate.parentId;
      }
      if (entry.firstKeptEntryId !== undefined && entry.firstKeptEntryId !== null && cursor !== entry.firstKeptEntryId) throw protocolError("invalid_history", "Pi v3 compaction firstKeptEntryId is not on its parent branch");
      push({ ...base, type: "compaction", summary: entry.summary, retainedTail: tail, tokensBefore: entry.tokensBefore, details: entry.details, usage: entry.usage, fromHook: entry.fromHook === true });
    }
    importedEntries += 1;
  }
  for (const entry of parsed.entries) if (!["message", "custom", "custom_message", "branch_summary", "compaction"].includes(entry.type)) omittedEntries += 1;

  const latest = (type) => [...activeChain].reverse().find((entry) => entry.type === type);
  const latestModel = latest("model_change");
  const latestThinking = latest("thinking_level_change");
  const latestTools = latest("active_tools_change");
  const latestInfo = latest("session_info");
  const labels = new Map();
  for (const entry of parsed.entries) {
    if (entry.type !== "label") continue;
    const target = resolveRetained(entry.targetId);
    if (target === null) continue;
    if (entry.label) labels.set(target, entry.label);
    else labels.delete(target);
  }
  if (latestInfo?.name) push({ kind: "value", op: "set", namespace: "pi.session.name", key: "", value: latestInfo.name });
  for (const [target, label] of labels) push({ kind: "value", op: "set", namespace: "pi.entry.label", key: target, value: label });
  const tip = parsed.entries.length ? resolveRetained(parsed.entries.at(-1).id) : null;
  push({ kind: "value", op: "set", namespace: "pi.branch.tip", key: "main", value: tip });
  if (latestModel && typeof latestModel.provider === "string" && typeof latestModel.modelId === "string") {
    push({ kind: "value", op: "set", namespace: "pi.lane.config", key: "main", value: {
      model: { provider: latestModel.provider, modelId: latestModel.modelId },
      ...(latestThinking?.thinkingLevel ? { thinkingLevel: latestThinking.thinkingLevel } : {}),
      activeToolNames: Array.isArray(latestTools?.activeToolNames) ? latestTools.activeToolNames : [],
    } });
  }
  push({ kind: "value", op: "set", namespace: "pi.lane.state", key: "main", value: { currentOperationId: null, lastOperationId: null, inbox: [] } });
  const report = {
    schema_version: "tspi-history-import/1",
    mode: "v3_to_v4",
    lossless: omittedEntries === 0,
    source_session_id: parsed.header.id,
    source_sha256: sourceSha256 || sha256(parsed.sourceContent),
    imported_entries: importedEntries,
    omitted_entry_count: omittedEntries,
    omitted: omittedEntries ? ["legacy presentation/configuration entries are represented as v4 values"] : [],
  };
  push({ kind: "entry", id: `tspi-import-${sha256(report.source_sha256).slice(0, 20)}`, parentId: tip, timestamp: createdAt, type: "custom", customType: "tspi.history-import", data: report });
  const header = { kind: "header", v: 4, id: sessionId, storageVersion: 1, createdAt, cwd: parsed.header.cwd, nextSeq: writes.length + 1 };
  return { content: `${JSON.stringify(header)}\n${writes.map((write) => JSON.stringify(write)).join("\n")}\n`, session_id: sessionId, report: { ...report, destination_format: "pi-harness-v4" } };
}

export async function resolveHistoryWorkspace({ installRoot, workspaceRoot, workspaceId }) {
  if (typeof installRoot !== "string" || !installRoot.startsWith("/")) throw new TypeError("installRoot must be absolute");
  if (!WORKSPACE_ID.test(workspaceId || "")) throw protocolError("invalid_workspace", "workspace_id is invalid");
  let container = workspaceRoot;
  if (!container) {
    try { container = JSON.parse(await readFile(join(installRoot, ".pi/tspi/workspace-root.json"), "utf8")).workspace_root; } catch (error) { if (error.code !== "ENOENT") throw error; }
  }
  container ||= join(installRoot, "workspaces");
  if (!container.startsWith("/")) throw protocolError("invalid_workspace", "Workspace container must be absolute");
  const root = join(await realpath(container), workspaceId);
  await physicalPath(root);
  const identity = JSON.parse(await readFile(join(root, "workspace.json"), "utf8"));
  if (identity.schema_version !== "research-workspace/1") throw protocolError("invalid_workspace", "Workspace must be initialized before importing history");
  return root;
}

export async function listLegacyHistory(options) {
  const cwd = await resolveHistoryWorkspace(options);
  const sessions = [];
  const roots = [];
  // The installation root is the v4 owner. Workspace .pi/sessions is a
  // read-only compatibility source and is never opened by the Harness.
  if (options.includeCanonical !== false) roots.push({ root: canonicalSessionsRoot(options.installRoot), source: "canonical" });
  if (options.includeWorkspace !== false) roots.push({ root: workspaceSessionsRoot(cwd), source: "workspace" });
  for (const { root, source } of roots) {
    for (const path of await historyPaths(root)) {
      let content;
      let header;
      try {
        content = await readFile(path, "utf8");
        header = JSON.parse(content.slice(0, content.indexOf("\n")));
      } catch { continue; }
      if (header?.cwd !== cwd || typeof header.id !== "string") continue;
      const version = header.kind === "header" ? header.v : header.version;
      const info = await lstat(path);
      let importable = false;
      let incompatibility = null;
      try {
        const parsed = parseHistory(content, cwd);
        if (parsed.version === 3 && source === "workspace") {
          convertLegacyV3ToV4(parsed, { sessionId: importedId(sha256(content)), sourceSha256: sha256(content) });
        } else {
          // v4 export remains available for old installations and explicit
          // migration tooling. It is never a writable session in this list.
          convertHistory(parsed, { sessionId: importedId(sha256(content)), timestamp: new Date(0).toISOString() });
        }
        importable = true;
      } catch (error) { incompatibility = { code: error.code || "invalid_history", message: error.message }; }
      const key = `${header.id}:${source}`;
      sessions.push({
        workspace_id: options.workspaceId,
        session_id: header.id,
        cwd,
        session_file: path,
        source_path: path,
        source_sha256: sha256(content),
        version,
        format: source === "workspace" ? `pi-v${version}-legacy` : `legacy-v${version}`,
        source_kind: source,
        read_only: true,
        online: false,
        is_streaming: false,
        turn_id: null,
        created_at: header.timestamp || new Date(header.createdAt || 0).toISOString(),
        updated_at: info.mtime.toISOString(),
        importable,
        incompatibility,
        _history_key: key,
      });
    }
  }
  return sessions.sort((a, b) => b.updated_at.localeCompare(a.updated_at)).map(({ _history_key: _ignored, ...session }) => session);
}

/** Return a parsed, read-only workspace history for Host session/read. */
export async function readLegacyHistory(options) {
  const cwd = await resolveHistoryWorkspace(options);
  const sessions = await listLegacyHistory({ ...options, includeCanonical: options.includeCanonical ?? true });
  const selected = sessions.find((item) => item.session_id === options.sessionId && item.cwd === cwd);
  if (!selected) return null;
  const content = await readFile(selected.source_path, "utf8");
  const parsed = parseHistory(content, cwd);
  const entries = parsed.version === 3 ? parsed.entries : parsed.entries;
  const indexed = new Map(entries.filter((entry) => typeof entry.id === "string").map((entry) => [entry.id, entry]));
  const branch = [];
  const seen = new Set();
  let cursor = parsed.version === 3 ? entries.at(-1) : entries.at(-1);
  while (cursor && !seen.has(cursor.id)) {
    seen.add(cursor.id);
    branch.unshift(cursor);
    cursor = indexed.get(cursor.parentId);
  }
  const messages = branch.filter((entry) => entry.type === "message")
    .map((entry) => ({ ...(entry.message || {}), id: entry.id }));
  const model = [...branch].reverse().find((entry) => entry.type === "model_change");
  return {
    session: selected,
    snapshot: {
      messages,
      online: false,
      read_only: true,
      can_prompt: false,
      is_streaming: false,
      turn_id: null,
      pending_messages: false,
      streaming_message: null,
      model: model ? { provider: model.provider, id: model.modelId } : null,
      importable: selected.importable,
      source_path: selected.source_path,
      compatibility_error: selected.incompatibility?.message || "Legacy Pi history is read-only; explicitly import it into the Harness first",
      receipts: [],
    },
    cursor: { sequence: 0 },
  };
}

export async function inspectLegacyHistory(options) {
  const cwd = await resolveHistoryWorkspace(options);
  const source = await validateLegacySource(options.installRoot, options.source, options.workspaceRoot);
  const content = await readFile(source, "utf8");
  const parsed = parseHistory(content, cwd);
  const sdkValidated = await validateWithPiSdk(parsed, options.sourceRoot);
  return { parsed, source, source_sha256: sha256(content), sdk_validated: sdkValidated, cwd };
}

export async function importLegacyHistory(options) {
  const inspected = await inspectLegacyHistory(options);
  const { parsed, source, source_sha256, sdk_validated, cwd } = inspected;
  const destinationId = importedId(source_sha256);
  const sourceIsWorkspaceV3 = parsed.version === 3 && isContained(workspaceSessionsRoot(cwd), source);
  // New migrations flow v3 workspace history into the installation-owned v4
  // repository. Keep the old v4->v3 export path for installations that used
  // the pre-Harness CLI, so an operator can still recover those files.
  const converted = sourceIsWorkspaceV3
    ? convertLegacyV3ToV4(parsed, { sessionId: destinationId, sourceSha256: source_sha256 })
    : convertHistory(parsed, { sessionId: destinationId, timestamp: new Date(parsed.version === 4 ? parsed.header.createdAt : Date.parse(parsed.header.timestamp)).toISOString() });
  const sessionsRoot = sourceIsWorkspaceV3 ? canonicalSessionsRoot(options.installRoot) : workspaceSessionsRoot(cwd);
  const reportsRoot = sourceIsWorkspaceV3 ? join(options.installRoot, ".pi", "app-server-host", "history-imports") : join(cwd, ".pi", "history-imports");
  const destinationDirectory = sourceIsWorkspaceV3 ? join(sessionsRoot, v4SessionDirectoryName(cwd)) : sessionsRoot;
  for (const path of [join(options.installRoot, ".pi"), sessionsRoot, destinationDirectory, reportsRoot]) {
    await mkdir(path, { recursive: true, mode: 0o700 });
    await physicalPath(path);
  }
  let target = sourceIsWorkspaceV3
    ? join(destinationDirectory, v4SessionFileName(Date.parse(parsed.header.timestamp), converted.session_id))
    : join(sessionsRoot, `import-${converted.session_id}.jsonl`);
  // IDs, not just filenames, define a Pi session. Never create two conflicting
  // native files for the same ID, and never replace a file resumed after import.
  let duplicate = false;
  for (const path of await historyPaths(sessionsRoot)) {
    const content = await readFile(path, "utf8");
    let header;
    try { header = JSON.parse(content.slice(0, content.indexOf("\n"))); } catch { continue; }
    if (header.id !== converted.session_id) continue;
    if (content !== converted.content && !(parsed.version === 4 && content.startsWith(converted.content))) throw protocolError("history_conflict", `A different native history already uses session ${converted.session_id}`);
    target = path;
    duplicate = true;
  }
  if (sha256(await readFile(source, "utf8")) !== source_sha256) throw protocolError("history_changed", "Legacy history changed during inspection; retry after its writer stops");
  const reportPath = join(reportsRoot, `${source_sha256}.json`);
  const report = { schema_version: "tspi-history-import/1", source_path: source, source_sha256, source_session_id: parsed.header.id, source_version: parsed.version, source_preserved: true, sdk_validated, destination_path: target, destination_session_id: converted.session_id, destination_format: sourceIsWorkspaceV3 ? "pi-harness-v4" : "pi-v3", destination_sha256: sha256(converted.content), ...converted.report };
  await writeAtomic(reportPath, { ...report, state: "prepared" });
  if (!duplicate) {
    try {
      await writeExclusive(target, converted.content);
    } catch (error) {
      if (error.code !== "EEXIST") throw error;
      const existing = await readFile(target, "utf8");
      if (existing !== converted.content) throw protocolError("history_conflict", `A different native history already uses session ${converted.session_id}`);
      duplicate = true;
    }
  }
  await writeAtomic(reportPath, { ...report, state: "imported" });
  return { ...report, state: duplicate ? "already_imported" : "imported", report_path: reportPath };
}

async function historyPaths(root, depth = 0) {
  if (depth > 2) return [];
  let entries;
  try { await physicalPath(root); entries = await readdir(root, { withFileTypes: true }); } catch (error) { if (error.code === "ENOENT") return []; throw error; }
  const result = [];
  for (const entry of entries) {
    if (entry.isFile() && entry.name.endsWith(".jsonl")) result.push(join(root, entry.name));
    else if (entry.isDirectory()) result.push(...await historyPaths(join(root, entry.name), depth + 1));
  }
  return result;
}
async function validateLegacySource(installRoot, source, workspaceRoot) {
  const roots = [canonicalSessionsRoot(installRoot)];
  if (typeof workspaceRoot === "string" && workspaceRoot.startsWith("/")) roots.push(resolve(workspaceRoot));
  try {
    const configured = JSON.parse(await readFile(join(installRoot, ".pi/tspi/workspace-root.json"), "utf8")).workspace_root;
    if (typeof configured === "string" && configured.startsWith("/")) roots.push(configured);
  } catch (error) { if (error.code !== "ENOENT") throw error; }
  if (typeof source !== "string" || !source.startsWith("/") || !source.endsWith(".jsonl")
    || !roots.some((root) => isContained(root, source))) {
    throw protocolError("invalid_history_path", "Source must be an explicit file in the installation's canonical v4 or configured workspace history directory");
  }
  await physicalPath(source);
  if (!(await lstat(source)).isFile()) throw protocolError("invalid_history_path", "Source must be a regular history file");
  return source;
}
async function physicalPath(path) {
  const info = await lstat(path);
  if (info.isSymbolicLink() || await realpath(path) !== path) throw protocolError("unsafe_path", "History paths must not contain symbolic links");
}
function sha256(value) { return createHash("sha256").update(value).digest("hex"); }
function importedId(digest) {
  const value = sha256(`tspi-history:${digest}`).slice(0, 32);
  return `${value.slice(0, 8)}-${value.slice(8, 12)}-5${value.slice(13, 16)}-a${value.slice(17, 20)}-${value.slice(20)}`;
}
async function writeExclusive(path, content) {
  const temporary = `${path}.${randomUUID()}.tmp`;
  try {
    await writeFile(temporary, content, { flag: "wx", mode: 0o600 });
    await link(temporary, path);
  } finally { await unlink(temporary).catch(() => {}); }
}
async function writeAtomic(path, value) {
  const temporary = `${path}.${randomUUID()}.tmp`;
  try {
    await writeFile(temporary, `${JSON.stringify(value, null, 2)}\n`, { flag: "wx", mode: 0o600 });
    await rename(temporary, path);
  } finally { await unlink(temporary).catch(() => {}); }
}

async function main() {
  const values = {};
  for (let index = 2; index < process.argv.length; index += 1) {
    const key = process.argv[index];
    if (key === "--import") values.import = true;
    else if (["--install-root", "--workspace-root", "--workspace-id", "--source", "--source-root"].includes(key)) values[key.slice(2)] = process.argv[++index];
    else throw new Error(`Unknown history option: ${key}`);
  }
  const options = { installRoot: values["install-root"], workspaceRoot: values["workspace-root"], workspaceId: values["workspace-id"], source: values.source, sourceRoot: values["source-root"] || process.env.TSPI_PI_SOURCE };
  if (!options.sourceRoot && options.installRoot) {
    const pin = JSON.parse(await readFile(join(PACKAGE_ROOT, "config/pi-source.json"), "utf8"));
    const candidate = join(options.installRoot, ".pi/runtime-cache/pi", pin.commit);
    try { await lstat(candidate); options.sourceRoot = candidate; } catch { /* Pure parser remains available for inventory. */ }
  }
  let result;
  if (values.import) {
    if (!options.source) throw new Error("--import requires one explicit --source");
    result = await importLegacyHistory(options);
  } else if (options.source) {
    const inspected = await inspectLegacyHistory(options);
    const { parsed, ...metadata } = inspected;
    let conversion;
    try { conversion = convertHistory(parsed, { sessionId: importedId(inspected.source_sha256), timestamp: new Date(parsed.version === 4 ? parsed.header.createdAt : Date.parse(parsed.header.timestamp)).toISOString() }); } catch (error) { conversion = { error: { code: error.code, message: error.message } }; }
    result = { schema_version: "tspi-history-export/1", ...metadata, source_version: parsed.version, header: parsed.header, entries: parsed.entries, conversion };
  } else result = { schema_version: "tspi-history-list/1", sessions: await listLegacyHistory(options) };
  process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) main().catch((error) => { process.stderr.write(`${error.code || "history_error"}: ${error.message}\n`); process.exitCode = 1; });
