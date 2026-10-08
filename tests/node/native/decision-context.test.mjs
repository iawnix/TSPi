import assert from 'node:assert/strict';
import test from 'node:test';
import { Harness, MemoryStorage, createRegistry, defineExtension, hook, GenerationTask, CompactionTask } from '@earendil-works/pi-durable';
import { createModels, fauxProvider, fauxAssistantMessage } from '@earendil-works/pi-ai';
import { TODO_CONTEXT as context } from '@earendil-works/chord/context';
import { createDecisionContextInjector } from '../../../apps/app-server/decision-context.mjs';

test('actual generation requests rebuild facts after compaction and never persist snapshots', async t => {
  const faux = fauxProvider();
  const models = createModels(); models.setProvider(faux.provider);
  const requests = [], telemetry = [];
  let revision = 1;
  const inject = createDecisionContextInjector({
    sessionId: 'session_fixture', readModel: async () => ({contextWindow: 200000, maxTokens: 4096}),
    bridge: { async execute_command(command) {
      assert.equal(command, 'research.context');
      return { schema_version: 'research-decision-context/2', context_id: `ctx_${revision}`, revision, events: [],
        goals: [{id: 'claim_goal', statement: 'Validate the transition structure'}],
        attempts: [{id: 'attempt_current', state: revision === 1 ? 'running' : 'failed',
          primary_failure: revision === 1 ? null : 'optimization_limit'}] };
    } },
    coordinator: { async commit_files(record) { telemetry.push(record); } },
  });
  const registry = createRegistry();
  registry.install(defineExtension({name:'context-fixture', hooks:[
    hook(GenerationTask, { beforeRequest: (request, api) => inject(request, String(api.taskId), api.conversationId) }),
    hook(CompactionTask, { beforeCompact: () => ({summary:'Old interpretation: attempt_current was QPErr. This historical claim must be checked against current execution facts.'}) }),
  ]}));
  const harness = await Harness.open(new MemoryStorage(), {models, registry,
    settings: {compaction: {enabled: false, keepRecentTokens: 0}}}, context);
  t.after(() => harness.close(context));
  const conversation = await harness.root(context, {agent:{model:{provider:'faux',modelId:'faux-1'}}});
  faux.setResponses([1,2].map(() => input => { requests.push(input); return fauxAssistantMessage('Research decision recorded.'); }));
  await conversation.submit({type:'input',content:'Initial research task. '.repeat(100)},context);
  await conversation.waitForIdle(context);
  const task = await conversation.compact(undefined, context);
  await harness.waitForTask(task, context);
  await conversation.waitForIdle(context);
  revision = 2;
  await conversation.submit({type:'input',content:'Inspect the latest result.'},context);
  await conversation.waitForIdle(context);
  assert.equal(requests.length, 2);
  const latest = JSON.stringify(requests[1].messages);
  assert.match(latest, /Old interpretation/);
  assert.match(latest, /optimization_limit/);
  assert.match(latest, /claim_goal/);
  assert.equal(requests[1].messages.filter(m => JSON.stringify(m).includes('<research_state_snapshot>')).length, 1);
  assert.equal(telemetry.at(-1).payload.revision, 2);
  const entries = await conversation.entries({}, 100, undefined, context);
  assert.ok(entries.items.some(e => e.kind === 'pi.compaction'));
  assert.equal(JSON.stringify(entries).includes('<research_state_snapshot>'), false);
});
