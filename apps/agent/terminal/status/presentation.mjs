import { formatMonitor, taskStateLabel } from '../commands/monitor.mjs';

/** Pure presentation of durable usage, current context and operational observations. */
export const formatTokens = value => Number.isFinite(value)
  ? value >= 1e6 ? `${(value / 1e6).toFixed(1)}m` : value >= 1e3 ? `${(value / 1e3).toFixed(1)}k` : `${Math.round(value)}` : 'Unknown';

export function usageTotals(ledger) {
  const rows = Object.values(ledger?.models || {});
  if (!rows.length) return null;
  const keys = ['input', 'output', 'cacheRead', 'cacheWrite', 'reasoning', 'totalTokens'];
  return Object.fromEntries(keys.map(key => [key, rows.every(row => Number.isFinite(row[key]))
    ? rows.reduce((sum, row) => sum + (Number.isFinite(row[key]) ? row[key] : 0), 0) : null]));
}

export function contextMatches(view, telemetry) {
  const model = view?.docs?.['pi.agent']?.model;
  return telemetry && telemetry.entryId === (view?.entries?.at(-1)?.id ?? null)
    && telemetry.firstEntryId === (view?.entries?.[0]?.id ?? null)
    && model?.provider === telemetry.model?.provider && model?.modelId === telemetry.model?.modelId;
}

export function activityStatus({ monitor, monitorError, sessionId, now = Date.now() }) {
  const scoped = monitor?.session_id === sessionId ? monitor : null;
  const running = scoped?.jobs.counts?.running ?? null;
  const queued = scoped?.jobs.counts?.queued ?? null;
  const task = scoped?.task;
  const controller = scoped?.task_controller;
  const updated = Date.parse(scoped?.updated_at);
  let symbol = '✓', color = 'muted', reason;
  if (monitorError) {
    symbol = '×'; color = 'error'; reason = 'Connection lost';
  } else if (!scoped) {
    symbol = '…'; reason = 'Checking status';
  } else if (!Number.isFinite(updated) || now - updated > 30_000) {
    symbol = '!'; color = 'warning'; reason = 'Status is stale';
  } else if (controller.error) {
    symbol = '×'; color = 'error'; reason = `Continuation error: ${controller.error.code}`;
  } else if (!task) {
    reason = 'No current task';
  } else if (controller.last_checked_at === null) {
    symbol = '…'; reason = 'Checking recovery';
  } else if (['active', 'waiting'].includes(task.state) && now - Date.parse(controller.last_checked_at) > Math.max(30_000, controller.check_interval_ms * 3)) {
    symbol = '!'; color = 'warning'; reason = 'Continuation check overdue';
  } else if (task.state === 'blocked') {
    symbol = '!'; color = 'warning'; reason = scoped.execution.state === 'running'
      ? 'Responding · Task blocked' : 'Needs attention';
  } else if (task.state === 'active' && !scoped.automatic_continuation_enabled && scoped.execution.state === 'idle') {
    symbol = '!'; color = 'warning'; reason = 'Automatic continuation off';
  } else if (task.state === 'active' && scoped.execution.state === 'idle') {
    symbol = '…'; reason = task.continuation.reservation ? 'Preparing continuation' : 'Checking continuation';
  } else {
    reason = taskStateLabel(task.state);
    if (task.state === 'paused') symbol = 'Ⅱ';
    if (task.state === 'recovering') symbol = '…';
  }
  const suffix = ` · ${running ?? '—'} jobs running${reason === 'Waiting for compute' && scoped.automatic_continuation_enabled ? ' · Continues when ready' : ''}`;
  return { text: `Monitor ${symbol} · ${reason}${suffix}`, symbol, color, reason, running, queued };
}

export function createStatusPresentation({ session, theme, truncateToWidth, visibleWidth, ring = true,
  monochrome = process.env.TERM === 'dumb' || 'NO_COLOR' in process.env }) {
  let view, telemetry, monitor, monitorError;
  const fit = (text, width) => truncateToWidth(text, Math.max(1, width));
  const modelLabel = () => {
    const agent = view?.docs?.['pi.agent'] || {};
    return { model: agent.model?.modelId || 'Unknown', provider: agent.model?.provider,
      thinking: agent.thinkingLevel || 'off' };
  };
  const footer = {
    invalidate() {},
    render(width) {
      const w = Math.max(1, width - 2); const { model, provider, thinking } = modelLabel();
      const identity = `${provider ? `${provider}/` : ''}${model} · Thinking: ${thinking} · Workspace: ${session.workspaceId}`;
      const variants = [
        `${identity} · Session: ${session.sessionId}`,
        `${identity} · Session: ${session.sessionId.slice(0,8)}…`,
        `${model} · ${thinking} · ${session.workspaceId} · ${session.sessionId.slice(0,8)}…`,
        `${model} · ${thinking} · ${session.workspaceId}`,
      ];
      const suffix = ` · ${thinking} · ${session.workspaceId}`;
      const first = variants.find(value => visibleWidth(value) <= w)
        || `${fit(model, Math.max(1,w-visibleWidth(suffix)))}${suffix}`;
      const current = contextMatches(view, telemetry);
      const tokens = current ? telemetry.contextTokens : null;
      const capacity = current ? telemetry.contextWindow : null;
      const percent = Number.isFinite(tokens) && capacity > 0 ? tokens / capacity * 100 : null;
      const icon = ring && percent !== null ? `${['○','◔','◑','◕','●'][Math.min(4, Math.round(percent / 25))]} ` : '';
      const context = `${icon}Context ${tokens === null ? 'Unknown' : `${formatTokens(tokens)}`}/${formatTokens(capacity)}${percent === null ? '' : ` (${percent.toFixed(0)}%)`}`;
      const total = formatTokens(usageTotals(view?.docs?.['pi.usage'])?.totalTokens);
      const second = `${context} · Total tokens: ${total}`;
      const short = `${icon}Ctx ${percent === null ? '?' : `${percent.toFixed(0)}%`} · Tokens: ${total}`;
      const color = percent >= 90 ? 'error' : percent >= 70 ? 'warning' : 'muted';
      return [` ${theme.fg('muted',fit(first,w))}`, ` ${theme.fg(color,fit(visibleWidth(second) <= w ? second : short,w))}`];
    },
  };
  const activity = { invalidate() {}, render(width) {
    const state = activityStatus({telemetry,monitor,monitorError,sessionId:session.sessionId});
    const text = monochrome ? state.text
      : `${theme.fg('muted','Monitor ')}${theme.fg(state.color,state.symbol)}${theme.fg('muted',state.text.slice(`Monitor ${state.symbol}`.length))}`;
    return width > 0 ? [truncateToWidth(` ${text}`,width)] : [];
  } };
  return { footer, activity,
    update(value) {
      if ('view' in value) view = value.view;
      if ('telemetry' in value) telemetry = value.telemetry;
      if ('monitor' in value) monitor = value.monitor;
      if ('monitorError' in value) {
        monitorError = value.monitorError;
      }
    },
    usageDetails() {
      const totals = usageTotals(view?.docs?.['pi.usage']);
      const count = value => Number.isFinite(value) ? value.toLocaleString('en-US') : '—';
      const current = contextMatches(view, telemetry);
      const rows = Object.entries(view?.docs?.['pi.usage']?.models || {})
        .map(([model, usage]) => `${model}: ${count(usage.totalTokens)}`);
      return [`Total tokens: ${count(totals?.totalTokens)}`,
        `Input: ${count(totals?.input)} · Output: ${count(totals?.output)}`,
        `Cache read: ${count(totals?.cacheRead)} · Cache write: ${count(totals?.cacheWrite)}`,
        `Reasoning: ${count(totals?.reasoning)}`,
        `Context: ${count(current ? telemetry.contextTokens : null)} / ${count(current ? telemetry.contextWindow : null)}`,
        ...(rows.length ? ['', 'By model', ...rows] : [])].join('\n');
    },
    monitorDetails() {
      const state = activityStatus({monitor,monitorError,sessionId:session.sessionId});
      return [`Status: ${state.text}`,
        ...(monitor ? [formatMonitor('monitor/overview', monitor)] : []),
        `Last update: ${monitor?.updated_at || '—'}`,
        ...(monitorError ? [`Connection: ${monitorError}`] : [])].join('\n');
    },
  };
}
