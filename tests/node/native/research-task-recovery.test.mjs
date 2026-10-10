import assert from "node:assert/strict";
import test from "node:test";
import { mkdtemp, rm } from "node:fs/promises";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { Harness, createRegistry, defineExtension, LiveDoc, InboxDoc } from "@earendil-works/pi-durable";
import { openNodeSqliteStorage } from "@earendil-works/pi-durable/storage/sqlite/node";
import { createModels, fauxProvider, fauxAssistantMessage } from "@earendil-works/pi-ai";
import { TODO_CONTEXT as context } from "@earendil-works/chord/context";
import { TEST_ROOT, pinnedPiSource } from "./test-environment.mjs";
import { create_workspace_initializer } from "../../../apps/agent/host/workspace.mjs";
import { create_python_runtime_bridge } from "../../../apps/agent/bridge/client.mjs";
import { createInputAdmission } from "../../../apps/agent/host/admission/input.mjs";
import { createResearchTools } from "../../../apps/agent/tools/research/tools.mjs";
import { createTaskTools } from "../../../apps/agent/tasks/tools.mjs";
import { createTaskController } from "../../../apps/agent/tasks/controller.mjs";
import { createToolExecutionContext } from "../../../apps/agent/tools/context.mjs";
import { wrapToolForHarness } from "../../../apps/agent/tools/envelope.mjs";

const { admitSubmission } = await import(pathToFileURL(join(pinnedPiSource(), "packages/durable/src/harness/submissions.ts")));
const call = (name, args, id) => ({ ...fauxAssistantMessage(""), stopReason: "toolUse",
  content: [{ type: "toolCall", id, name, arguments: args }] });

test("Memory create survives before Task binding and both stores replay their original operation identities", { timeout: 30_000 }, async () => {
  const root = await mkdtemp(join(TEST_ROOT, "research-task-recovery-"));
  const workspaceRoot = join(root, "workspace"), database = join(root, "conversation.sqlite");
  const workspaceId = "recovery", sessionId = "recovery-session";
  const workspaces = create_workspace_initializer();
  const faux = fauxProvider(), models = createModels(); models.setProvider(faux.provider);
  const invocations = [], writes = [];
  let bridge, harness, controller, conversation, admission, tools;
  async function close() {
    await controller?.close(); controller = undefined;
    await harness?.close(context); harness = undefined;
    await bridge?.close(); bridge = undefined;
  }
  async function open() {
    bridge = create_python_runtime_bridge({ workspace_root: workspaceRoot, workspace_id: workspaceId });
    const commandBridge = { execute_command(command, params) {
      if (command === "research.create") writes.push(params.request_id);
      return bridge.execute_command(command, params);
    } };
    const trusted = createToolExecutionContext({ workspace_root: workspaceRoot, session_id: sessionId,
      operation_id: null, principal: "root_agent", allowed_authorities: ["kernel_read", "kernel_write", "task_control"],
      allowed_effects: ["read", "research_write", "task_write"] });
    tools = [...createResearchTools({ commandBridge }), ...createTaskTools(() => controller)].map(tool => {
      const wrapped = wrapToolForHarness(tool, { toolContext: trusted,
        invocation: api => ({ workspaceRoot, sessionId, operationId: String(api.taskId) }) });
      return { ...wrapped, async execute(params, api, ctx) {
        const result = await wrapped.execute(params, api, ctx);
        invocations.push({ name: tool.name, params: structuredClone(params),
          api: { taskId: api.taskId, callId: api.callId }, result });
        return result;
      } };
    });
    const registry = createRegistry();
    registry.install(defineExtension({ name: "research-recovery-tools", tools }));
    harness = await Harness.open(await openNodeSqliteStorage(database), { models, registry, settings: {} }, context);
    conversation = await harness.root(context, { agent: { model: { provider: "faux", modelId: "faux-1" } } });
    admission = createInputAdmission({ harness, conversation, LiveDoc, InboxDoc, admitSubmission });
    controller = createTaskController({ harness, conversation, admission, LiveDoc, InboxDoc,
      kernel: bridge, workspaceId, sessionId, context });
    await admission.checkRecovery(context);
  }
  const replay = invocation => tools.find(tool => tool.name === invocation.name).execute(invocation.params, invocation.api, context);
  try {
    await workspaces.initialize_workspace({ workspace_root: workspaceRoot, workspace_id: workspaceId });
    await workspaces.admit_workspace(workspaceRoot);
    await open();
    faux.setResponses([fauxAssistantMessage("I will retain the derivation and its limitations.")]);
    const source = await admission.submitUser({ requestId: "user-research", content: "Develop a local theoretical derivation." }, context);
    await conversation.waitForIdle(context);
    const task = await controller.begin({ title: "Derivation", objective: "Retain the derivation and limitations",
      source_submission_ids: [String(source.id)], criteria: [{ id: "derivation", description: "A recorded derivation" }] }, "begin", context);
    const createParams = { title: "Boundary condition", goal: "Does the solution satisfy the boundary condition?", plan: "Substitute the general solution." };
    faux.setResponses([call("research_create", createParams, "provider-call"), fauxAssistantMessage("The research question is recorded.")]);
    await admission.submitUser({ requestId: "create-question", content: "Record the question before continuing." }, context);
    await conversation.waitForIdle(context);
    const created = invocations.find(item => item.name === "research_create");
    assert.equal(created.result.isError, undefined);
    const nodeId = created.result.details.result.node.id;
    assert.deepEqual((await controller.current(context)).research, { entry_node_ids: [], focus_node_ids: [] });
    assert.equal(writes[0], `${sessionId}:${created.api.taskId}:${created.api.callId}`);
    const receipt = await bridge.transaction_get({ request_id: writes[0] });
    assert.equal(receipt.result.node.id, nodeId);
    // The Memory commit exists, while no Task association has been committed.
    await close();
    await open();
    assert.equal((await controller.current(context)).user_task_id, task.user_task_id);
    assert.deepEqual((await controller.current(context)).research.entry_node_ids, []);
    const replayed = await replay(created);
    assert.equal(replayed.isError, undefined);
    assert.deepEqual(replayed.details.result, created.result.details.result);
    let snapshot = await bridge.execute_command("research.read", { session_id: sessionId });
    assert.deepEqual(snapshot.nodes.map(node => node.id), [nodeId], "replaying the committed create must not invent another root");
    const changed = await tools.find(tool => tool.name === "research_create").execute({ ...createParams, goal: "Different content" }, created.api, context);
    assert.equal(changed.isError, true, "the same operation identity cannot change its committed payload");
    faux.setResponses([async () => call("task_update", { action: "set_research", expected_revision: (await controller.current(context)).revision,
      research: { entry_node_ids: [nodeId], focus_node_ids: [nodeId] } }, "bind-call"), fauxAssistantMessage("The existing question is now associated with the task.")]);
    await admission.submitUser({ requestId: "bind-question", content: "Continue using the existing question." }, context);
    await conversation.waitForIdle(context);
    const bound = invocations.find(item => item.name === "task_update");
    assert.equal(bound.result.isError, undefined);
    const boundTask = await controller.current(context);
    assert.deepEqual(boundTask.research.entry_node_ids, [nodeId]);
    await close();
    await open();
    assert.deepEqual(await controller.current(context), boundTask);
    assert.deepEqual((await replay(bound)).details.result, bound.result.details.result);
    assert.equal((await controller.current(context)).revision, boundTask.revision, "Task receipt replay does not repeat the association write");
    // Providers may reuse call IDs; distinct Pi operations must remain distinct.
    faux.setResponses([call("research_create", { goal: "What controls the approximation error?" }, created.api.callId), fauxAssistantMessage("The independent error question is recorded.")]);
    await admission.submitUser({ requestId: "independent-question", content: "Record the independent approximation question." }, context);
    await conversation.waitForIdle(context);
    const independent = invocations.at(-1);
    assert.equal(independent.name, "research_create");
    assert.equal(independent.result.isError, undefined);
    assert.notEqual(independent.api.taskId, created.api.taskId);
    assert.equal(independent.api.callId, created.api.callId);
    assert.notEqual(independent.result.details.result.node.id, nodeId);
    snapshot = await bridge.execute_command("research.read", { session_id: sessionId });
    assert.equal(snapshot.nodes.length, 2);
    assert.deepEqual((await controller.current(context)).research.entry_node_ids, [nodeId]);
  } finally {
    try { await close(); }
    finally { await rm(root, { recursive: true, force: true }); }
  }
});
