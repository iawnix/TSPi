import assert from 'node:assert/strict';
import test from 'node:test';
import { Harness, MemoryStorage, createRegistry, LiveDoc } from '@earendil-works/pi-durable';
import { createModels, fauxProvider } from '@earendil-works/pi-ai';
import { TODO_CONTEXT as context } from '@earendil-works/chord/context';
import { createSessionAdmission } from '../../../apps/app-server/session-admission.mjs';

test('interrupt aborts its active turn; a late retry leaves the next turn running', { timeout: 10000 }, async t => {
  const faux = fauxProvider();
  const models = createModels(); models.setProvider(faux.provider);
  const harness = await Harness.open(new MemoryStorage(), { models, registry: createRegistry(), settings: {} }, context);
  t.after(() => harness.close(context));
  const conversation = await harness.root(context, { agent: { model: { provider: 'faux', modelId: 'faux-1' } } });
  const admission = createSessionAdmission({ harness, conversation, LiveDoc });
  const start = async content => {
    let reached; let aborted = false;
    const ready = new Promise(resolve => { reached = resolve; });
    faux.setResponses([(_ctx, options) => new Promise((_, reject) => {
      reached(); options.signal.addEventListener('abort', () => { aborted = true; reject(options.signal.reason); }, { once: true });
    })]);
    const submission = await conversation.submit({ type: 'input', content }, context);
    await ready;
    return { id: String(submission.id), aborted: () => aborted };
  };
  const first = await start('first');
  assert.equal((await admission.interrupt({ turnId: 'unrelated' }, context)).accepted, false);
  assert.equal(first.aborted(), false);
  assert.equal((await admission.interrupt({ turnId: first.id }, context)).accepted, true);
  await conversation.waitForIdle(context);
  assert.equal(first.aborted(), true);
  const second = await start('second');
  assert.equal((await admission.interrupt({ turnId: first.id }, context)).accepted, false);
  assert.equal(second.aborted(), false);
  assert.equal((await admission.interrupt({ turnId: second.id }, context)).accepted, true);
  await conversation.waitForIdle(context);
  assert.equal(second.aborted(), true);
  await assert.rejects(admission.interrupt({}, context), /turn_id/);
});
