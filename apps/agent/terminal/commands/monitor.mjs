const STATES = {
  active: 'Researching', waiting: 'Waiting for compute', paused: 'Paused', blocked: 'Needs attention',
  completing: 'Preparing delivery', completed: 'Completed', cancelled: 'Cancelled', recovering: 'Checking recovery',
};

export const taskStateLabel = state => STATES[state] || 'Unknown';
const text = value => value === null || value === undefined || value === '' ? '—' : String(value);
const lines = value => value.length ? value.join('\n') : '(none)';

export function formatTask(task) {
  if (!task) return 'No current task';
  return [
    `Task: ${task.title} · ${taskStateLabel(task.state)}`,
    `Goal: ${task.objective}`,
    `Progress: ${text(task.progress?.summary)}`,
    ...(task.wait ? [`Waiting: ${task.wait.job_ids.join(', ')} (${task.wait.mode})`] : []),
    ...(task.reason ? [`Reason: ${task.reason}`] : []),
    `Delivery criteria:\n${lines(task.criteria.map(item => `• ${item.description}`))}`,
    `Updated: ${task.updated_at}`,
    '', `/monitor task ${task.user_task_id}`,
    `/monitor jobs --task ${task.user_task_id}`,
    `/monitor runs --task ${task.user_task_id}`,
    ...(['active', 'waiting', 'blocked'].includes(task.state) ? [`/monitor task pause ${task.user_task_id}`] : []),
    ...(['paused', 'blocked'].includes(task.state) ? [`/monitor task resume ${task.user_task_id}`] : []),
  ].join('\n');
}

function jobRow(job) {
  return `${job.job_id} · ${text(job.state)} · Collection: ${text(job.collection_state)} · Analysis: Not recorded`;
}

function nextPage(response, command, params) {
  if (!response.next_cursor) return '';
  return `\n\nNext page: /monitor ${command}${params.user_task_id ? ` --task ${params.user_task_id}` : ''}${params.limit ? ` --limit ${params.limit}` : ''} --cursor ${response.next_cursor}`;
}

function formatResearch(snapshot, sessionJobIds) {
  const research = snapshot.research;
  const labels = { open: 'Open', paused: 'Paused', closed: 'Ended' };
  const nodes = research.nodes.map(node => {
    const detail = snapshot.nodes.find(item => item.id === node.id);
    return [
      `• ${node.id} · ${node.title}`,
      `  Status: ${node.status} · ${labels[node.status]} · Revision: ${node.revision}`,
      `  Plan: ${text(node.plan)}`,
      ...(node.content_omitted ? ['  Excerpt only; read the problem for its complete plan.'] : []),
      `  Assessment reference: ${text(node.assessment_ref)}`,
      ...(detail?.recent_results || []).map(result => `  Result: ${result.id} · ${result.summary}`),
      `  Read: /research read ${node.read.ref}`,
    ].join('\n');
  });
  const nodeIds = new Set(research.nodes.map(node => node.id));
  const jobs = [...snapshot.running_jobs, ...snapshot.uncollected_jobs].filter(job => nodeIds.has(job.node_id));
  const sessionJobs = new Set(sessionJobIds);
  const omitted = Object.entries(research.omitted).filter(([, count]) => count > 0);
  return [
    'Research problems',
    `Entry references: ${research.entry_node_ids.join(', ') || '—'}`,
    `Current focus: ${research.focus_node_ids.join(', ') || '—'}`,
    ...(nodes.length ? nodes : [omitted.length ? 'Research details omitted from this snapshot.' : 'No research problems linked.']),
    '', 'Relations (references to the same problems)',
    lines(research.relations.map(edge => `• ${edge.source} ${edge.kind} ${edge.target}`)),
    ...(jobs.length ? ['', 'Related compute jobs', ...jobs.map(job => sessionJobs.has(job.job_id)
      ? `${job.node_id}: /monitor job ${job.job_id}`
      : `${job.node_id}: ${job.job_id} · Outside this session`)] : []),
    ...(omitted.length ? ['', `Omitted: ${omitted.map(([key, count]) => `${key.replaceAll('_', ' ')} ${count}`).join(', ')}. Read the referenced problems for more detail.`] : []),
    '', `Research snapshot: ${snapshot.sequence}. Ended problems do not imply verified conclusions or task completion.`,
  ].join('\n');
}

/** Explicit fields keep execution internals and tool payloads out of the task overview. */
export function formatMonitor(method, response, params = {}) {
  switch (method) {
    case 'monitor/overview':
      return [formatTask(response.task), '',
        `Automatic continuation: ${response.automatic_continuation_enabled ? 'On' : 'Off'}`,
        '', 'Compute jobs', lines(response.jobs.items.map(jobRow)),
        ...(response.jobs.next_cursor ? ['More jobs: /monitor jobs'] : []),
        '', '/monitor tasks · /monitor jobs · /monitor runs · /monitor health'].join('\n');
    case 'monitor/tasks':
      return lines(response.items.map(task => `${task.user_task_id} · ${task.title} · ${taskStateLabel(task.state)}`))
        + '\n\nDetails: /monitor task <task-id>' + nextPage(response, 'tasks', params);
    case 'monitor/task/read':
      return formatTask(response.task) + '\n\n' + formatResearch(response.research, response.session_job_ids);
    case 'monitor/task/pause':
    case 'monitor/task/resume':
      return formatTask(response.task);
    case 'monitor/task/cancel':
      return formatTask(response.task) + `\n\nCompute jobs: ${response.jobs_policy === 'keep' ? 'Kept running' : 'Cancellation requested'}`
        + (response.job_cancellations ? '\n' + formatFields(response.job_cancellations) : '');
    case 'monitor/jobs':
      return lines(response.items.map(jobRow)) + '\n\nDetails: /monitor job <job-id>' + nextPage(response, 'jobs', params);
    case 'monitor/job/read':
    case 'monitor/job/cancel':
      return [`Job: ${response.job.job_id}`, `Execution: ${text(response.job.state)}`,
        `Collection: ${text(response.job.collection_state)}`, 'Analysis: Not recorded',
        `User task: ${text(response.job.user_task_id)}`, `Platform: ${text(response.job.platform)}`,
        ...(response.job.error ? [`Error: ${text(response.job.error)}`] : []),
        ...(response.job.result_receipt ? ['Receipt:\n' + formatFields(response.job.result_receipt)] : []),
        '', `/monitor job cancel ${response.job.job_id}`].join('\n');
    case 'monitor/runs':
      return lines(response.items.map(run => `${run.run_id} · ${text(run.producer)} · ${text(run.state)} · ${text(run.generation_count)} model calls`))
        + '\n\nExecution details: /monitor run <run-id>' + nextPage(response, 'runs', params);
    case 'monitor/run/read':
      return [`Execution: ${response.run.run_id}`, `User task: ${text(response.run.user_task_id)}`, '',
        lines(response.items.map(item => [
          `${item.kind === 'pi.generation' ? 'Model request' : item.kind === 'pi.tool' ? 'Tool call' : item.kind}${item.tool_name ? ': ' + item.tool_name : ''} · ${item.state}${item.outcome ? ' / ' + item.outcome : ''}`,
          `  Started: ${text(item.started_at)} · Ended: ${text(item.ended_at)}`,
          ...(item.error ? [`  Error: ${item.error.code}`,
            ...(item.error.failure_class ? [`  Class: ${item.error.failure_class}`] : []),
            ...(typeof item.error.retryable === 'boolean' ? [`  Retryable: ${item.error.retryable ? 'Yes' : 'No'}`] : []),
            ...(item.error.action_outcome ? [`  Action outcome: ${item.error.action_outcome}`] : [])] : []),
          `  Pi task: ${item.pi_task_id}${item.result_entry_id ? ' · Result entry: ' + item.result_entry_id : ''}`,
        ].join('\n'))),
      ].join('\n') + nextPage(response, `run ${params.run_id}`, params);
    case 'monitor/health':
      return formatFields(response);
    default: throw new Error(`Unsupported Monitor view: ${method}`);
  }
}

// These views receive only bounded service-owned diagnostic projections.
function formatFields(value, indent = '') {
  if (value === null || typeof value !== 'object') return text(value);
  if (Array.isArray(value)) return lines(value.map(item => `${indent}• ${formatFields(item, indent + '  ')}`));
  return Object.entries(value).filter(([key]) => key !== 'schema_version').map(([key, item]) =>
    `${indent}${key.replaceAll('_', ' ')}: ${item !== null && typeof item === 'object' ? '\n' + formatFields(item, indent + '  ') : text(item)}`).join('\n');
}
