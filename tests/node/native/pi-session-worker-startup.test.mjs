import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import test from "node:test";
import { TEST_ROOT, managedPython, pinnedPiSource } from "./test-environment.mjs";

const execute = promisify(execFile);
const sourceRoot = pinnedPiSource();
const packageRoot = resolve(process.env.TSPI_TEST_PACKAGE_ROOT || process.cwd());

test("real Pi Worker creates and reads a research session without a model request", {
  skip: !sourceRoot || !existsSync(join(sourceRoot, "packages/coding-agent/src/experimental/source-resolver.ts")),
  timeout: 60_000,
}, async () => {
  await mkdir(TEST_ROOT, { recursive: true });
  const root = await mkdtemp(join(TEST_ROOT, "w-"));
  const savedEnvironment = { ...process.env };
  let backend;
  try {
    process.env.PI_CODING_AGENT_DIR = join(root, "agent");
    await mkdir(process.env.PI_CODING_AGENT_DIR);
    await writeFile(join(process.env.PI_CODING_AGENT_DIR, "models.json"), JSON.stringify({ providers: { fixture: {
      baseUrl: "http://127.0.0.1:9/v1", apiKey: "fixture-only", api: "openai-completions",
      models: [{id:"fixture", name:"Fixture", reasoning:false, input:["text"],
        cost:{input:0, output:0, cacheRead:0, cacheWrite:0}, contextWindow:200000, maxTokens:4096}],
    } } }));
    process.env.TSPI_PYTHON = managedPython();
    process.env.PYTHONDONTWRITEBYTECODE = "1";
    const workspaceRoot = join(root, "workspaces");
    await mkdir(workspaceRoot);
    await execute(process.env.TSPI_PYTHON, [
      join(packageRoot, "apps/agent-cli/workspace_mode.py"),
      "--root", join(workspaceRoot, "startup"), "--workspace-id", "startup",
    ]);
    const { createTspiHarnessBackend } = await import(pathToFileURL(join(packageRoot, "apps/app-server/tspi-harness-backend.mjs")));
    backend = await createTspiHarnessBackend({
      sourceRoot, packageRoot, workspaceRoot,
      serverDirectory: join(root, "pi"), sessionDir: join(root, "sessions"),
      stateRoot: join(root, "state"), provider:"fixture", model:"fixture",
    });
    const created = await backend.createSession({ workspace_id: "startup", provider:"fixture", model:"fixture" });
    assert.equal(created.session.runtime_kind, "pi-harness");
    assert.equal(created.session.online, true);
    assert.equal(created.session.is_streaming, false);
    const read = await backend.readSession("startup", created.session.session_id);
    assert.equal(read.session.session_id, created.session.session_id);
    assert.equal(read.snapshot.operation, null);
    assert.ok(existsSync(join(root, "sessions", "startup", created.session.session_id, "session.sqlite")));
  } finally {
    try { await backend?.close(); }
    finally {
      for (const key of Object.keys(process.env)) if (!(key in savedEnvironment)) delete process.env[key];
      Object.assign(process.env, savedEnvironment);
      await rm(root, { recursive: true, force: true });
    }
  }
});
