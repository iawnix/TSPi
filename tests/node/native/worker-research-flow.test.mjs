import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { mkdir, mkdtemp, readFile, writeFile, rm, readdir, symlink } from "node:fs/promises";
import { createServer } from "node:http";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import test from "node:test";
import { TEST_ROOT, managedPython, pinnedPiSource } from "./test-environment.mjs";

const execute = promisify(execFile);
const sourceRoot = pinnedPiSource();
const packageRoot = resolve(process.env.TSPI_TEST_PACKAGE_ROOT || process.cwd());
const quote = value => `'${value.replaceAll("'", "'\\''")}'`;

test("Worker reads installed Skills, runs a Job, checks configured email and ends a user wait", {
  skip: !sourceRoot || !existsSync(join(sourceRoot, "packages/coding-agent/src/experimental/source-resolver.ts")),
  timeout: 60_000,
}, async () => {
  await mkdir(TEST_ROOT, { recursive: true });
  const root = await mkdtemp(join(TEST_ROOT, "flow-"));
  const saved = { ...process.env };
  let backend, server;
  const requests = [];
  try {
    const agentDir = join(root, "agent");
    const workspaceRoot = join(root, "workspaces");
    const workspace = join(workspaceRoot, "flow");
    const python = managedPython();
    await mkdir(agentDir); await mkdir(workspaceRoot);
    const config = join(root, "email.toml");
    await writeFile(config, '[notifications.email]\nenabled=true\nprovider="smtp"\npreset="custom"\nhost="127.0.0.1"\nport=9\nsecurity="ssl"\nusername="sender@example.test"\nrecipient="reader@example.test"\npassword_env="FIXTURE_MAIL_PASSWORD"\n', { mode: 0o600 });
    Object.assign(process.env, { PI_CODING_AGENT_DIR: agentDir, TSPI_PYTHON: python,
      PYTHONDONTWRITEBYTECODE: "1", TS_NOTIFICATION_CONFIG: config });
    delete process.env.TS_JOB_CONFIG;
    await execute(python, [join(packageRoot, "apps/agent-cli/workspace_mode.py"), "--root", workspace, "--workspace-id", "flow"]);
    const call = (name, args) => ({ name, arguments: args });
    const steps = [
      ...["extensions/core/skills/research-state/SKILL.md", "extensions/core/skills/orchestration/SKILL.md",
        "extensions/chemical/skills/method-selection/SKILL.md", "extensions/chemical/skills/cf22d/SKILL.md",
        "extensions/chemical/skills/cf22d/references/cf22d_workflow.md", "extensions/chemical/skills/_shared/science.py",
        "extensions/email/SKILL.md", "extensions/email/scripts/email_cli.py"].map(path => call("read", { path: join(packageRoot, path) })),
      call("bash", { command: [python, join(packageRoot, "extensions/email/scripts/email_cli.py"), "check", "--root", workspace, "--output", join(workspace, "reports/email-check.json")].map(quote).join(" ") }),
      call("research_read", { mode: "context" }),
      call("research_change", { rationale: "Initialize a bounded fixture", operations: [
        { type: "create_claim", id: "claim_flow", statement: "The fixture can produce a file" },
        { type: "create_node", id: "node_flow", title: "Fixture", objective: "Produce evidence", claim_ids: ["claim_flow"] },
        { type: "set_focus", claim_ids: ["claim_flow"], node_ids: ["node_flow"] },
      ] }),
      call("research_strategy", { claimId: "claim_flow", strategyOperation: "plan", plan: {
        id: "strategy_flow", claim_id: "claim_flow", node_id: "node_flow", objective: "Produce a file",
        rationale: "Exercise the real execution chain", status: "active",
      } }),
      call("job_start", { nodeId: "node_flow", requestId: "fixture_run", command: [python, "-c", "from pathlib import Path;Path('result.txt').write_text('fixture evidence')"], outputs: [{ path: "result.txt", required: true, minBytes: 1 }] }),
      call("job_status", { jobId: "job_fixture_run" }),
      call("job_collect", { jobId: "job_fixture_run" }),
      // First end without a disposition: exactly one repair is expected.
      "Fixture evidence collected.",
      call("research_read", { mode: "context" }),
      call("research_change", { rationale: "The fixture needs an actual user choice", operations: [
        { type: "set_node_state", node_id: "node_flow", state: "blocked", summary: "Choose the next fixture experiment" },
      ] }),
      call("research_checkpoint", { checkpoint: { id: "checkpoint_wait", disposition: "user_input_required",
        claim_ids: ["claim_flow"], node_ids: ["node_flow"], reason: "A genuine fixture user choice is needed" } }),
      "Waiting for the fixture user's choice.",
    ];
    server = createServer(async (req, res) => {
      let body = ""; for await (const part of req) body += part;
      const request = JSON.parse(body); requests.push(request);
      const step = steps[requests.length - 1] || "Unexpected continuation.";
      if (step?.name === "job_status") {
        const statusFile = join(workspace, "runs/jobs/job_fixture_run/status.json");
        for (let i = 0; i < 100 && !existsSync(statusFile); i++) await new Promise(done => setTimeout(done, 20));
        assert.ok(existsSync(statusFile), "fixture process must finish before collection");
      }
      const delta = typeof step === "string" ? { role: "assistant", content: step } : {
        role: "assistant", tool_calls: [{ index: 0, id: `call_${requests.length}`, type: "function",
          function: { name: step.name, arguments: JSON.stringify(step.arguments) } }],
      };
      res.writeHead(200, { "Content-Type": "text/event-stream" });
      for (const [chunk, finish] of [[delta, null], [{}, typeof step === "string" ? "stop" : "tool_calls"]]) {
        res.write(`data: ${JSON.stringify({ id: `reply_${requests.length}`, object: "chat.completion.chunk", created: 1,
          model: "fixture", choices: [{ index: 0, delta: chunk, finish_reason: finish }] })}\n\n`);
      }
      res.end("data: [DONE]\n\n");
    });
    await new Promise(done => server.listen(0, "127.0.0.1", done));
    await writeFile(join(agentDir, "models.json"), JSON.stringify({ providers: { fixture: {
      baseUrl: `http://127.0.0.1:${server.address().port}/v1`, apiKey: "fixture-only", api: "openai-completions",
      models: [{ id: "fixture", name: "Fixture", reasoning: false, input: ["text"],
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 200000, maxTokens: 4096 }],
    } } }));
    const { createTspiHarnessBackend } = await import(pathToFileURL(join(packageRoot, "apps/app-server/tspi-harness-backend.mjs")));
    const packageAlias = join(root, "current-package");
    await symlink(packageRoot, packageAlias, "dir");
    backend = await createTspiHarnessBackend({ sourceRoot, packageRoot: packageAlias, workspaceRoot,
      serverDirectory: join(root, "pi"), sessionDir: join(root, "sessions"), stateRoot: join(root, "state"),
      provider: "fixture", model: "fixture" });
    const created = await backend.createSession({ workspace_id: "flow", provider: "fixture", model: "fixture" });
    const session_id = created.session.session_id;
    await backend.sendInput({ workspace_id: "flow", session_id, request_id: "fixture_request", client_message_id: "fixture_message",
      text: "Exercise the local fixture without sending mail.", mode: "auto" });
    let read;
    for (let i = 0; i < 250; i++) {
      read = await backend.readSession("flow", session_id);
      if (requests.length && !read.session.is_streaming) break;
      await new Promise(done => setTimeout(done, 100));
    }
    assert.equal(read.session.is_streaming, false);
    assert.equal(requests.length, steps.length, JSON.stringify(read.snapshot.failure));
    const toolResults = requests.at(-1).messages.filter(message => message.role === "tool");
    assert.equal(toolResults.length, steps.filter(step => typeof step !== "string").length);
    for (const result of toolResults) assert.doesNotMatch(String(result.content), /Tool call blocked|^research_decision_required|^operation references unknown/);
    const context = JSON.parse(await readFile(join(workspace, "research_map/context.json")));
    assert.equal(context.attempts.length, 1);
    assert.equal(context.attempts[0].state, "succeeded");
    assert.ok(context.artifacts.length > 0);
    const email = JSON.parse(await readFile(join(workspace, "reports/email-check.json")));
    assert.equal(email.recipient, "reader@example.test");
    assert.equal(email.enabled, true);
    assert.equal(existsSync(join(workspace, "reports/email/deliveries")), false);
    const liveness = JSON.parse(await readFile(join(workspace, "lifecycle/liveness.json")));
    assert.equal(liveness.disposition, "user_input_required");
    const continuations = requests.at(-1).messages.filter(message => message.role === "user" && JSON.stringify(message.content).includes("Research turn ended"));
    assert.equal(continuations.length, 1);
  } catch (error) {
    for (const file of await readdir(root, { recursive: true })) {
      if (file.endsWith(".log")) console.error(file, await readFile(join(root, file), "utf8"));
    }
    throw error;
  } finally {
    try { await backend?.close(); }
    finally {
      if (server) { server.closeAllConnections(); await new Promise(done => server.close(done)); }
      for (const key of Object.keys(process.env)) if (!(key in saved)) delete process.env[key];
      Object.assign(process.env, saved);
      await rm(root, { recursive: true, force: true });
    }
  }
});
