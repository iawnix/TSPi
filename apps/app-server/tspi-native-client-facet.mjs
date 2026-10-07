import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { parseSlashCommand, slashCompletions, SLASH_COMMAND_DEFINITIONS } from "../../packages/agent-runtime/host-api/commands.mjs";
import { CLIENT_QUERIES_SERVICE_ID } from "./tspi-client-queries.mjs";
import { createStatusPresentation } from "./tspi-status-presentation.mjs";
import { createDocumentView } from "./tspi-document-view.mjs";

/** Presentation-only commands; all scientific reads execute in the worker. */
export async function createTspiNativeClientFacet({ sourceRoot, session } = {}) {
  if (typeof sourceRoot !== "string" || !sourceRoot) throw new TypeError("sourceRoot is required");
  const fromSource = (relative) => import(pathToFileURL(join(sourceRoot, relative)).href);
  const [{ defineFacet, defineService }, { SlashCommands }, { PresentationUI }, components, { Transcript }, { theme }, { BACKGROUND_CONTEXT, withAbortSignal }] = await Promise.all([
    fromSource("packages/chord/src/index.ts"),
    fromSource("packages/coding-agent/src/experimental/services/slash-commands.ts"),
    fromSource("packages/coding-agent/src/experimental/services/presentation-ui.ts"),
    fromSource("packages/tui/src/index.ts"),
    fromSource("packages/coding-agent/src/experimental/services/transcript.ts"),
    fromSource("packages/coding-agent/src/modes/interactive/theme/theme.ts"),
    fromSource("packages/chord/src/context/index.ts"),
  ]);
  const queriesService = defineService(CLIENT_QUERIES_SERVICE_ID);
  return defineFacet({
    id: "@tspi/native-client-commands",
    setup(env) {
      const commands = env.use(SlashCommands);
      const ui = env.use(PresentationUI);
      const queries = env.use(queriesService);
      const transcript = env.use(Transcript);
      env.onActivate(() => {
        const status = createStatusPresentation({ session, theme, ...components, ring: process.env.TERM !== "dumb" && process.env.TSPI_TUI_RING !== "0" });
        const lifetime = new AbortController();
        const queryContext = withAbortSignal(lifetime.signal, BACKGROUND_CONTEXT);
        let stopped = false, refreshing = false, dirty = false, timer;
        const redraw = () => { if (!stopped) { ui.setFooter(status.footer); ui.setActivity(status.activity); } };
        const refresh = async () => {
          if (stopped) return;
          if (refreshing) { dirty = true; return; }
          refreshing = true; dirty = false;
          const results = await Promise.allSettled([queries.telemetry(queryContext), session.monitorStatus?.()]);
          if (!stopped) {
            const [usage, monitor] = results;
            if (usage.status === "fulfilled" && usage.value.session_id === session.sessionId && usage.value.workspace_id === session.workspaceId) status.update({telemetry:usage.value.result});
            else status.update({telemetry:null});
            if (monitor.status === "fulfilled") status.update({monitor:monitor.value, monitorError:null});
            else status.update({monitorError:"Monitor unavailable"});
            redraw();
          }
          refreshing = false;
          if (!stopped) { clearTimeout(timer); timer = setTimeout(refresh, dirty ? 250 : 5000); timer.unref?.(); }
        };
        let signature;
        env.own(transcript.state.subscribe(view => {
          status.update({view});
          const next = JSON.stringify([view.entries.at(-1)?.id, view.docs["pi.agent"], view.entries[0]?.id]);
          if (next !== signature) { signature = next; clearTimeout(timer); timer = setTimeout(refresh,250); }
          // Pi already repaints transcript changes; the components read current state at render time.
        }));
        redraw(); void refresh();
        if (session.subscribeMonitor) env.own(session.subscribeMonitor(() => { void refresh(); }, () => { status.update({monitorError:"Monitor unavailable"}); redraw(); }));
        env.own(() => { stopped = true; lifetime.abort(); clearTimeout(timer); ui.setFooter(undefined); ui.setActivity(undefined); });
        const show = (title, body, context) => ui.showDocument(createDocumentView({ title, body,
          wrapText: components.wrapTextWithAnsi, truncateToWidth: components.truncateToWidth, matchesKey: components.matchesKey, theme }), context);
        for (const command of createTerminalCommands({ ui, queries, session, show, usage: () => status.details() })) {
          env.own(commands.replace(command));
        }
      });
    },
  });
}

export function createTerminalCommands({ ui, queries, session, show, usage }) {
  let pending = false;
  return Object.values(SLASH_COMMAND_DEFINITIONS).map((definition) => ({
    name: definition.name,
    description: definition.description,
    argumentHint: definition.usage.replace(`/${definition.name}`, "").trim(),
    getArgumentCompletions(prefix) { return slashCompletions(definition.name, prefix) || []; },
    async run(args, context) {
      try {
        const invocation = parseSlashCommand(definition.name, args);
        if (definition.name === "quit") { session.quit(); return; }
        if (pending) { ui.showStatus("Another terminal command is still open. Close it before continuing.", context); return; }
        pending = true;
        try {
          if (definition.name === "usage") {
            await show("Usage", usage(), context);
            return;
          }
          if (definition.name === "resume") {
            let id = invocation.params.sessionId;
            if (!id) {
              const sessions = await session.list();
              if (!sessions.length) { ui.showStatus("No writable sessions in this workspace.", context); return; }
              id = await ui.select("Resume session", sessions.map((item) => ({
                value: item.session_id,
                label: `${item.session_id}${item.session_id === session.sessionId ? " (current)" : ""}`,
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
          const body = definition.name === "sys-prompt" ? formatPrompt(response.result) : formatValue(response.result);
          await show(title, body, context);
        } finally { pending = false; }
      } catch (error) {
        if (!session.signal?.aborted) ui.showStatus(`/${definition.name}: ${error instanceof Error ? error.message : String(error)}`, context);
      }
    },
  }));
}

function formatPrompt(manifest) {
  const sources = (manifest.contributors || []).map((item) => `${item.origin}: ${item.source}`).join("\n");
  return `${manifest.effective}\n\nSources\n${sources}\n\nSHA256: ${manifest.sha256}${manifest.limitations?.length ? `\n\nLimitations\n${manifest.limitations.join("\n")}` : ""}`;
}

function formatValue(value, indent = "") {
  if (value === null || typeof value !== "object") return String(value ?? "—");
  if (Array.isArray(value)) return value.length ? value.map((item) => `${indent}• ${formatValue(item, `${indent}  `)}`).join("\n") : "(none)";
  return Object.entries(value).filter(([key]) => key !== "schema_version").map(([key, item]) =>
    `${indent}${key.replaceAll("_", " ")}: ${item !== null && typeof item === "object" ? `\n${formatValue(item, `${indent}  `)}` : String(item ?? "—")}`,
  ).join("\n");
}
