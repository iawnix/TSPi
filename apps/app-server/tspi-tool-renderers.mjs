/** Presentation summaries preserve full results behind the native expand control. */
export function createTspiToolRenderers({ Text, wrapTextWithAnsi }, names) {
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
      const fields = ["mode", "nodeId", "jobId", "artifactId", "requestFile"].filter(key => args[key] !== undefined);
      const suffix = fields.map(key => `${key}=${shorten(args[key])}`).join(" · ");
      const title = theme.fg("toolTitle", theme.bold(name));
      return bounded(context.expanded ? `${title}\n${JSON.stringify(args, null, 2)}` : `${title}${suffix ? ` · ${suffix}` : ""}`, theme, context.expanded);
    },
    renderResult(result, options, theme, context) {
      const raw = textOf(result);
      if (options.expanded) return new Text(raw, 0, 0);
      let data = result.details?.result;
      if (!data) { try { data = JSON.parse(raw); } catch {} }
      data = data?.result || data;
      const state = data?.state || data?.status || data?.disposition || data?.lifecycle;
      const label = context.isError ? "Failed" : options.isPartial ? "Running" : state || (name === "job_start" ? "Submitted" : "Done");
      const pending = /running|queued|submitted|pending|waiting|deferred|started|执行中|已提交/i.test(label);
      const failed = context.isError || /failed|blocked|error|cancelled/i.test(label);
      const color = failed ? "error" : pending ? "warning" : "success";
      const details = data && !context.isError
        ? [data.job_id, data.attempt_id, data.artifact_id, data.node_id, data.summary, data.reason,
          data.revision !== undefined ? `revision ${data.revision}` : undefined].filter(value => typeof value === "string").join(" · ")
        : raw;
      return bounded(`${theme.fg(color, label)}${details ? ` · ${shorten(details)}` : ""}\n${theme.fg("muted", "Ctrl+O: arguments and full result")}`, theme, false);
    },
  }]));
}
