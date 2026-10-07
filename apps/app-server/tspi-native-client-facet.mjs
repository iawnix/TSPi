import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { parseSlashCommand, slashCompletions, SLASH_COMMAND_DEFINITIONS } from "../../packages/agent-runtime/host-api/commands.mjs";
import { CLIENT_QUERIES_SERVICE_ID } from "./tspi-client-queries.mjs";

/** Presentation-only commands; all scientific reads execute in the worker. */
export async function createTspiNativeClientFacet({ sourceRoot, session } = {}) {
  if (typeof sourceRoot !== "string" || !sourceRoot) throw new TypeError("sourceRoot is required");
  const fromSource = (relative) => import(pathToFileURL(join(sourceRoot, relative)).href);
  const [{ defineFacet, defineService }, { SlashCommands }, { PresentationUI }, { wrapTextWithAnsi }] = await Promise.all([
    fromSource("packages/chord/src/index.ts"),
    fromSource("packages/coding-agent/src/experimental/services/slash-commands.ts"),
    fromSource("packages/coding-agent/src/experimental/services/presentation-ui.ts"),
    fromSource("packages/tui/src/index.ts"),
  ]);
  const queriesService = defineService(CLIENT_QUERIES_SERVICE_ID);
  return defineFacet({
    id: "@tspi/native-client-commands",
    setup(env) {
      const commands = env.use(SlashCommands);
      const ui = env.use(PresentationUI);
      const queries = env.use(queriesService);
      env.onActivate(() => {
        for (const command of createTerminalCommands({ ui, queries, session, wrapText: wrapTextWithAnsi })) {
          env.own(commands.replace(command));
        }
      });
    },
  });
}

export function createTerminalCommands({ ui, queries, session, wrapText = (text) => text.split("\n") }) {
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
          const title = `${definition.name} · ${response.workspace_id} · ${response.session_id}`;
          const body = definition.name === "sys-prompt" ? formatPrompt(response.result) : formatValue(response.result);
          await showDocument(ui, title, body, context, wrapText, session.signal);
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

// Use Pi's own selector, including its wrapping and focus handling. No second
// overlay renderer. Reserve space for the title and page navigation on small TTYs.
async function showDocument(ui, title, body, context, wrapText, signal) {
  const width = Math.max(10, (process.stdout.columns || 80) - 4);
  const lines = body.split("\n").flatMap((line) => wrapText(line, width));
  const pageSize = Math.max(1, Math.min(16, (process.stdout.rows || 24) - 12));
  const pages = Math.max(1, Math.ceil(lines.length / pageSize));
  let page = 0;
  while (!signal?.aborted) {
    const items = [
      ...(page + 1 < pages ? [{ value: "next", label: "Next page" }] : []),
      ...(page > 0 ? [{ value: "previous", label: "Previous page" }] : []),
      { value: "close", label: "Close" },
    ];
    const selected = await ui.select(`${title} (${page + 1}/${pages})\n\n${lines.slice(page * pageSize, (page + 1) * pageSize).join("\n")}`, items, undefined, context);
    if (selected === "next") page++;
    else if (selected === "previous") page--;
    else break;
  }
  if (!signal?.aborted) ui.showStatus(`Viewed ${title}.`, context);
}
