import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtemp, mkdir, writeFile, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import { createInterface } from "node:readline";
import { createServer } from "node:net";
import { once } from "node:events";
import test from "node:test";
import { SettingsManager, SessionManager } from "@earendil-works/pi-coding-agent";
import { sessionSettings } from "../extensions/ts-phone-bridge/runtime.mjs";

const runtimePath = resolve("extensions/ts-phone-bridge/runtime.mjs");

async function fixture() {
  const root = await mkdtemp(resolve(tmpdir(), "tspi-model-runtime-"));
  const agent = resolve(root, "agent");
  const workspace = resolve(root, "workspace");
  await mkdir(agent); await mkdir(workspace);
  const settings = { defaultProvider: "fixture", defaultModel: "first", defaultThinkingLevel: "off" };
  await writeFile(resolve(agent, "settings.json"), JSON.stringify(settings));
  await writeFile(resolve(agent, "models.json"), JSON.stringify({ providers: { fixture: {
    baseUrl: "http://127.0.0.1:9/v1", api: "openai-completions", apiKey: "not-a-real-key",
    models: ["first", "second"].map((id) => ({ id, name: id, reasoning: false, input: ["text"],
      contextWindow: 16000, maxTokens: 2000, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 } })),
  } } }));
  return { root, agent, workspace };
}

test("session preferences preserve Pi merge rules without changing global or project files", async () => {
  const f = await fixture();
  await mkdir(resolve(f.workspace, ".pi"));
  await writeFile(resolve(f.workspace, ".pi/settings.json"), JSON.stringify({defaultThinkingLevel: "low"}));
  const source = SettingsManager.create(f.workspace, f.agent);
  const settings = sessionSettings(source);
  assert.equal(settings.getDefaultThinkingLevel(), "low");
  settings.setDefaultModelAndProvider("fixture", "second");
  await settings.flush();
  assert.equal(settings.getDefaultModel(), "second");
  assert.equal(JSON.parse(await readFile(resolve(f.agent, "settings.json"), "utf8")).defaultModel, "first");
  assert.equal(JSON.parse(await readFile(resolve(f.workspace, ".pi/settings.json"), "utf8")).defaultModel, undefined);
});

test("official RPC restores exact history and switches models without changing another session", async () => {
  const f = await fixture();
  const sessionDir = resolve(f.workspace, ".pi/sessions");
  const previous = SessionManager.create(f.workspace, sessionDir, {id: "session_1"});
  previous.appendModelChange("fixture", "second");
  previous.appendMessage({role: "assistant", content: [{type: "text", text: "existing answer"}],
    api: "openai-completions", provider: "fixture", model: "second", timestamp: Date.now(),
    stopReason: "stop", usage: {input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0,
      cost: {input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0}}});
  const settingsBefore = await readFile(resolve(f.agent, "settings.json"), "utf8");
  const secretFile = resolve(f.root, "bridge.secret");
  const socketPath = resolve(f.root, "bridge.sock");
  await writeFile(secretFile, "fixture".repeat(8), {mode: 0o600});
  const snapshots = [];
  const bridge = createServer((socket) => {
    socket.on("error", (error) => { if (error.code !== "ECONNRESET") throw error; });
    createInterface({input: socket}).on("error", (error) => {
      if (error.code !== "ECONNRESET") throw error;
    }).on("line", (line) => {
      const record = JSON.parse(line);
      if (record.type === "bridge.register") {
        socket.write(JSON.stringify({protocolVersion: record.protocolVersion, type: "bridge.registered",
          workspaceId: record.workspaceId, sessionId: record.sessionId, instanceEpoch: record.instanceEpoch}) + "\n");
      } else if (record.type === "session.snapshot") snapshots.push(record.snapshot);
    });
  });
  await new Promise((done) => bridge.listen(socketPath, done));
  const manifest = JSON.parse(await readFile(resolve("package.json"), "utf8"));
  const resources = [...manifest.pi.extensions, "extensions/ts-phone-bridge/index.ts"]
    .flatMap((path) => ["-e", resolve(path)]);
  const child = spawn(process.execPath, [runtimePath, "--mode", "rpc", "--session-id", "session_1",
    "--session-dir", sessionDir, "--model", "fixture/first", ...resources,
    "--skill", resolve("skills/transition-state-workflow"), "--theme", resolve("themes/ts-theme.json")], {cwd: f.workspace,
    env: {...process.env, PI_CODING_AGENT_DIR: f.agent, TS_PHONE_WORKER: "1", TS_SESSION_ID: "session_1",
      TS_PHONE_MODE: "bridge", TS_PHONE_WORKSPACE_ID: "ts_fixture", TS_PHONE_ACCESS_MODE: "controller",
      TS_PHONE_BRIDGE_SOCKET: socketPath, TS_PHONE_BRIDGE_SECRET_FILE: secretFile},
    stdio: ["pipe", "pipe", "pipe"]});
  const exit = once(child, "exit");
  const pending = new Map();
  let diagnostic = "";
  const extensionErrors = [];
  child.stdin.on("error", (error) => { diagnostic += `stdin: ${error.code}\n`; });
  child.stderr.on("error", (error) => { diagnostic += `stderr: ${error.code}\n`; });
  child.stderr.on("data", (chunk) => { diagnostic += chunk; });
  createInterface({input: child.stdout}).on("error", (error) => {
    diagnostic += `stdout: ${error.code}\n`;
  }).on("line", (line) => {
    let value; try { value = JSON.parse(line); } catch { return; }
    if (value.type === "extension_error") extensionErrors.push(value);
    if (value.type !== "response") return;
    pending.get(value.id)?.(value);
  });
  let sequence = 0;
  const request = (command) => new Promise((resolveRequest, reject) => {
    const id = `test-${++sequence}`;
    const timer = setTimeout(() => reject(new Error(`RPC timed out: ${diagnostic}`)), 15000);
    pending.set(id, (value) => { clearTimeout(timer); pending.delete(id); resolveRequest(value); });
    child.stdin.write(JSON.stringify({id, ...command}) + "\n");
  });
  try {
    const before = await request({type: "get_state"});
    assert.equal(before.success, true, diagnostic);
    assert.equal(before.data.sessionId, "session_1");
    assert.equal(before.data.model.id, "second");
    const commands = (await request({type: "get_commands"})).data.commands;
    assert.ok(commands.some((command) => command.name === "ts-runs"));
    assert.ok(commands.some((command) => command.name === "ts-check"));
    const changed = await request({type: "set_model", provider: "fixture", modelId: "first"});
    assert.equal(changed.success, true);
    assert.equal(changed.data.id, "first");
    assert.equal((await request({type: "get_messages"})).data.messages[0].content[0].text, "existing answer");
    const rejected = await request({type: "set_model", provider: "fixture", modelId: "missing"});
    assert.equal(rejected.success, false);
    assert.equal((await request({type: "get_state"})).data.model.id, "first");
    assert.equal(await readFile(resolve(f.agent, "settings.json"), "utf8"), settingsBefore);
    const reopened = SessionManager.open(previous.getSessionFile(), sessionDir);
    assert.equal(reopened.getBranch().filter((entry) => entry.type === "model_change").at(-1).modelId, "first");
    assert.equal((await SessionManager.list(f.workspace, sessionDir)).length, 1);
    for (let attempt = 0; snapshots.length === 0 && attempt < 50; attempt++) {
      await new Promise((done) => setTimeout(done, 20));
    }
    assert.equal(snapshots.at(-1)?.modelControl, true);
    assert.equal(snapshots.at(-1)?.model, "fixture/first");
    assert.deepEqual(extensionErrors, []);
  } finally {
    child.stdin.end();
    const stop = setTimeout(() => child.kill("SIGKILL"), 3000);
    await exit;
    clearTimeout(stop);
    await new Promise((done) => bridge.close(done));
  }
});
