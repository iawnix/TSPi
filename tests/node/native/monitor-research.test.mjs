import assert from 'node:assert/strict';
import test from 'node:test';
import { createMonitorService } from '../../../apps/agent/tasks/service.mjs';
import { formatMonitor } from '../../../apps/agent/terminal/commands/monitor.mjs';
import { createTerminalSession } from '../../../apps/agent/terminal/session.mjs';

const task = {
  schema_version: 'coragent-user-task/2', user_task_id: 'task_a', title: 'Compare methods',
  objective: 'Explain the comparison and its limits', state: 'active', criteria: [],
  research: { entry_node_ids: ['node_a', 'node_b'], focus_node_ids: ['node_shared'] },
  updated_at: '2026-10-10T00:00:00Z', revision: 7,
};
const snapshot = {
  schema_version: 'research-snapshot/3', sequence: 42,
  research: {
    entry_node_ids: task.research.entry_node_ids, focus_node_ids: task.research.focus_node_ids,
    nodes: [
      { id: 'node_a', revision: 1, title: 'Method A', status: 'closed', assessment_ref: 'result_a',
        plan: 'Compare the numerical estimates', content_omitted: false, read: { ref: 'node_a', field: 'relations' } },
      { id: 'node_shared', revision: 3, title: 'Shared convergence question', status: 'open', assessment_ref: null,
        plan: 'Bound the numerical error', content_omitted: true, read: { ref: 'node_shared', field: 'relations' } },
    ],
    relations: [
      { id: 'edge_a', source: 'node_shared', kind: 'part_of', target: 'node_a' },
      { id: 'edge_b', source: 'node_shared', kind: 'part_of', target: 'node_b' },
    ],
    omitted: { entry_node_ids: 0, focus_node_ids: 0, nodes: 1, relations: 2, unexpanded_nodes: 1 },
  },
  nodes: [
    { id: 'node_a', recent_results: [{ id: 'result_a', summary: 'Uncertainty remains' }] },
    { id: 'node_unrelated', title: 'Unrelated recent research' },
  ],
  running_jobs: [{ job_id: 'job_a', node_id: 'node_shared' }, { job_id: 'job_unrelated', node_id: 'node_unrelated' }],
  uncollected_jobs: [],
};

test('Monitor task research uses the canonical read without mutating focus or admitting input', async () => {
  const original = structuredClone(task), calls = [], reads = [];
  const service = createMonitorService({ workspaceId: 'w', sessionId: 's',
    controller: { async read(params) { reads.push(params); return task; } },
    kernel: { async execute_command(command, params) {
      calls.push([command, params]);
      return command === 'research.read' ? snapshot : { jobs: [{ job_id: 'job_a' }], next_cursor: null };
    } },
  });
  const rpc = [];
  const session = createTerminalSession({ workspaceId: 'w', sessionId: 's',
    async request(method, params) {
      rpc.push(method);
      const response = await service.handle({ method, params });
      assert.equal(response.error, null);
      return response.result;
    },
  });
  for (let attempt = 0; attempt < 2; attempt++) {
    const response = await session.monitor('monitor/task/read', { user_task_id: 'task_a' });
    assert.equal(response.task, task);
    assert.equal(response.research, snapshot);
    assert.deepEqual(response.session_job_ids, ['job_a']);
  }
  assert.deepEqual(rpc, ['monitor/task/read', 'monitor/task/read']);
  assert.equal(reads.length, 2);
  assert.deepEqual(calls, Array.from({ length: 2 }, () => [['research.read', {
    session_id: 's', entry_node_ids: ['node_a', 'node_b'], focus_node_ids: ['node_shared'], limit: 16000,
  }], ['job.list', { session_id: 's', limit: 100 }]]).flat());
  assert.deepEqual(task, original);
});

test('Monitor displays shared graph references, partial plans and ended status without success claims', () => {
  const view = formatMonitor('monitor/task/read', { task, research: snapshot, session_job_ids: ['job_a'] });
  assert.match(view, /Research problems/);
  assert.match(view, /Entry references: node_a, node_b/);
  assert.match(view, /Current focus: node_shared/);
  assert.match(view, /Status: closed · Ended/);
  assert.match(view, /Plan: Bound the numerical error/);
  assert.match(view, /Excerpt only/);
  assert.match(view, /Assessment reference: result_a/);
  assert.match(view, /Result: result_a · Uncertainty remains/);
  assert.equal(view.match(/Shared convergence question/g).length, 1);
  assert.match(view, /node_shared part_of node_a/);
  assert.match(view, /node_shared part_of node_b/);
  assert.match(view, /Omitted: nodes 1, relations 2/);
  assert.match(view, /\/research read node_shared/);
  assert.match(view, /\/monitor job job_a/);
  assert.doesNotMatch(view, /Unrelated recent research|job_unrelated|\d+%|Status:.*succeeded/);
});

test('unbound tasks do not claim recent workspace research as their own', () => {
  const unbound = { ...snapshot, research: { entry_node_ids: [], focus_node_ids: [], nodes: [], relations: [],
    omitted: { entry_node_ids: 0, focus_node_ids: 0, nodes: 0, relations: 0, unexpanded_nodes: 0 } } };
  const view = formatMonitor('monitor/task/read', {
    task: { ...task, research: { entry_node_ids: [], focus_node_ids: [] } }, research: unbound, session_job_ids: [],
  });
  assert.match(view, /No research problems linked/);
  assert.doesNotMatch(view, /Unrelated recent research|Uncertainty remains|\/monitor job job_a/);
});

test('research snapshot errors surface through the existing Monitor error envelope', async () => {
  let calls = 0;
  const service = createMonitorService({ workspaceId: 'w', sessionId: 's',
    controller: { async read() { return task; } },
    kernel: { async execute_command() {
      calls++;
      throw Object.assign(new Error('Research unavailable'), { code: 'research_read_failed' });
    } },
  });
  const response = await service.handle({ method: 'monitor/task/read', params: { user_task_id: 'task_a' } });
  assert.deepEqual(response, { result: null, error: { code: 'research_read_failed', message: 'Research unavailable' } });
  assert.equal(calls, 1);
});

test('task controls read revision through task pages even when research is unavailable', async () => {
  const calls = [];
  const session = createTerminalSession({ workspaceId: 'w', sessionId: 's', async request(method, params) {
    calls.push([method, params]);
    if (method === 'monitor/task/read') throw new Error('Research unavailable');
    if (method === 'monitor/tasks') return params.cursor
      ? { items: [task], next_cursor: null }
      : { items: [{ user_task_id: 'task_other', revision: 1 }], next_cursor: 'page2' };
    return { task };
  } });
  for (const action of ['pause', 'resume', 'cancel']) {
    await session.monitor(`monitor/task/${action}`, { user_task_id: 'task_a', ...(action === 'cancel' ? { jobs: 'keep' } : {}) });
    assert.equal(calls.at(-1)[0], `monitor/task/${action}`);
    assert.equal(calls.at(-1)[1].expected_revision, 7);
    assert.match(calls.at(-1)[1].request_id, /^terminal-monitor-/);
    assert.equal(calls.at(-2)[1].cursor, 'page2');
  }
  assert.equal(calls.some(([method]) => method === 'monitor/task/read' || method === 'input/send'), false);
  await assert.rejects(session.monitor('monitor/task/pause', { user_task_id: 'task_missing' }), { code: 'task_not_found' });
  assert.equal(calls.at(-1)[0], 'monitor/tasks');
});

test('shared research keeps external Jobs visible without offering unusable session commands', async () => {
  const shared = { ...snapshot, running_jobs: [
    { job_id: 'job_a', node_id: 'node_shared' },
    { job_id: 'job_external', node_id: 'node_shared' },
  ] };
  const calls = [];
  const service = createMonitorService({ workspaceId: 'w', sessionId: 's',
    controller: { async read() { return task; } },
    kernel: { async execute_command(command, params) {
      calls.push([command, params]);
      if (command === 'research.read') return shared;
      assert.equal(command, 'job.list');
      assert.equal(params.session_id, 's');
      return params.cursor
        ? { jobs: [{ job_id: 'job_a', session_id: 's' }], next_cursor: null }
        : { jobs: [{ job_id: 'job_other', session_id: 's' }], next_cursor: 'page2' };
    } },
  });
  const detail = await service.handle({ method: 'monitor/task/read', params: { user_task_id: 'task_a' } });
  assert.equal(detail.error, null);
  assert.deepEqual(detail.result.session_job_ids, ['job_a']);
  assert.equal(detail.result.research, shared);
  assert.equal(calls.at(-1)[1].cursor, 'page2');
  const view = formatMonitor('monitor/task/read', detail.result);
  assert.match(view, /node_shared: \/monitor job job_a/);
  assert.match(view, /node_shared: job_external · Outside this session/);
  assert.doesNotMatch(view, /\/monitor job job_external|job_other/);
  assert.equal((await service.handle({ method: 'monitor/job/read', params: { job_id: 'job_a' } })).result.job.job_id, 'job_a');
  assert.equal((await service.handle({ method: 'monitor/job/read', params: { job_id: 'job_external' } })).error.code, 'job_not_found');
});
