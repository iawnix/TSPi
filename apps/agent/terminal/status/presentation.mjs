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

export function activityStatus({ view, monitor, monitorError, telemetry, sessionId, now = Date.now() }) {
  const live = view?.docs?.['pi.live'] || {};
  const rows = (monitor?.monitors || []).filter(row => row.session_id === sessionId);
  const pending = (monitor?.pending_deliveries || []).filter(row => row.session_id === sessionId);
  const running = rows.filter(row => row.last_state === 'running').length;
  const waiting = rows.filter(row => ['queued', 'held', 'pending', 'submitted'].includes(row.last_state)).length;
  const relevant = running + waiting > 0 || pending.length > 0 || (telemetry?.research?.running_jobs?.length || 0) > 0;
  const parts = []; let color = 'muted';
  if (pending.length) {
    parts.push('Wake pending delivery'); color = 'warning';
  }
  if (relevant && !live.run) {
    if (running + waiting) parts.push(`Waiting for jobs · ${running} running${waiting ? ` · ${waiting} queued` : ''}`);
    else if (!pending.length) parts.push('Waiting for external work');
  }
  if (relevant) {
    const health = monitor?.host_worker_health;
    if (monitorError || health?.last_error || monitor?.supervisor_health?.state !== 'running') {
      parts.push(monitorError ? 'Monitor unavailable' : 'Monitor error'); color = 'error';
    } else if (!Number.isFinite(Date.parse(health?.last_successful_poll)) || now - Date.parse(health.last_successful_poll) > Math.max(30_000, (health.poll_interval_ms || 5000) * 3)) {
      parts.push('Monitor status stale'); color = 'warning';
    } else if (rows.some(row => !row.enabled && ['running','queued','held'].includes(row.last_state))) {
      parts.push('Monitor disabled'); color = 'warning';
    } else if (!rows.length) { parts.push('No job monitor registered'); color = 'warning'; }
    else parts.push('Monitor active');
  }
  return { text: parts.join(' · '), color };
}

export function createStatusPresentation({ session, theme, truncateToWidth, visibleWidth, ring = true }) {
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
    const state = activityStatus({view,telemetry,monitor,monitorError,sessionId:session.sessionId});
    return state.text ? [` ${theme.fg(state.color,fit(state.text,width-2))}`] : [];
  } };
  return { footer, activity,
    update(value) {
      if ('view' in value) view = value.view;
      if ('telemetry' in value) telemetry = value.telemetry;
      if ('monitor' in value) monitor = value.monitor;
      if ('monitorError' in value) monitorError = value.monitorError;
    },
    details() {
      const totals = usageTotals(view?.docs?.['pi.usage']);
      const rows = Object.entries(view?.docs?.['pi.usage']?.models || {}).map(([model,usage]) => `${model}: ${formatTokens(usage.totalTokens)} tokens`);
      return ['Session usage', `Workspace: ${session.workspaceId}`, `Session: ${session.sessionId}`, '',
        ...Object.entries({input:'Input tokens',output:'Output tokens',cacheRead:'Cache read',cacheWrite:'Cache write',reasoning:'Reasoning tokens',totalTokens:'Total tokens'})
          .map(([key,label]) => `${label}: ${totals?.[key] ?? 'Unknown'}`), '',
        ...rows, '', 'Totals are provider-reported model usage for this session, including compaction calls.',
        'Cached input is recorded separately. Reasoning may be included in output; do not add it again.',
        'Tool usage is excluded from model totals. Missing provider counters are unknown.',
        'Context is Pi’s compaction-aware estimate, not an exact tokenizer count or a billing total.',
        '', 'Monitor (shared worker)', monitorError || JSON.stringify(monitor?.host_worker_health || null,null,2)].join('\n');
    },
  };
}
