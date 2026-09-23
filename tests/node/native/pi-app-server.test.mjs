import assert from "node:assert/strict";
import { access, mkdir, mkdtemp, readFile, readdir, rename, rm, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { basename, join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { spawn, spawnSync } from "node:child_process";
import test from "node:test";

const sourceRoot = process.env.TSPI_PI_SOURCE;
const testRoot = process.env.TSPI_TEST_ROOT || tmpdir();
const nativeRuntimeRoot = process.env.TSPI_TEST_RUNTIME_ROOT;
const nativeRuntimeDirectories = new Map();

function nativeServerDirectory(root) {
  if (!nativeRuntimeRoot) return join(root, "server");
  let directory = nativeRuntimeDirectories.get(root);
  if (!directory) {
    directory = join(nativeRuntimeRoot, `n${process.pid.toString(36)}-${nativeRuntimeDirectories.size}`);
    nativeRuntimeDirectories.set(root, directory);
  }
  return directory;
}

async function cleanupNativeRuntime(root) {
  const directory = nativeRuntimeDirectories.get(root);
  if (!directory) return;
  nativeRuntimeDirectories.delete(root);
  await rm(directory, { recursive: true, force: true });
}

async function waitForExit(fixture, label, timeoutMs = 10_000) {
  let timeout;
  try {
    return await Promise.race([
      fixture.exit,
      new Promise((_, reject) => {
        timeout = setTimeout(() => reject(new Error(`${label}: ${fixture.stderr()}`)), timeoutMs);
      }),
    ]);
  } finally {
    clearTimeout(timeout);
  }
}

async function startOrdinaryHost(root) {
  const runtime = join(root, "runtime");
  const workspace = join(root, "workspace");
  const state = join(root, "state");
  const serverId = "11111111-1111-4111-8111-111111111111";
  const socket = join(runtime, `${serverId}.sock`);
  await Promise.all([mkdir(runtime), mkdir(workspace), mkdir(state)]);
  const child = spawn(process.execPath, [
    "apps/app-server/pi-app-server.mjs", "server",
    "--workspace", workspace,
    "--directory", runtime,
    "--server-id", serverId,
    "--state-root", state,
  ], {
    cwd: process.cwd(),
    env: {
      ...process.env,
      TSPI_HOST_BACKEND: "ordinary",
      TSPI_INSTALL_ROOT: root,
      TSPI_MONITOR_DISABLED: "1",
      TSPI_PACKAGE_ROOT: process.cwd(),
      TSPI_WORKSPACE_ROOT: workspace,
    },
    stdio: ["ignore", "ignore", "pipe"],
  });
  let stderr = "";
  child.stderr.setEncoding("utf8");
  child.stderr.on("data", (chunk) => { stderr += chunk; });
  const exit = new Promise((resolve, reject) => {
    child.once("error", reject);
    child.once("exit", (code, signal) => resolve({ code, signal }));
  });
  const fixture = { child, exit, runtime, socket, stderr: () => stderr };
  try {
    const deadline = Date.now() + 10_000;
    while (Date.now() < deadline) {
      try {
        await access(socket);
        return fixture;
      } catch (error) {
        if (error.code !== "ENOENT") throw error;
      }
      if (child.exitCode !== null || child.signalCode !== null) {
        throw new Error(`Host exited before creating its socket: ${stderr}`);
      }
      await new Promise((resolveWait) => setTimeout(resolveWait, 10));
    }
    throw new Error(`Host did not create its socket: ${stderr}`);
  } catch (error) {
    await stopTestHost(fixture);
    throw error;
  }
}

async function stopTestHost(fixture) {
  if (fixture?.child.exitCode === null && fixture.child.signalCode === null) {
    fixture.child.kill("SIGKILL");
    await fixture.exit.catch(() => {});
  }
}

test("Host removes its socket and exits cleanly on SIGTERM", async () => {
  const root = await mkdtemp(join(testRoot, "host-shutdown-"));
  let fixture;
  try {
    fixture = await startOrdinaryHost(root);
    fixture.child.kill("SIGTERM");
    assert.deepEqual(await waitForExit(fixture, "Host did not stop after SIGTERM"), { code: 0, signal: null });
    await assert.rejects(access(fixture.socket), { code: "ENOENT" });
    assert.equal(fixture.stderr(), "");
  } finally {
    await stopTestHost(fixture);
    await rm(root, { recursive: true, force: true });
  }
});

test("Host reports a shutdown cleanup failure without an unhandled rejection", async () => {
  const root = await mkdtemp(join(testRoot, "host-shutdown-failure-"));
  let fixture;
  try {
    fixture = await startOrdinaryHost(root);
    const displacedRuntime = `${fixture.runtime}.displaced`;
    await rename(fixture.runtime, displacedRuntime);
    await writeFile(fixture.runtime, "not a directory\n");
    fixture.child.kill("SIGTERM");
    assert.deepEqual(await waitForExit(fixture, "Host did not stop after cleanup failure"), { code: 1, signal: null });
    assert.match(fixture.stderr(), /TSPi Host shutdown failed after SIGTERM:.*ENOTDIR/s);
    assert.doesNotMatch(fixture.stderr(), /unhandled.*rejection/i);
    await access(join(displacedRuntime, basename(fixture.socket)));
  } finally {
    await stopTestHost(fixture);
    await rm(root, { recursive: true, force: true });
  }
});

test("Host handles SIGTERM while the managed Pi backend is starting", { skip: !sourceRoot }, async () => {
  // Pi derives several Unix socket names below this root; keep it short enough
  // for the platform AF_UNIX path limit.
  const root = await mkdtemp(join(testRoot, "hs-"));
  const runtime = nativeServerDirectory(root);
  const workspace = join(root, "workspace");
  const state = join(root, "state");
  const agent = join(root, "agent");
  const serverId = "22222222-2222-4222-8222-222222222222";
  const socket = join(runtime, `${serverId}.sock`);
  await Promise.all([mkdir(runtime), mkdir(workspace), mkdir(state), mkdir(agent)]);
  const child = spawn(process.execPath, [
    "apps/app-server/pi-app-server.mjs", "server",
    "--source-root", sourceRoot,
    "--workspace", workspace,
    "--directory", runtime,
    "--server-id", serverId,
    "--state-root", state,
  ], {
    cwd: process.cwd(),
    env: {
      ...process.env,
      PI_CODING_AGENT_DIR: agent,
      TSPI_HOST_BACKEND: "harness",
      TSPI_INSTALL_ROOT: root,
      TSPI_MONITOR_DISABLED: "1",
      TSPI_PACKAGE_ROOT: process.cwd(),
      TSPI_PI_SOURCE: sourceRoot,
      TSPI_WORKSPACE_ROOT: workspace,
    },
    stdio: ["ignore", "ignore", "pipe"],
  });
  let stderr = "";
  child.stderr.setEncoding("utf8");
  child.stderr.on("data", (chunk) => { stderr += chunk; });
  const exit = new Promise((resolve, reject) => {
    child.once("error", reject);
    child.once("exit", (code, signal) => resolve({ code, signal }));
  });
  const fixture = { child, exit, stderr: () => stderr };
  try {
    const deadline = Date.now() + 10_000;
    let observedStartup = false;
    while (Date.now() < deadline) {
      try {
        await access(join(runtime, "pi"));
        try {
          await access(socket);
        } catch (error) {
          if (error.code !== "ENOENT") throw error;
          observedStartup = true;
          break;
        }
      } catch (error) {
        if (error.code !== "ENOENT") throw error;
      }
      if (child.exitCode !== null || child.signalCode !== null) {
        throw new Error(`Host exited during startup: ${stderr}`);
      }
      await new Promise((resolveWait) => setTimeout(resolveWait, 1));
    }
    assert.equal(observedStartup, true, "did not observe the managed backend startup window");
    child.kill("SIGTERM");
    const result = await waitForExit(fixture, "Host did not stop after startup signal", 30_000);
    assert.deepEqual(result, { code: 0, signal: null }, stderr);
    const cleanupDeadline = Date.now() + 5_000;
    let residualSockets = [];
    do {
      residualSockets = (await readdir(runtime, { recursive: true })).filter((name) => name.endsWith(".sock"));
      if (residualSockets.length === 0) break;
      await new Promise((resolveWait) => setTimeout(resolveWait, 25));
    } while (Date.now() < cleanupDeadline);
    assert.deepEqual(residualSockets, []);
    assert.equal(stderr, "");
  } finally {
    if (child.exitCode === null && child.signalCode === null) {
      child.kill("SIGKILL");
      await exit.catch(() => {});
    }
    await cleanupNativeRuntime(root);
    await rm(root, { recursive: true, force: true });
  }
});

test("Host wrapper routes client mode through Pi's native client without injecting a presentation facet", async () => {
  const wrapper = await readFile("apps/app-server/pi-experimental-app-server.mjs", "utf8");
  const client = await readFile("apps/app-server/pi-native-client.mjs", "utf8");
  assert.match(wrapper, /join\(packageRoot, "apps\/app-server\/pi-native-client\.mjs"\)/);
  assert.match(wrapper, /const piForwarded = forwarded;/);
  assert.match(wrapper, /\[join\(packageRoot, "apps\/app-server\/pi-native-client\.mjs"\), \.\.\.piForwarded\]/);
  assert.doesNotMatch(wrapper, /extensions\/pi\/tui-package/);
  assert.doesNotMatch(wrapper, /TSPI_PRESENTATION_RENDERERS_ONLY/);
  assert.doesNotMatch(wrapper, /injectPresentationPackage/);
  assert.match(client, /experimental\/client-tui\.ts/);
  assert.match(client, /runClientTui/);
  assert.match(client, /parsed\.command\.pluginPackages === undefined/);
  assert.match(client, /connect\?\.transport !== "radius"/);
  assert.match(client, /pluginPackages: \[\]/);
  assert.doesNotMatch(client, /class RemoteTranscript/);
  assert.doesNotMatch(client, /CombinedAutocompleteProvider/);
});

test("native client binds the interactive process to the workspace cwd", { skip: !sourceRoot }, async () => {
  const wrapper = await readFile("apps/app-server/pi-experimental-app-server.mjs", "utf8");
  const client = await readFile("apps/app-server/pi-native-client.mjs", "utf8");
  assert.match(client, /const cwd = process\.env\.TSPI_SESSION_CWD\?\.trim\(\);/);
  assert.match(client, /process\.chdir\(resolvedCwd\)/);
  assert.match(wrapper, /cwd: mode === "client" \? \(process\.env\.TSPI_SESSION_CWD \|\| process\.cwd\(\)\)/);
  const piSource = await readFile(`${sourceRoot}/packages/coding-agent/src/experimental/client-tui.ts`, "utf8");
  assert.match(piSource, /const sessionCwd = process\.env\.TSPI_SESSION_CWD\?\.trim\(\);/);
  assert.match(piSource, /summary\.cwd === sessionCwd/);
});

async function startNativeServer(root, { workspaceRoot, python } = {}) {
  const serverDirectory = nativeServerDirectory(root);
  await mkdir(serverDirectory, { recursive: true });
  const child = spawn(process.execPath, [
    "apps/app-server/pi-experimental-app-server.mjs", "server", "--source-root", sourceRoot,
    "--directory", serverDirectory, "--workspace", root, "--session-dir", join(root, "sessions"),
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
  try {
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
  } catch (error) {
    await stopNativeServer(child);
    throw error;
  }
  return {
    child,
    serverId: output.match(/^Server: ([0-9a-f-]+)$/m)?.[1],
    socket: output.match(/^Socket: (.+)$/m)?.[1],
  };
}

async function stopNativeServer(child) {
  if (child.exitCode !== null || child.signalCode !== null) return;
  const exit = new Promise((resolve) => child.once("exit", resolve));
  child.kill("SIGTERM");
  let timeout;
  const stopped = await Promise.race([
    exit.then(() => true),
    new Promise((resolve) => { timeout = setTimeout(() => resolve(false), 2_000); }),
  ]).finally(() => clearTimeout(timeout));
  if (stopped || child.exitCode !== null || child.signalCode !== null) return;
  child.kill("SIGKILL");
  await exit;
}

async function runNativeClient(root, ...arguments_) {
  return runNativeClientWithEnv(root, {}, ...arguments_);
}

async function runNativeClientWithEnv(root, environment, ...arguments_) {
  return await new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [
      "apps/app-server/pi-experimental-app-server.mjs", "client", "--source-root", sourceRoot, ...arguments_,
    ], {
      cwd: process.cwd(),
      env: {
        ...process.env,
        PI_EXPERIMENTAL: "1",
        PI_OFFLINE: "1",
        PI_CODING_AGENT_DIR: join(root, "agent"),
        ...environment,
      },
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
    "apps/app-server/pi-experimental-app-server.mjs", "gateway", "--source-root", sourceRoot,
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
    const result = spawnSync(process.execPath, ["apps/app-server/pi-experimental-app-server.mjs", ...fixture.args], {
      cwd: process.cwd(),
      encoding: "utf8",
    });
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, new RegExp(fixture.message.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  }
  const gateway = spawnSync(process.execPath, ["apps/app-server/pi-experimental-app-server.mjs", "gateway", "--source-root", sourceRoot], {
    cwd: process.cwd(),
    encoding: "utf8",
  });
  assert.notEqual(gateway.status, 0);
  assert.match(gateway.stderr, /gateway requires --connect/);
});

test("native Pi app server starts from the pinned source entrypoint", { skip: !sourceRoot }, async () => {
  const root = await mkdtemp(join(tmpdir(), "tspi-native-server-"));
  const serverDirectory = nativeServerDirectory(root);
  await mkdir(serverDirectory, { recursive: true });
  await mkdir(join(root, "agent"), { recursive: true });
  await writeFile(join(root, "agent", "auth.json"), JSON.stringify({ anthropic: { type: "api_key", key: "test-key" } }), { mode: 0o600 });
  const child = spawn(process.execPath, [
    "apps/app-server/pi-experimental-app-server.mjs", "server", "--source-root", sourceRoot,
    "--directory", serverDirectory, "--workspace", root, "--session-dir", join(root, "sessions"),
  ], {
    cwd: process.cwd(), env: { ...process.env, PI_EXPERIMENTAL: "1", PI_OFFLINE: "1", PI_CODING_AGENT_DIR: join(root, "agent") },
    stdio: ["ignore", "pipe", "pipe"],
  });
  let output = "";
  let errors = "";
  let serverClient;
  let services;
  let backgroundContext;
  let step = "wait for server";
  child.stdout.setEncoding("utf8");
  child.stderr.setEncoding("utf8");
  child.stdout.on("data", (chunk) => { output += chunk; });
  child.stderr.on("data", (chunk) => { errors += chunk; });
  try {
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error(`native server did not start: ${output}${errors}`)), 15_000);
      child.stdout.on("data", () => {
        if (/^Server: [0-9a-f-]+\nSocket: .+\.sock/m.test(output)) { clearTimeout(timer); resolve(); }
      });
      child.once("error", reject);
      child.once("exit", (code) => { if (code !== null && code !== 0) reject(new Error(`native server exited ${code}: ${output}${errors}`)); });
    });
    const socket = output.match(/^Socket: (.+)$/m)?.[1];
    assert.ok(socket);
    step = "load client services";
    const fromSource = (relative) => import(pathToFileURL(join(sourceRoot, relative)).href);
    ({ BACKGROUND_CONTEXT: backgroundContext } = await fromSource("packages/chord/src/context/index.ts"));
    const { Client } = await fromSource("packages/client/src/index.ts");
    const { createUnixTransportFactory } = await fromSource("packages/client/src/unix.ts");
    const { SessionManagement } = await fromSource("packages/coding-agent/src/experimental/services/sessions.ts");
    const { readSessionPluginPackageProfile, writeSessionPluginPackageProfile } = await fromSource(
      "packages/coding-agent/src/experimental/plugins/package.ts",
    );
    const { createServerServiceBinding } = await fromSource("packages/coding-agent/test/experimental-service-binding.ts");
    const serverId = output.match(/^Server: ([0-9a-f-]+)$/m)?.[1];
    assert.ok(serverId);
    serverClient = await Client.connect({
      serverId,
      transportFactory: createUnixTransportFactory({ path: socket }),
    });
    step = "bind client services";
    services = createServerServiceBinding(serverClient, { services: [SessionManagement] });
    await services.ready(backgroundContext);
    step = "create session";
    const session = await services.use(SessionManagement).create({ id: "cli-attach" }, backgroundContext);
    const sessionFiles = (await readdir(join(root, "sessions"), { recursive: true }))
      .filter((path) => path.endsWith(".jsonl"));
    assert.equal(sessionFiles.length, 1);
    const sessionPath = join(root, "sessions", sessionFiles[0]);
    const legacyPresentationPackage = resolve("extensions/pi/tui-package");
    await writeSessionPluginPackageProfile(
      serverDirectory,
      serverId,
      sessionPath,
      [legacyPresentationPackage],
    );
    assert.deepEqual(
      await readSessionPluginPackageProfile(serverDirectory, serverId, sessionPath),
      [legacyPresentationPackage],
    );
    const client = await new Promise((resolve, reject) => {
      const result = spawn(process.execPath, [
        "apps/app-server/pi-experimental-app-server.mjs", "client", "--source-root", sourceRoot,
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
    assert.deepEqual(
      await readSessionPluginPackageProfile(serverDirectory, serverId, sessionPath),
      [],
    );
  } catch (error) {
    throw new Error(`${step}: ${error instanceof Error ? error.message : String(error)}\nServer output:\n${output}${errors}`, { cause: error });
  } finally {
    await services?.dispose(backgroundContext).catch(() => {});
    await serverClient?.dispose().catch(() => {});
    await stopNativeServer(child);
    await cleanupNativeRuntime(root);
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
    await cleanupNativeRuntime(root);
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
    await cleanupNativeRuntime(root);
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
    const projectBSession = await services.use(SessionManagement).create({ cwd: projectB }, backgroundContext);
    assert.equal(projectBSession.cwd, projectB);
    const workspaceSession = await services.use(SessionManagement).create({ workspaceId: "project-c" }, backgroundContext);
    assert.equal(workspaceSession.cwd, projectC);
    const projectAList = await runNativeClientWithEnv(
      root,
      { TSPI_SESSION_CWD: projectA },
      "--connect", `unix://${server.socket}`,
    );
    assert.equal(projectAList.stdout, `${server.serverId}\t${created.sessionId}\n`);
    assert.doesNotMatch(projectAList.stdout, new RegExp(projectBSession.sessionId));
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
    await cleanupNativeRuntime(root);
    await rm(root, { recursive: true, force: true });
  }
});
