import assert from "node:assert/strict";
import test from "node:test";
import { execFile, spawn } from "node:child_process";
import { once } from "node:events";
import { promisify } from "node:util";
import { mkdtemp, mkdir, writeFile, readFile, rm } from "node:fs/promises";
import { join, resolve } from "node:path";
import { startTspiHost } from "../../../apps/app-server/tspi-host.mjs";
import { connectHost } from "../../../apps/app-server/tspi-host-client.mjs";
import { TEST_ROOT as testRoot, managedPython } from "./test-environment.mjs";

const execute = promisify(execFile);
const source = process.env.TSPI_PI_SOURCE;
const tmux = process.env.TSPI_TMUX;
const python = managedPython();
const quote = (value) => `'${String(value).replaceAll("'", "'\\''")}'`;
async function eventually(read, predicate, milliseconds = 20000) {
  const deadline = Date.now() + milliseconds;
  let value;
  while (Date.now() < deadline) {
    value = await read();
    if (predicate(value)) return value;
    await new Promise((done) => setTimeout(done, 100));
  }
  throw new Error(`Condition timed out: ${JSON.stringify(value)}`);
}

test("ordinary Pi TUI and remote inputs share one persistent session", { skip: !source || !tmux, timeout: 60000 }, async () => {
  const root = await mkdtemp(join(testRoot, "pi-tui-"));
  const project = join(root, "ws", "ts_001");
  const other = join(root, "ws", "ts_002");
  const socketPath = join(root, "host.sock");
  const terminalSocket = join(root, "tmux.sock");
  let host;
  let client;
  let gateway;
  const mux = (...args) => execute(tmux, ["-S", terminalSocket, ...args], { timeout: 10000 });
  try {
    for (const path of [project, other]) {
      await execute(python, ["scripts/ts_workspace.py", "bootstrap", "--root", path], { env: { ...process.env, TS_AGENT_PYTHON: python, PYTHONDONTWRITEBYTECODE: "1" } });
      await mkdir(join(path, ".pi/sessions"), { recursive: true });
    }
    host = await startTspiHost({ socketPath, workspaceRoot: join(root, "ws"), stateRoot: join(root, "state"), monitorPollMs: 0 });
    const command = ["env", "PI_OFFLINE=1", "PI_TELEMETRY=0", `PI_CODING_AGENT_DIR=${join(root, "agent")}`,
      `TSPI_HOST_SOCKET=${socketPath}`, `TSPI_BRIDGE_TOKEN_FILE=${host.bridgeTokenFile}`, "TSPI_WORKSPACE_ID=ts_001", "TSPI_TERMINAL_SESSION=pi",
      `TS_AGENT_PYTHON=${python}`, `TS_WORKSPACE_ROOT=${project}`, `TS_AGENT_PACKAGE_ROOT=${process.cwd()}`,
      process.execPath, "--import", join(source, "packages/coding-agent/src/experimental/source-resolver.ts"),
      join(source, "packages/coding-agent/src/cli.ts"), "--session-dir", join(project, ".pi/sessions"), "--session-id", "test-native-session",
      "-ne", "-ns", "-nc", "-e", resolve("tests/node/native/ordinary-pi-provider.ts"), "-e", resolve("extensions/pi/bridge/index.ts"),
      ...["research", "review", "compute", "artifacts"].flatMap((name) => ["-e", resolve(`extensions/pi/${name}/index.ts`)]),
      "--provider", "tspi-fixture", "--model", "echo"];
    await mux("-f", "/dev/null", "new-session", "-d", "-s", "pi", "-c", project, "-x", "100", "-y", "30", `exec ${command.map(quote).join(" ")}`);
    client = await connectHost({ socketPath });
    const list = await eventually(() => client.request("session/list", { workspace_id: "ts_001" }), (value) => value.sessions?.some((item) => item.online));
    const sessionId = list.sessions.find((item) => item.online).session_id;
    const initialPane = (await mux("capture-pane", "-p", "-S", "-", "-t", "pi")).stdout;
    assert.doesNotMatch(initialPane, /DAG-based transition-state research|Theme · ts-theme|^Server:/m);
    assert.equal(sessionId, "test-native-session");
    const identity = { workspace_id: "ts_001", session_id: sessionId };
    await client.request("session/attach", identity);
    const request = { ...identity, request_id: "phone-request-1", client_message_id: "phone-1", text: "from-phone", mode: "auto" };
    assert.equal((await client.request("input/send", request)).accepted, true);
    await client.request("input/send", request);
    let state = await eventually(() => client.request("session/read", identity), (value) => !value.snapshot.is_streaming && value.snapshot.messages.some((m) => m.role === "assistant"));
    assert.equal(state.snapshot.messages.filter((m) => m.role === "user").length, 1);
    const pane = await mux("capture-pane", "-p", "-S", "-", "-t", "pi");
    assert.match(pane.stdout, /fixture reply: from-phone/);
    await mux("send-keys", "-t", "pi", "-l", "from-terminal");
    await mux("send-keys", "-t", "pi", "Enter");
    state = await eventually(() => client.request("session/read", identity), (value) => !value.snapshot.is_streaming && value.snapshot.messages.filter((m) => m.role === "assistant").length === 2);
    assert.equal(state.snapshot.messages.filter((m) => m.role === "user").length, 2);
    await assert.rejects(client.request("input/send", { ...request, workspace_id: "ts_002", client_message_id: "cross-project" }), /offline|workspace|present/i);
    client.close();
    await host.close();
    host = await startTspiHost({ socketPath, workspaceRoot: join(root, "ws"), stateRoot: join(root, "state"), monitorPollMs: 0 });
    client = await connectHost({ socketPath });
    await eventually(() => client.request("session/read", identity), (value) => value.session.online);
    await client.request("input/send", request);
    state = await client.request("session/read", identity);
    assert.equal(state.snapshot.messages.filter((m) => m.role === "user").length, 2);
    await mux("send-keys", "-t", "pi", "-l", "/settings");
    await mux("send-keys", "-t", "pi", "Enter");
    await eventually(() => mux("capture-pane", "-p", "-t", "pi"), (value) => /Settings|Auto.compact|Thinking|Theme/i.test(value.stdout));
    await mux("send-keys", "-t", "pi", "Escape");
    // Monitor must route a canonical ws_* identity to the registered directory
    // without a terminal client being attached and without creating another Pi.
    const monitor = async (...args) => JSON.parse((await execute(python,
      ["scripts/ts_monitor.py", ...args, "--root", project], { env: { ...process.env, TS_AGENT_PYTHON: python, PYTHONDONTWRITEBYTECODE: "1" } })).stdout);
    const header = JSON.parse(await readFile(join(project, "workspace.json"), "utf8"));
    assert.match(header.workspace_id, /^ws_/);
    await monitor("register", "--node-id", "node_1", "--intent-id", "calc_1",
      "--intent-digest", `sha256:${"a".repeat(64)}`, "--session-id", sessionId, "--notify-policy", "none");
    const runWorker = () => execute(process.execPath, ["apps/app-server/pi-monitor-worker.mjs", "--workspace-root", join(root, "ws"),
      "--host-socket", socketPath, "--state-root", join(root, "state"), "--once"], {
      timeout: 30000, env: { ...process.env, TS_AGENT_PYTHON: python, TSPI_PACKAGE_ROOT: process.cwd() },
    });
    await runWorker();
    state = await eventually(() => client.request("session/read", identity), (value) => !value.snapshot.is_streaming && value.snapshot.messages.filter((m) => m.role === "assistant").length === 3);
    assert.match(JSON.stringify(state.snapshot.messages.at(-1)), /compute monitor event/);
    assert.equal((await monitor("pending")).deliveries.length, 0);
    await runWorker();
    state = await client.request("session/read", identity);
    assert.equal(state.snapshot.messages.filter((m) => m.role === "user").length, 3);
    gateway = spawn(process.execPath, ["apps/app-server/tspi-browser-gateway.mjs", "--connect", `unix://${socketPath}`,
      "--workspace", project, "--session-id", sessionId, "--port", "0", "--auth-token", "test-browser-token"], { stdio: ["ignore", "pipe", "pipe"] });
    const [ready] = await once(gateway.stdout, "data");
    const address = String(ready).match(/http:\/\/127\.0\.0\.1:\d+/)?.[0];
    assert.ok(address, `Gateway did not announce readiness: ${ready}`);
    assert.equal((await fetch(`${address}/health`)).status, 401);
    const headers = { Authorization: "Bearer test-browser-token" };
    assert.equal((await fetch(`${address}/health`, { headers: { ...headers, Origin: "https://untrusted.example" } })).status, 403);
    const web = await (await fetch(`${address}/v1/session/${sessionId}/snapshot`, { headers })).json();
    assert.equal(web.session.session_id, sessionId);
    assert.equal(web.snapshot.messages.filter((m) => m.role === "user").length, 3);
    const replay = await (await fetch(`${address}/rpc`, { method: "POST", headers, body: JSON.stringify({ id: "web-replay", method: "input/send", params: request }) })).json();
    assert.equal(replay.result.accepted, true);
    const history = await readFile(state.session.session_file, "utf8");
    assert.equal(JSON.parse(history.split("\n")[0]).version, 3);
    assert.equal(JSON.parse(history.split("\n")[0]).cwd, project);
  } catch (error) {
    const pane = await mux("capture-pane", "-p", "-S", "-", "-t", "pi").catch(() => ({ stdout: "Pi terminal exited" }));
    error.message += `\nTerminal:\n${pane.stdout}`;
    throw error;
  } finally {
    if (gateway && gateway.exitCode === null) { const stopped = once(gateway, "exit"); gateway.kill("SIGTERM"); await stopped; }
    client?.close();
    await mux("kill-server").catch(() => {});
    await host?.close();
    await rm(root, { recursive: true, force: true });
  }
});
