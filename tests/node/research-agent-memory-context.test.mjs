import assert from "node:assert/strict";
import test from "node:test";

import {
  create_context_builder,
  create_memory_store,
} from "../../packages/agent-core/index.mjs";
import {
  create_model_port,
  create_memory_port,
} from "../../packages/agent-core/ports.mjs";

test("session memory is bounded and does not expose mutable internal records", async () => {
  const memory = create_memory_store({ workspace_mode: "research", workspace_id: "workspace_research", session_id: "session_1", max_entries: 2 });
  const added = await memory.append({
    workspace_mode: "research",
    entry: { entry_id: "memory_first", kind: "turn", content: { prompt: "hello" } },
  });
  assert.equal(added.accepted, true);
  const first = await memory.read();
  first.entries[0].content.prompt = "mutated";
  assert.equal((await memory.read()).entries[0].content.prompt, "hello");
  await memory.append({ entry: { kind: "tool_result", content: { value: 1 } } });
  await assert.rejects(
    memory.append({ entry: { kind: "overflow", content: null } }),
    /memory_limit_exceeded/,
  );
});

test("research session memory cannot become workspace scientific memory", async () => {
  const memory = create_memory_store({ workspace_mode: "research", workspace_id: "workspace_research", session_id: "session_1" });
  await memory.append({ entry: { kind: "turn", content: "session-only" } });
  await assert.rejects(
    memory.append({ scope: "workspace", entry: { kind: "claim", content: "not a ResearchMap write" } }),
    /research_memory_authority_required/,
  );
  await assert.rejects(
    memory.read({ workspace_mode: "invalid" }),
    /workspace_mode_mismatch/,
  );
});

test("context builder creates a bounded ephemeral pack with Kernel provenance", async () => {
  const memory = create_memory_store({ workspace_mode: "research", workspace_id: "workspace_research", session_id: "session_1" });
  await memory.append({ entry: { kind: "turn", content: "hello" } });
  const context = create_context_builder({
    memory_port: memory,
    workspace_mode: "research",
    workspace_id: "workspace_research",
    session_id: "session_1",
    entry_limit: 1,
  });
  const pack = await context.build({
    kernel_context: {
      provenance: { memory: "research-memory" },
      memory_revision: 4,
      lifecycle: { state: "admitted" },
    },
  });
  assert.equal(pack.schema_version, "agent_context_1");
  assert.match(pack.context_id, /^ctx_[a-f0-9]{24}$/u);
  assert.equal(pack.memory.scope, "session");
  assert.equal(pack.kernel_context.memory_revision, 4);
  assert.equal(pack.provenance.kernel_revision, 4);
  assert.equal(pack.bounds.truncated, false);
  await assert.rejects(
    context.build({ workspace_mode: "invalid" }),
    /workspace_mode_mismatch/,
  );
});

test("research context rejects an untrusted scientific projection", async () => {
  const memory = create_memory_store({ workspace_mode: "research" });
  const context = create_context_builder({ memory_port: memory, workspace_mode: "research" });
  await assert.rejects(
    context.build({ kernel_context: { provenance: { source: "model_input" } } }),
    /research_context_requires_kernel_source/,
  );
});

test("ModelPort and MemoryPort wrappers bind implementations and own protocol ids", async () => {
  class Model {
    constructor() { this.calls = 0; }
    describe() { return [{ id: "fixture" }]; }
    async *stream() { this.calls += 1; yield { type: "text", text: "ok" }; }
  }
  const model = new Model();
  model.protocol_version = "wrong";
  const model_port = create_model_port(model);
  assert.equal(model_port.protocol_version, "model_port_1");
  assert.deepEqual(model_port.describe(), [{ id: "fixture" }]);
  const events = [];
  for await (const event of model_port.stream({ input: "hello" })) events.push(event);
  assert.deepEqual(events, [{ type: "text", text: "ok" }]);
  assert.equal(model.calls, 1);

  const memory_port = create_memory_port({
    async read() { return { entries: [] }; },
    async append(request) { return { accepted: true, request }; },
  });
  assert.equal(memory_port.protocol_version, "memory_port_1");
  assert.equal((await memory_port.append({ entry: { kind: "turn" } })).accepted, true);
});
