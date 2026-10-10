/** Request-only bounded control projection. Full facts remain in task_read. */
export function projectUserTask(task) {
  if (!task) return null;
  let truncated = false;
  // Bound serialized bytes, including JSON escapes and multibyte text.
  const text = (value, bytes) => {
    if (value === null) return null;
    if (Buffer.byteLength(JSON.stringify(value)) <= bytes) return value;
    truncated = true;
    let low = 0, high = value.length;
    while (low < high) {
      const middle = Math.ceil((low + high) / 2);
      if (Buffer.byteLength(JSON.stringify(value.slice(0, middle))) <= bytes) low = middle;
      else high = middle - 1;
    }
    return value.slice(0, low);
  };
  const sources = task.sources.length <= 4 ? task.sources : [task.sources[0], ...task.sources.slice(-3)];
  const criteria = task.criteria.slice(0, 8);
  const projection = {
    user_task_id: task.user_task_id, title: text(task.title, 256), objective: text(task.objective, 2048),
    state: task.state, reason: text(task.reason, 512), revision: task.revision, control_epoch: task.control_epoch,
    research: { entry_node_ids: task.research.entry_node_ids.slice(0, 8), focus_node_ids: task.research.focus_node_ids.slice(0, 8),
      entry_nodes_omitted: Math.max(0, task.research.entry_node_ids.length - 8),
      focus_nodes_omitted: Math.max(0, task.research.focus_node_ids.length - 8) },
    criteria: criteria.map(item => ({ id: text(item.id, 128), description: text(item.description, 256) })),
    criteria_omitted: task.criteria.length - criteria.length,
    sources: sources.map(source => ({ submission_id: source.submission_id, entry_id: source.entry_id,
      text: text(source.text, 384) })),
    sources_omitted: task.sources.length - sources.length,
    wait: task.wait ? { mode: task.wait.mode, job_ids: task.wait.job_ids.slice(0, 8).map(id => text(id, 128)),
      jobs_omitted: Math.max(0, task.wait.job_ids.length - 8) } : null,
    progress: task.progress ? { summary: text(task.progress.summary ?? null, 512), at: task.progress.at,
      evidence_refs: task.progress.evidence_refs.slice(0, 8).map(ref => text(ref, 128)),
      evidence_omitted: Math.max(0, task.progress.evidence_refs.length - 8) } : null,
    continuation: { sequence: task.continuation.sequence, no_progress: task.continuation.no_progress },
  };
  projection.projection_truncated = truncated || projection.sources_omitted > 0 || projection.criteria_omitted > 0
    || projection.research.entry_nodes_omitted > 0 || projection.research.focus_nodes_omitted > 0
    || (projection.wait?.jobs_omitted || 0) > 0 || (projection.progress?.evidence_omitted || 0) > 0;
  projection.required_action = "Full original requirements, criteria, and evidence remain in task_read. Read omitted details before revising scope or claiming completion; excerpts never relax authorization limits.";
  return projection;
}
