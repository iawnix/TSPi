import assert from "node:assert/strict";
import { mkdir, mkdtemp, readFile, rm, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { spawn, spawnSync } from "node:child_process";
import test from "node:test";

const sourceRoot = process.env.TSPI_PI_SOURCE;

test("Host wrapper routes client mode through the remote-native Pi client", async () => {
  const wrapper = await readFile("apps/app-server/pi-app-server.mjs", "utf8");
  const client = await readFile("apps/app-server/pi-native-client.mjs", "utf8");
  assert.match(wrapper, /join\(packageRoot, "apps\/app-server\/pi-native-client\.mjs"\)/);
  assert.doesNotMatch(wrapper, /presentationPackage/);
  assert.match(client, /experimental\/client-runtime\.ts/);
  assert.match(client, /createInteractiveTui/);
  assert.doesNotMatch(client, /ExperimentalClientTui/);
});

test("native TTY client scopes session selection and creation to the workspace cwd", async () => {
  const client = await readFile("apps/app-server/pi-native-client.mjs", "utf8");
  const prepareStart = client.indexOf("async function prepareSession");
  const prepareEnd = client.indexOf("\nasync function changeModel", prepareStart);
  assert.ok(prepareStart >= 0);
  assert.ok(prepareEnd > prepareStart);
  const prepare = client.slice(prepareStart, prepareEnd);
  const newStart = client.indexOf("async function startNewSession");
  const newEnd = client.indexOf("\nasync function resumeSession", newStart);
  const resumeEnd = client.indexOf("\nfunction report", newEnd);
  assert.ok(newStart >= 0);
  assert.ok(newEnd > newStart);
  assert.ok(resumeEnd > newEnd);
  const newSession = client.slice(newStart, newEnd);
  const resume = client.slice(newEnd, resumeEnd);

  assert.match(client, /function sessionCreateOptions\(id\)/);
  assert.match(client, /function sessionMatchesCwd\(summary\)/);
  assert.match(client, /const cwd = process\.env\.TSPI_SESSION_CWD\?\.trim\(\);/);
  assert.match(client, /\{ cwd \}/);
  assert.match(client, /summary\.cwd === cwd/);
  assert.match(prepare, /item\.sessionId === command\.sessionId && sessionMatchesCwd\(item\)/);
  assert.match(prepare, /create\(sessionCreateOptions\(command\.sessionId\)/);
  assert.match(prepare, /\.filter\(sessionMatchesCwd\)/);
  assert.match(prepare, /create\(sessionCreateOptions\(\)/);
  assert.doesNotMatch(prepare, /management\.create\(\{\}/);
  assert.match(newSession, /management\.create\(sessionCreateOptions\(\)/);
  assert.doesNotMatch(newSession, /management\.create\(\{\}/);
  assert.match(resume, /const sessions = \(services\.directory\.state\.value\?\.sessions \|\| \[\]\)\.filter\(sessionMatchesCwd\)/);
});

async function startNativeServer(root, { workspaceRoot, python } = {}) {
  const child = spawn(process.execPath, [
    "apps/app-server/pi-app-server.mjs", "server", "--source-root", sourceRoot,
    "--directory", join(root, "server"), "--workspace", root, "--session-dir", join(root, "sessions"),
  ], {
    cwd: process.cwd(), env: {
      ...process.env,
      PI_EXPERIMENTAL: "1",
      PI_OFFLINE: "1",
      PI_CODING_AGENT_DIR: join(root, "agent"),
      ...(workspaceRoot === undefined ? {} : { TSPI_WORKSPACE_ROOT: workspaceRoot }),
      ...(python === undefined ? {} : { TS_AGENT_PYTHON: python }),
    },
    stdio: ["ignore", "pipe", "pipe"],
  });
  let output = "";
  let errors = "";
  child.stdout.setEncoding("utf8");
  child.stderr.setEncoding("utf8");
  child.stdout.on("data", (chunk) => { output += chunk; });
  child.stderr.on("data", (chunk) => { errors += chunk; });
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`native server did not start: ${output}${errors}`)), 15_000);
    child.stdout.on("data", () => {
      if (/^Server: [0-9a-f-]+\nSocket: .+\.sock/m.test(output)) {
        clearTimeout(timer);
        resolve();
      }
    });
    child.once("error", (error) => {
      clearTimeout(timer);
      reject(error);
    });
    child.once("exit", (code) => {
      if (code !== null && code !== 0) {
        clearTimeout(timer);
        reject(new Error(`native server exited ${code}: ${output}${errors}`));
      }
    });
  });
  return {
    child,
    serverId: output.match(/^Server: ([0-9a-f-]+)$/m)?.[1],
    socket: output.match(/^Socket: (.+)$/m)?.[1],
  };
}

async function stopNativeServer(child) {
  if (child.exitCode !== null || child.signalCode !== null) return;
  child.kill("SIGTERM");
  await Promise.race([
    new Promise((resolve) => child.once("exit", resolve)),
    new Promise((resolve) => setTimeout(resolve, 2_000)),
  ]);
  if (child.exitCode === null && child.signalCode === null) child.kill("SIGKILL");
}

async function runNativeClient(root, ...arguments_) {
  return await new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [
      "apps/app-server/pi-app-server.mjs", "client", "--source-root", sourceRoot, ...arguments_,
    ], {
      cwd: process.cwd(),
      env: { ...process.env, PI_EXPERIMENTAL: "1", PI_OFFLINE: "1", PI_CODING_AGENT_DIR: join(root, "agent") },
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (chunk) => { stdout += chunk; });
    child.stderr.on("data", (chunk) => { stderr += chunk; });
    child.once("error", reject);
    child.once("exit", (code) => code === 0 ? resolve({ stdout, stderr }) : reject(new Error(`native client exited ${code}: ${stderr}`)));
  });
}

async function startNativeGateway(root, socket, sessionId, workspaceRoot = root) {
  const child = spawn(process.execPath, [
    "apps/app-server/pi-app-server.mjs", "gateway", "--source-root", sourceRoot,
    "--workspace", workspaceRoot,
    "--connect", `unix://${socket}`, "--session-id", sessionId,
    "--port", "0", "--auth-token", "gateway-test-token",
  ], {
    cwd: process.cwd(),
    env: { ...process.env, PI_EXPERIMENTAL: "1", PI_OFFLINE: "1", PI_CODING_AGENT_DIR: join(root, "agent") },
    stdio: ["ignore", "pipe", "pipe"],
  });
  let output = "";
  let errors = "";
  child.stdout.setEncoding("utf8");
  child.stderr.setEncoding("utf8");
  child.stdout.on("data", (chunk) => { output += chunk; });
  child.stderr.on("data", (chunk) => { errors += chunk; });
  const address = await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`native gateway did not start: ${output}${errors}`)), 15_000);
    child.stdout.on("data", () => {
      const match = output.match(/^Gateway: (http:\/\/[^\n]+)$/m);
      if (match) {
        clearTimeout(timer);
        resolve(match[1]);
      }
    });
    child.once("error", (error) => {
      clearTimeout(timer);
      reject(error);
    });
  child.once("exit", (code) => {
    if (code !== null && code !== 0) {
      clearTimeout(timer);
        reject(new Error(`native gateway exited ${code}: ${output}${errors}`));
      }
    });
  });
  return { child, address };
}

test("native Pi app server rejects mode-incompatible arguments", { skip: !sourceRoot }, () => {
  const cases = [
    {
      args: ["server", "--source-root", sourceRoot, "--workspace", process.cwd(), "--connect", "unix:///tmp/pi.sock"],
      message: "The experimental server command does not support existing CLI options yet",
    },
    {
      args: ["client", "--source-root", sourceRoot, "--workspace", process.cwd()],
      message: "--workspace is not valid in client mode",
    },
  ];
  for (const fixture of cases) {
    const result = spawnSync(process.execPath, ["apps/app-server/pi-app-server.mjs", ...fixture.args], {
      cwd: process.cwd(),
      encoding: "utf8",
    });
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, new RegExp(fixture.message.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  }
  const gateway = spawnSync(process.execPath, ["apps/app-server/pi-app-server.mjs", "gateway", "--source-root", sourceRoot], {
    cwd: process.cwd(),
    encoding: "utf8",
  });
  assert.notEqual(gateway.status, 0);
  assert.match(gateway.stderr, /gateway requires --connect/);
});

test("native Pi app server starts from the pinned source entrypoint", { skip: !sourceRoot }, async () => {
  const root = await mkdtemp(join(tmpdir(), "tspi-native-server-"));
  await mkdir(join(root, "agent"), { recursive: true });
  await writeFile(join(root, "agent", "auth.json"), JSON.stringify({ anthropic: { type: "api_key", key: "test-key" } }), { mode: 0o600 });
  const child = spawn(process.execPath, [
    "apps/app-server/pi-app-server.mjs", "server", "--source-root", sourceRoot,
    "--directory", join(root, "server"), "--workspace", root, "--session-dir", join(root, "sessions"),
  ], {
    cwd: process.cwd(), env: { ...process.env, PI_EXPERIMENTAL: "1", PI_OFFLINE: "1", PI_CODING_AGENT_DIR: join(root, "agent") },
    stdio: ["ignore", "pipe", "pipe"],
  });
  let output = "";
  let serverClient;
  let services;
  let backgroundContext;
  child.stdout.setEncoding("utf8");
  child.stdout.on("data", (chunk) => { output += chunk; });
  try {
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error(`native server did not start: ${output}`)), 15_000);
      child.stdout.on("data", () => {
        if (/^Server: [0-9a-f-]+\nSocket: .+\.sock/m.test(output)) { clearTimeout(timer); resolve(); }
      });
      child.once("error", reject);
      child.once("exit", (code) => { if (code !== null && code !== 0) reject(new Error(`native server exited ${code}: ${output}`)); });
    });
    const socket = output.match(/^Socket: (.+)$/m)?.[1];
    assert.ok(socket);
    const fromSource = (relative) => import(pathToFileURL(join(sourceRoot, relative)).href);
    ({ BACKGROUND_CONTEXT: backgroundContext } = await fromSource("packages/chord/src/context/index.ts"));
    const { Client } = await fromSource("packages/client/src/index.ts");
    const { createUnixTransportFactory } = await fromSource("packages/client/src/unix.ts");
    const { SessionManagement } = await fromSource("packages/coding-agent/src/experimental/services/sessions.ts");
    const { createServerServiceBinding } = await fromSource("packages/coding-agent/test/experimental-service-binding.ts");
    const serverId = output.match(/^Server: ([0-9a-f-]+)$/m)?.[1];
    assert.ok(serverId);
    serverClient = await Client.connect({
      serverId,
      transportFactory: createUnixTransportFactory({ path: socket }),
    });
    services = createServerServiceBinding(serverClient, { services: [SessionManagement] });
    await services.ready(backgroundContext);
    const session = await services.use(SessionManagement).create({ id: "cli-attach" }, backgroundContext);
    const client = await new Promise((resolve, reject) => {
      const result = spawn(process.execPath, [
        "apps/app-server/pi-app-server.mjs", "client", "--source-root", sourceRoot,
        "--connect", `unix://${socket}`, "--session-id", session.sessionId,
      ], {
        cwd: process.cwd(),
        env: { ...process.env, PI_EXPERIMENTAL: "1", PI_OFFLINE: "1", PI_CODING_AGENT_DIR: join(root, "agent") },
        stdio: ["ignore", "pipe", "pipe"],
      });
      let stdout = "";
      let stderr = "";
      result.stdout.setEncoding("utf8");
      result.stderr.setEncoding("utf8");
      result.stdout.on("data", (chunk) => { stdout += chunk; });
      result.stderr.on("data", (chunk) => { stderr += chunk; });
      result.once("error", reject);
      result.once("exit", (code) => code === 0 ? resolve({ stdout, stderr }) : reject(new Error(`native client exited ${code}: ${stderr}`)));
    });
    assert.match(client.stdout, new RegExp(`^[0-9a-f-]+\\t${session.sessionId}\\tattached\\n$`));
  } finally {
    await services?.dispose(backgroundContext).catch(() => {});
    await serverClient?.dispose().catch(() => {});
    child.kill("SIGTERM");
    await Promise.race([
      new Promise((resolve) => child.once("exit", resolve)),
      new Promise((resolve) => setTimeout(resolve, 2_000)),
    ]);
    if (child.exitCode === null) child.kill("SIGKILL");
    await rm(root, { recursive: true, force: true });
  }
});

test("native Pi app server restores and reattaches a persisted session after restart", { skip: !sourceRoot }, async () => {
  const root = await mkdtemp(join(tmpdir(), "tspi-native-restart-"));
  await mkdir(join(root, "agent"), { recursive: true });
  await writeFile(join(root, "agent", "auth.json"), JSON.stringify({ anthropic: { type: "api_key", key: "test-key" } }), { mode: 0o600 });
  const fromSource = (relative) => import(pathToFileURL(join(sourceRoot, relative)).href);
  const { BACKGROUND_CONTEXT } = await fromSource("packages/chord/src/context/index.ts");
  const { Client } = await fromSource("packages/client/src/index.ts");
  const { createUnixTransportFactory } = await fromSource("packages/client/src/unix.ts");
  const { SessionManagement } = await fromSource("packages/coding-agent/src/experimental/services/sessions.ts");
  const { createServerServiceBinding } = await fromSource("packages/coding-agent/test/experimental-service-binding.ts");
  let first;
  let second;
  let client;
  let services;
  try {
    first = await startNativeServer(root);
    assert.ok(first.serverId);
    assert.ok(first.socket);
    client = await Client.connect({
      serverId: first.serverId,
      transportFactory: createUnixTransportFactory({ path: first.socket }),
    });
    services = createServerServiceBinding(client, { services: [SessionManagement] });
    await services.ready(BACKGROUND_CONTEXT);
    const created = await services.use(SessionManagement).create({ id: "restart-persisted" }, BACKGROUND_CONTEXT);
    await services.dispose(BACKGROUND_CONTEXT);
    services = undefined;
    await client.dispose();
    client = undefined;
    await stopNativeServer(first.child);

    second = await startNativeServer(root);
    assert.equal(second.serverId, first.serverId);
    assert.equal(second.socket, first.socket);
    const attached = await runNativeClient(
      root,
      "--connect", `unix://${second.socket}`,
      "--session-id", created.sessionId,
    );
    assert.match(attached.stdout, new RegExp(`^${second.serverId}\\t${created.sessionId}\\tattached\\n$`));
  } finally {
    await services?.dispose(BACKGROUND_CONTEXT).catch(() => {});
    await client?.dispose().catch(() => {});
    if (first) await stopNativeServer(first.child);
    if (second) await stopNativeServer(second.child);
    await rm(root, { recursive: true, force: true });
  }
});

test("native session-control gateway attaches the existing Host session", { skip: !sourceRoot }, async () => {
  const root = await mkdtemp(join(tmpdir(), "tspi-native-gateway-"));
  await mkdir(join(root, "agent"), { recursive: true });
  await writeFile(join(root, "agent", "auth.json"), JSON.stringify({ anthropic: { type: "api_key", key: "test-key" } }), { mode: 0o600 });
  const server = await startNativeServer(root);
  let serverClient;
  let services;
  let backgroundContext;
  let gateway;
  try {
    const fromSource = (relative) => import(pathToFileURL(join(sourceRoot, relative)).href);
    ({ BACKGROUND_CONTEXT: backgroundContext } = await fromSource("packages/chord/src/context/index.ts"));
    const { Client } = await fromSource("packages/client/src/index.ts");
    const { createUnixTransportFactory } = await fromSource("packages/client/src/unix.ts");
    const { SessionManagement } = await fromSource("packages/coding-agent/src/experimental/services/sessions.ts");
    const { createServerServiceBinding } = await fromSource("packages/coding-agent/test/experimental-service-binding.ts");
    serverClient = await Client.connect({
      serverId: server.serverId,
      transportFactory: createUnixTransportFactory({ path: server.socket }),
    });
    services = createServerServiceBinding(serverClient, { services: [SessionManagement] });
    await services.ready(backgroundContext);
    const session = await services.use(SessionManagement).create({ id: "gateway-attach" }, backgroundContext);

    gateway = await startNativeGateway(root, server.socket, session.sessionId);
    const headers = { Authorization: "Bearer gateway-test-token" };
    const health = await fetch(`${gateway.address}/health`, { headers });
    assert.equal(health.status, 200);
    assert.equal((await health.json()).session_id, session.sessionId);
    const snapshot = await fetch(`${gateway.address}/v1/session/${session.sessionId}/snapshot`, { headers });
    assert.equal(snapshot.status, 200);
    assert.equal((await snapshot.json()).snapshot.lane, "main");
  } finally {
    if (gateway) await stopNativeServer(gateway.child);
    await services?.dispose(backgroundContext).catch(() => {});
    await serverClient?.dispose().catch(() => {});
    await stopNativeServer(server.child);
    await rm(root, { recursive: true, force: true });
  }
});

test("native Pi app server exposes direct workspaces and binds session cwd", { skip: !sourceRoot }, async () => {
  const root = await mkdtemp(join(tmpdir(), "tspi-native-workspaces-"));
  const workspaceRoot = join(root, "workspaces");
  const projectA = join(workspaceRoot, "project-a");
  const projectB = join(workspaceRoot, "project-b");
  const legacyProject = join(workspaceRoot, "legacy-project");
  await mkdir(join(root, "agent"), { recursive: true });
  await mkdir(projectA, { recursive: true });
  await mkdir(projectB, { recursive: true });
  await mkdir(legacyProject, { recursive: true });
  const bootstrapPython = join(root, "bootstrap-python.mjs");
  await writeFile(bootstrapPython, `#!/usr/bin/env node
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
const workspace = process.argv.at(-1);
mkdirSync(workspace, { recursive: true, mode: 0o700 });
const workspaceId = "ws_" + "c".repeat(24);
mkdirSync(join(workspace, ".agents"), { recursive: true, mode: 0o700 });
writeFileSync(join(workspace, ".agents/workspace-identity.json"), JSON.stringify({
  schema_version: "ts-workspace-identity/1",
  workspace_id: workspaceId,
  created_at: "2026-09-17T00:00:00+00:00",
}));
writeFileSync(join(workspace, "workspace.json"), JSON.stringify({
  schema_version: "research-workspace/1",
  workspace_id: workspaceId,
  kernel_protocol: "research-map/1",
  created_at: "2026-09-17T00:00:00+00:00",
}));
writeFileSync(join(workspace, "research_map.json"), JSON.stringify({
  schema_version: "research-map/1",
  map_id: workspaceId,
  title: "Native workspace",
  created_at: "2026-09-17T00:00:00+00:00",
  revision: 0,
  phases: [], claims: [], nodes: [], findings: [], gates: [],
  claim_relations: [], focus_claim_ids: [], focus_node_ids: [], metadata: {},
}));
writeFileSync(join(workspace, "transactions.jsonl"), "");
for (const directory of ["nodes", "operations", "scratch", "inputs"]) mkdirSync(join(workspace, directory));
`, { mode: 0o700 });
  await writeFile(join(root, "agent", "auth.json"), JSON.stringify({ anthropic: { type: "api_key", key: "test-key" } }), { mode: 0o600 });
  for (const [directory, workspaceId] of [[projectA, "ws_aaaaaaaaaaaaaaaaaaaaaaaa"], [projectB, "ws_bbbbbbbbbbbbbbbbbbbbbbbb"]]) {
    await mkdir(join(directory, ".agents"), { recursive: true });
    await writeFile(join(directory, ".agents/workspace-identity.json"), JSON.stringify({
      schema_version: "ts-workspace-identity/1",
      workspace_id: workspaceId,
      created_at: "2026-09-17T00:00:00+00:00",
    }));
    await writeFile(join(directory, "workspace.json"), JSON.stringify({
      schema_version: "research-workspace/1",
      workspace_id: workspaceId,
      kernel_protocol: "research-map/1",
      created_at: "2026-09-17T00:00:00+00:00",
    }));
    await writeFile(join(directory, "research_map.json"), JSON.stringify({
      schema_version: "research-map/1",
      map_id: workspaceId,
      title: directory.split("/").at(-1),
      created_at: "2026-09-17T00:00:00+00:00",
      revision: 0,
      phases: [], claims: [], nodes: [], findings: [], gates: [],
      claim_relations: [], focus_claim_ids: [], focus_node_ids: [], metadata: {},
    }));
    await writeFile(join(directory, "transactions.jsonl"), "");
    for (const name of ["nodes", "operations", "scratch", "inputs"]) await mkdir(join(directory, name));
  }
  await writeFile(join(legacyProject, "workspace.json"), JSON.stringify({ schema_version: "ts-workspace/6" }));
  await mkdir(join(projectA, "nested"));
  await symlink(projectA, join(workspaceRoot, "project-a-alias"));
  const server = await startNativeServer(root, { workspaceRoot, python: bootstrapPython });
  let serverClient;
  let services;
  let backgroundContext;
  try {
    const fromSource = (relative) => import(pathToFileURL(join(sourceRoot, relative)).href);
    ({ BACKGROUND_CONTEXT: backgroundContext } = await fromSource("packages/chord/src/context/index.ts"));
    const { Client } = await fromSource("packages/client/src/index.ts");
    const { createUnixTransportFactory } = await fromSource("packages/client/src/unix.ts");
    const { SessionManagement, WorkspaceDirectory } = await fromSource("packages/coding-agent/src/experimental/services/sessions.ts");
    const { createServerServiceBinding } = await fromSource("packages/coding-agent/test/experimental-service-binding.ts");
    serverClient = await Client.connect({
      serverId: server.serverId,
      transportFactory: createUnixTransportFactory({ path: server.socket }),
    });
    services = createServerServiceBinding(serverClient, { services: [SessionManagement, WorkspaceDirectory] });
    await services.ready(backgroundContext);

    const workspaces = await services.use(WorkspaceDirectory).list(backgroundContext);
    assert.deepEqual(workspaces, [
      { workspaceId: "project-a", name: "project-a", root: projectA },
      { workspaceId: "project-b", name: "project-b", root: projectB },
    ]);

    const projectC = join(workspaceRoot, "project-c");
    const createdWorkspace = await services.use(WorkspaceDirectory).create("project-c", backgroundContext);
    assert.deepEqual(createdWorkspace, { workspaceId: "project-c", name: "project-c", root: projectC });
    assert.equal(JSON.parse(await readFile(join(projectC, "workspace.json"))).schema_version, "research-workspace/1");
    await assert.rejects(services.use(WorkspaceDirectory).create("../outside", backgroundContext));

    const created = await services.use(SessionManagement).create({ cwd: projectA }, backgroundContext);
    assert.equal(created.cwd, projectA);
    const workspaceSession = await services.use(SessionManagement).create({ workspaceId: "project-c" }, backgroundContext);
    assert.equal(workspaceSession.cwd, projectC);
    await assert.rejects(services.use(SessionManagement).create({ cwd: workspaceRoot }, backgroundContext));
    await assert.rejects(services.use(SessionManagement).create({ cwd: join(projectA, "nested") }, backgroundContext));
    await assert.rejects(services.use(SessionManagement).create({ cwd: join(workspaceRoot, "project-a-alias") }, backgroundContext));
    await assert.rejects(
      services.use(SessionManagement).create({ cwd: legacyProject }, backgroundContext),
      /Session cwd is not a supported TSPi workspace/,
    );
  } finally {
    await services?.dispose(backgroundContext).catch(() => {});
    await serverClient?.dispose().catch(() => {});
    await stopNativeServer(server.child);
    await rm(root, { recursive: true, force: true });
  }
});
