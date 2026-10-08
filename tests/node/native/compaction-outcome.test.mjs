import assert from 'node:assert/strict';
import test from 'node:test';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {Harness,MemoryStorage,createRegistry,defineExtension,hook,CompactionTask} from '@earendil-works/pi-durable';
import {createModels,fauxProvider,fauxAssistantMessage} from '@earendil-works/pi-ai';
import {TODO_CONTEXT as context} from '@earendil-works/chord/context';
import {pinnedPiSource} from './test-environment.mjs';
const fromSource = path => import(pathToFileURL(join(pinnedPiSource(),path)));
const {createAgentController} = await fromSource('packages/coding-agent/src/experimental/services/agent-controller-provider.ts');

for (const scenario of ['completed','skipped','failed','cancelled']) {
  test(`manual compaction reports ${scenario} from its durable operation`, {timeout:10000}, async t => {
    const faux = fauxProvider(); const models = createModels(); models.setProvider(faux.provider);
    const registry = createRegistry();
    let started, release;
    const pending = new Promise(resolve => { started = resolve; });
    if (scenario === 'completed' || scenario === 'cancelled') registry.install(defineExtension({name:'compact-outcome',hooks:[
      hook(CompactionTask,{async beforeCompact(){
        if (scenario === 'cancelled') { started(); await new Promise(resolve => {release=resolve;}); }
        return {summary:'PRIVATE SUMMARY CONTENT'};
      }}),
    ]}));
    const harness = await Harness.open(new MemoryStorage(),{models,registry,
      settings:{compaction:{enabled:false,keepRecentTokens:0},retry:{enabled:false}}},context);
    t.after(()=>harness.close(context));
    const conversation = await harness.root(context,{agent:{model:{provider:'faux',modelId:'faux-1'}}});
    const controller = createAgentController(harness,conversation);
    if (scenario !== 'skipped') {
      faux.setResponses([fauxAssistantMessage('Answer'),fauxAssistantMessage('',{stopReason:'error',errorMessage:'Summary provider unavailable'})]);
      await (await conversation.submit({type:'input',content:'History '.repeat(100)},context)).wait(context);
    }
    const operation = await controller.compact({customInstructions:null},context);
    assert.equal(operation.accepted,true);
    if (scenario === 'cancelled') {
      await pending;
      const aborting = controller.abort(context);
      release();
      await aborting;
    }
    const outcome = await controller.waitForCompaction(operation.operationId,context);
    assert.equal(outcome.status,scenario);
    if (scenario === 'failed') assert.match(outcome.error,/Summary provider unavailable/);
    if (scenario === 'completed') {
      // Completion means the summary has actually been placed, including queued placement.
      const entries = await conversation.entries({},100,undefined,context);
      assert.ok(entries.items.some(entry => entry.kind === 'pi.compaction'));
      const [{ExperimentalChatView},{TuiAltScreen},{VirtualTerminal},{initTheme}] = await Promise.all([
        fromSource('packages/coding-agent/src/experimental/client-tui-chat.ts'),
        fromSource('packages/tui/src/index.ts'),fromSource('packages/tui/test/virtual-terminal.ts'),
        fromSource('packages/coding-agent/src/modes/interactive/theme/theme.ts'),
      ]);
      initTheme('dark');
      const ui = new TuiAltScreen(new VirtualTerminal(100,24));
      const chat = new ExperimentalChatView(ui, process.cwd());
      const state = await conversation.viewState(context);
      try {
        chat.apply(state.value);
        const rendered = chat.transcript.render(100).join('\n');
        assert.match(rendered,/Context compacted/);
        assert.doesNotMatch(rendered,/PRIVATE SUMMARY CONTENT/);
      } finally {chat.dispose(); await state.dispose(context);}
    }
    await assert.rejects(controller.waitForCompaction('invalid',context),/Unknown compaction/);
    const other = await harness.createConversation({ownership:{kind:'ownerless'}},context);
    await assert.rejects(createAgentController(harness,other).waitForCompaction(operation.operationId,context),/Unknown compaction/);
  });
}
