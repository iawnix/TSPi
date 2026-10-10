/** Presentation summaries preserve full results behind the native expand control. */
import { stripVTControlCharacters } from 'node:util';

export function createCoRAgentToolRenderers({ Text, wrapTextWithAnsi }, names) {
  const presentationTheme = theme => process.env.TERM === 'dumb' || 'NO_COLOR' in process.env
    ? { fg: (_, text) => stripVTControlCharacters(text), bold: text => stripVTControlCharacters(text) } : theme;
  function textOf(result) {
    return (result.content || []).filter(block => block.type === "text").map(block => block.text).join("\n");
  }
  function bounded(text, theme, expanded) {
    if (expanded) return new Text(text, 0, 0);
    return { render(width) {
      const lines = text.split("\n").flatMap(line => wrapTextWithAnsi(line, width));
      return [...lines.slice(0, 3), ...(lines.length > 3 ? [wrapTextWithAnsi(theme.fg("muted", "… Ctrl+O: details"), width)[0]] : [])];
    }, invalidate() {} };
  }
  const shorten = value => String(value).replace(/(?:\/[^\s/]+){3,}\//g, "…/");
  return Object.fromEntries(names.map(name => [name, {
    renderCall(args, theme, context) {
      theme = presentationTheme(theme);
      const fields = ["ref", "query", "job_id", "artifact_id", "request_file"].filter(key => args[key] !== undefined);
      const suffix = fields.map(key => `${key}=${shorten(args[key])}`).join(" · ");
      const title = theme.fg("toolTitle", theme.bold(name));
      return bounded(context.expanded ? `${title}\n${JSON.stringify(args, null, 2)}` : `${title}${suffix ? ` · ${suffix}` : ""}`, theme, context.expanded);
    },
    renderResult(result, options, theme, context) {
      theme = presentationTheme(theme);
      const raw = textOf(result);
      // Pi records execution time per attempt; older and interrupted results
      // may have none. For job_start this measures submission, not the Job.
      const duration = !options.isPartial && Number.isFinite(context.durationMs) && context.durationMs >= 0
        ? `${(context.durationMs / 1000).toFixed(1)}s` : null;
      if (options.expanded) return new Text(duration === null ? raw
        : `${raw}\n\n${theme.fg("muted", `Tool execution: ${duration}`)}`, 0, 0);
      let data = result.details?.result;
      if (!data) { try { data = JSON.parse(raw); } catch {} }
      data = data?.result || data;
      const state = data?.state || data?.status;
      const label = context.isError ? "Failed" : options.isPartial ? "Running" : state || (name === "job_start" ? "Submitted" : "Done");
      const pending = /running|queued|submitted|pending|waiting|deferred|started|执行中|已提交/i.test(label);
      const failed = context.isError || /failed|error|timed_out/i.test(label);
      const color = failed ? "error" : /blocked/i.test(label) ? "warning"
        : /cancelled|canceled/i.test(label) ? "muted" : pending ? "accent" : "success";
      const details = data && !context.isError
        ? [data.job_id, data.artifact_id, data.ref, data.summary, data.reason,
          data.revision !== undefined ? `revision ${data.revision}` : undefined].filter(value => typeof value === "string").join(" · ")
        : raw;
      return bounded(`${theme.fg(color, label)}${duration === null ? "" : ` · ${theme.fg("muted", duration)}`}${details ? ` · ${shorten(details)}` : ""}\n${theme.fg("muted", "Ctrl+O: arguments and full result")}`, theme, false);
    },
  }]));
}
