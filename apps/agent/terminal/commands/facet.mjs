import { loadPi } from "../../pi/source.mjs";
import { parseSlashCommand, slashCompletions, SLASH_COMMAND_DEFINITIONS } from "../../tools/commands.mjs";
import { CLIENT_QUERIES_SERVICE_ID } from "../../pi/services/queries.mjs";
import { createStatusPresentation } from "../status/presentation.mjs";
import { createDocumentView } from "../renderers/document.mjs";
import { createCommandPresentation } from "./panel.mjs";

/** Presentation-only commands; all scientific reads execute in the worker. */
export async function createCoRAgentNativeClientFacet({ sourceRoot, session } = {}) {
  if (typeof sourceRoot !== "string" || !sourceRoot) throw new TypeError("sourceRoot is required");

  const [{ defineFacet, defineService }, { SlashCommands }, { PresentationUI }, components, { Transcript }, { theme }, { BACKGROUND_CONTEXT, withAbortSignal }] = await Promise.all([
    loadPi("chord", sourceRoot),
    loadPi("slashCommands", sourceRoot),
    loadPi("presentationUI", sourceRoot),
    loadPi("tui", sourceRoot),
    loadPi("transcript", sourceRoot),
    loadPi("theme", sourceRoot),
    loadPi("context", sourceRoot),
  ]);
  const queriesService = defineService(CLIENT_QUERIES_SERVICE_ID);
  return defineFacet({
    id: "@coragent/native-client-commands",
    setup(env) {
      const commands = env.use(SlashCommands);
      const ui = env.use(PresentationUI);
      const queries = env.use(queriesService);
      const transcript = env.use(Transcript);
      env.onActivate(() => {
        ui.setCommandPresentation(createCommandPresentation({ ...components, scope: 'Session' }));
        const status = createStatusPresentation({ session, theme, ...components, ring: process.env.TERM !== "dumb" && process.env.CORAGENT_TUI_RING !== "0" });
        const lifetime = new AbortController();
        const queryContext = withAbortSignal(lifetime.signal, BACKGROUND_CONTEXT);
        let stopped = false, refreshing = false, dirty = false, timer;
        const redraw = () => { if (!stopped) { ui.setFooter(status.footer); ui.setActivity(status.activity); } };
        const refresh = async () => {
          if (stopped || session.signal?.aborted) return;
          if (refreshing) { dirty = true; return; }
          refreshing = true; dirty = false;
          const results = await Promise.allSettled([queries.telemetry(queryContext), session.monitorStatus?.()]);
          if (!stopped && !session.signal?.aborted) {
            const [usage, monitor] = results;
            if (usage.status === "fulfilled" && usage.value.session_id === session.sessionId && usage.value.workspace_id === session.workspaceId) status.update({telemetry:usage.value.result});
            else status.update({telemetry:null});
            if (monitor.status === "fulfilled" && monitor.value?.workspace_id === session.workspaceId) status.update({monitor:monitor.value, monitorError:null});
            else status.update({monitorError:"Monitor unavailable"});
            redraw();
          }
          refreshing = false;
          if (!stopped && !session.signal?.aborted) { clearTimeout(timer); timer = setTimeout(refresh, dirty ? 250 : 5000); timer.unref?.(); }
        };
        let signature;
        env.own(transcript.state.subscribe(view => {
          status.update({view});
          const next = JSON.stringify([view.entries.at(-1)?.id, view.docs["pi.agent"], view.entries[0]?.id]);
          if (next !== signature) { signature = next; clearTimeout(timer); timer = setTimeout(refresh,250); }
          // Pi already repaints transcript changes; the components read current state at render time.
        }));
        redraw(); void refresh();
        if (session.subscribeMonitor) env.own(session.subscribeMonitor(() => { void refresh(); }, () => {
          if (stopped || session.signal?.aborted) return;
          status.update({monitorError:"Monitor unavailable"}); redraw();
        }));
        env.own(() => { stopped = true; lifetime.abort(); clearTimeout(timer); ui.setFooter(undefined); ui.setActivity(undefined); ui.setCommandPresentation(undefined); });
        const show = (title, body, context, command, scope, mode) => ui.showDocument(createDocumentView({ title, body, command, scope, mode,
          ...components, wrapText: components.wrapTextWithAnsi }), context);
        for (const command of createTerminalCommands({ ui, queries, session, show, usage: () => status.usageDetails(), monitor: () => status.monitorDetails() })) {
          env.own(commands.replace(command));
        }
      });
    },
  });
}

export function createTerminalCommands({ ui, queries, session, show, usage, monitor }) {
  return Object.values(SLASH_COMMAND_DEFINITIONS).map((definition) => ({
    name: definition.name,
    description: definition.description,
    argumentHint: definition.usage.replace(`/${definition.name}`, "").trim(),
    getArgumentCompletions(prefix) { return slashCompletions(definition.name, prefix) || []; },
    async run(args, context) {
      try {
        const invocation = parseSlashCommand(definition.name, args);
        if (definition.name === "quit") { session.quit(); return; }
        if (definition.name === "usage") {
          await show("Session usage", usage, context, 'usage', 'Session', 'panel');
          return;
        }
        if (definition.name === "monitor") {
          await show("Monitor", monitor, context, 'monitor', 'Session', 'panel');
          return;
        }
        if (definition.name === "resume") {
          let id = invocation.params.sessionId;
          if (!id) {
            const sessions = await session.list();
            if (!sessions.length) { ui.showStatus("No writable sessions in this workspace.", context); return; }
            id = await ui.select("Resume session", sessions.map((item) => ({
              value: item.session_id,
              label: item.session_id,
              description: `${item.updated_at || item.created_at || ""}${item.is_streaming ? " · running" : ""}`,
            })), session.sessionId, context);
          }
          if (id === session.sessionId) ui.showStatus("Already in this session. Research State is shared by sessions in this workspace.", context);
          else if (id) await session.resume(id);
          return;
        }
        const response = definition.name === "research"
          ? await queries.research(args, context)
          : await queries.systemPrompt(context);
        if (session.signal?.aborted) return;
        if (response.session_id !== session.sessionId) throw new Error("Query returned a different session");
        if (session.workspaceId && response.workspace_id !== session.workspaceId) throw new Error("Query returned a different workspace");
        if (response.error) throw new Error(response.error.message);
        const title = definition.name === "sys-prompt" ? "System prompt" : "Research state";
        const body = definition.name === "sys-prompt" ? formatPrompt(response.result) : formatResearch(response.result);
        await show(title, body, context, `${definition.name}${args ? ` ${args}` : ''}`, definition.name === 'research' ? 'Workspace' : 'Session', definition.name === 'sys-prompt' ? 'page' : 'auto');
      } catch (error) {
        if (!session.signal?.aborted) ui.showStatus(error instanceof Error ? error.message : String(error), context, 'error');
      }
    },
  }));
}

function formatPrompt(manifest) {
  const sources = (manifest.contributors || []).map((item) => `${item.origin}: ${item.source}`).join("\n");
  return `${manifest.effective}\n\nSources\n${sources}\n\nSHA256: ${manifest.sha256}${manifest.limitations?.length ? `\n\nLimitations\n${manifest.limitations.join("\n")}` : ""}`;
}

function formatResearch(value) {
  if (value?.schema_version !== 'research-summary/1') return formatValue(value);
  const sections = [
    ['Research overview', { workspace: value.workspace_id, revision: value.revision, state: value.lifecycle_state, progress: value.progress }],
    ['Current focus', value.focus], ['Phases and goals', value.phases], ['Claims', value.claims],
    ['Research nodes', value.nodes], ['Findings', value.findings], ['Gates', value.gates],
  ];
  return sections.map(([title, content]) => `${title}\n${'─'.repeat(title.length)}\n${formatValue(content)}`).join('\n\n')
    + '\n\nFull item: /research detail <kind> <id>';
}

function formatValue(value, indent = "") {
  if (value === null || typeof value !== "object") return String(value ?? "—");
  if (Array.isArray(value)) return value.length ? value.map((item) => `${indent}• ${formatValue(item, `${indent}  `)}`).join("\n") : "(none)";
  return Object.entries(value).filter(([key]) => key !== "schema_version").map(([key, item]) =>
    `${indent}${key.replaceAll("_", " ")}: ${item !== null && typeof item === "object" ? `\n${formatValue(item, `${indent}  `)}` : String(item ?? "—")}`,
  ).join("\n");
}
