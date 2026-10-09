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

const ACTIVE_JOB_STATES = new Set(['running', 'queued', 'held', 'pending', 'submitted']);

export function activityStatus({ monitor, monitorError, monitorErrorSince, telemetry, sessionId, now = Date.now() }) {
  const rows = (monitor?.monitors || []).filter(row => row.session_id === sessionId);
  const pending = (monitor?.pending_deliveries || []).filter(row => row.session_id === sessionId);
  const active = rows.filter(row => ACTIVE_JOB_STATES.has(row.last_state));
  const running = active.filter(row => row.last_state === 'running').length;
  const queued = active.length - running;
  const relevant = active.length > 0 || pending.length > 0 || (telemetry?.research?.running_jobs?.length || 0) > 0;
  const health = monitor?.host_worker_health;
  const supervisor = monitor?.supervisor_health;
  const lastPoll = Date.parse(health?.last_successful_poll);
  const staleAfter = Math.max(30_000, (health?.poll_interval_ms || 5000) * 3);
  let symbol = '✓', color = 'muted', reason = 'Healthy';
  if (pending.some(row => row.error) || health?.last_error || (supervisor?.state && supervisor.state !== 'running')) {
    symbol = '×'; color = 'error';
    reason = pending.find(row => row.error)?.error || health?.last_error || `Shared monitor supervisor: ${supervisor.state}`;
  } else if (monitorError && Number.isFinite(monitorErrorSince) && now - monitorErrorSince >= 30_000) {
    symbol = '×'; color = 'error'; reason = 'Monitor unavailable for at least 30 seconds';
  } else if (health && (!Number.isFinite(lastPoll) || now - lastPoll > staleAfter)) {
    symbol = '!'; color = 'warning'; reason = 'Last successful poll is missing or stale';
  } else if (active.some(row => row.enabled === false)) {
    symbol = '!'; color = 'warning';
    reason = `${active.filter(row => row.enabled === false).length} active job monitor(s) paused`;
  } else if (monitor && !rows.length && relevant) {
    symbol = '!'; color = 'warning'; reason = 'No job monitor registered for this session';
  } else if (monitorError || !health || !supervisor?.state) {
    symbol = '…'; reason = monitorError ? 'Reconnecting to monitor' : 'Checking monitor health';
  }
  return { text: relevant ? `Monitor ${symbol}${pending.length ? ` · ↑${pending.length}` : ''}` : '',
    symbol, color, reason, running, queued, pending: pending.length };
}

export function createStatusPresentation({ session, theme, truncateToWidth, visibleWidth, ring = true,
  monochrome = process.env.TERM === 'dumb' || 'NO_COLOR' in process.env }) {
  let view, telemetry, monitor, monitorError, monitorErrorSince;
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
    const state = activityStatus({telemetry,monitor,monitorError,monitorErrorSince,sessionId:session.sessionId});
    if (!state.text) return [];
    const text = monochrome ? state.text
      : `${theme.fg('muted','Monitor ')}${theme.fg(state.color,state.symbol)}${theme.fg('muted',state.pending ? ` · ↑${state.pending}` : '')}`;
    return width > 0 ? [truncateToWidth(` ${text}`,width)] : [];
  } };
  return { footer, activity,
    update(value) {
      if ('view' in value) view = value.view;
      if ('telemetry' in value) telemetry = value.telemetry;
      if ('monitor' in value) monitor = value.monitor;
      if ('monitorError' in value) {
        if (value.monitorError && !monitorError) monitorErrorSince = Date.now();
        if (!value.monitorError) monitorErrorSince = undefined;
        monitorError = value.monitorError;
      }
    },
    details() {
      const totals = usageTotals(view?.docs?.['pi.usage']);
      const state = activityStatus({telemetry,monitor,monitorError,monitorErrorSince,sessionId:session.sessionId});
      const rows = Object.entries(view?.docs?.['pi.usage']?.models || {}).map(([model,usage]) => `${model}: ${formatTokens(usage.totalTokens)} tokens`);
      return ['Session usage', `Workspace: ${session.workspaceId}`, `Session: ${session.sessionId}`, '',
        ...Object.entries({input:'Input tokens',output:'Output tokens',cacheRead:'Cache read',cacheWrite:'Cache write',reasoning:'Reasoning tokens',totalTokens:'Total tokens'})
          .map(([key,label]) => `${label}: ${totals?.[key] ?? 'Unknown'}`), '',
        ...rows, '', 'Totals are provider-reported model usage for this session, including compaction calls.',
        'Cached input is recorded separately. Reasoning may be included in output; do not add it again.',
        'Tool usage is excluded from model totals. Missing provider counters are unknown.',
        'Context is Pi’s compaction-aware estimate, not an exact tokenizer count or a billing total.',
        '', 'Monitor', `Status: ${state.symbol} ${state.reason}`,
        `This session: ${state.running} running · ${state.queued} queued · ${state.pending} pending deliveries`,
        '↑N counts monitor events awaiting delivery, not events already received by the Agent.',
        `Last successful poll: ${monitor?.host_worker_health?.last_successful_poll || 'Unknown'}`,
        ...(monitorError ? [`Connection: ${monitorError}`] : []),
        'Worker and supervisor health are shared across workspaces.',
        JSON.stringify({worker:monitor?.host_worker_health || null,supervisor:monitor?.supervisor_health || null},null,2)].join('\n');
    },
  };
}
