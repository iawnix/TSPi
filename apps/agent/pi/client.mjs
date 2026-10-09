import { loadPi } from "./source.mjs";
import { lstatSync } from "node:fs";
import { resolve, join } from "node:path";

import { formatTerminalFailure } from "../terminal/errors.mjs";
import { runTerminalSessions } from "../terminal/session.mjs";
import { subscribeMonitor } from "../terminal/status/monitor.mjs";
import { connectHost } from "../transport/host-client.mjs";
import { createResearchAgentToolRenderers } from "../terminal/renderers/tools.mjs";
import { PUBLIC_TOOL_NAMES } from "../tools/contracts.mjs";

if (!process.env.RESEARCH_AGENT_PI_RUNTIME_ROOT) throw new Error("remote Pi client requires RESEARCH_AGENT_PI_RUNTIME_ROOT");
const sourceRoot = resolve(process.env.RESEARCH_AGENT_PI_RUNTIME_ROOT);


const [commandModule, clientModule, tuiModule] = await Promise.all([
  loadPi("clientCommand", sourceRoot),
  loadPi("client", sourceRoot),
  loadPi("clientTui", sourceRoot),
]);
const { clientCommand } = commandModule;
const { runClient } = clientModule;
const { runClientTui } = tuiModule;
const [{ configureToolRenderers }, tuiComponents] = await Promise.all([
  loadPi("clientChat", sourceRoot),
  loadPi("tui", sourceRoot),
]);
configureToolRenderers(createResearchAgentToolRenderers(tuiComponents, Object.values(PUBLIC_TOOL_NAMES)));

function createHostRequest() {
  const socketPath = process.env.RESEARCH_AGENT_HOST_SOCKET?.trim();
  if (!socketPath) throw new Error("Terminal commands require the Host connection");
  const expectedReleaseId = process.env.RESEARCH_AGENT_HOST_RELEASE_ID?.trim() || undefined;
  const request = async (method, params) => {
    const peer = await connectHost({ socketPath, expectedReleaseId });
    try { return await peer.request(method, params); }
    finally { peer.close(); }
  };
  request.subscribeMonitor = (workspaceId, onChange, onError) => subscribeMonitor({
    connect: () => connectHost({ socketPath, expectedReleaseId }), workspaceId, onChange, onError,
  });
  return request;
}

function bindWorkspaceCwd() {
  const cwd = process.env.RESEARCH_AGENT_SESSION_CWD?.trim();
  if (!cwd) return process.cwd();
  const resolvedCwd = resolve(cwd);
  const info = lstatSync(resolvedCwd);
  if (!info.isDirectory() || info.isSymbolicLink()) {
    throw new Error(`ResearchAgent session cwd must be a regular directory: ${resolvedCwd}`);
  }
  process.chdir(resolvedCwd);
  return resolvedCwd;
}

async function runPrintClient(command) {
  let streamedText = false;
  const result = await runClient(command, {
    directory: process.env.PI_SERVER_DIR,
    onEvent(event) {
      if (event.type !== "message_update" || event.frame?.type !== "text_delta") return;
      streamedText = true;
      process.stdout.write(event.frame.delta);
    },
  });
  if (result.kind === "attached") {
    console.log(`${result.serverId}\t${result.sessionId}\tattached`);
  } else if (result.kind === "prompted") {
    if (streamedText) process.stdout.write("\n");
    else console.log(result.text);
  } else {
    for (const session of result.sessions) console.log(`${session.serverId}\t${session.sessionId}`);
  }
}

const parsed = clientCommand.parse(process.argv.slice(2));
if (!parsed.ok) {
  for (const error of parsed.errors) console.error(`Error: ${error}`);
  process.exitCode = 1;
} else {
  try {
    // The launcher exports this path because the App Server child itself is
    // started from the managed Pi source tree. Bind it before loading the
    // native presentation so settings, plugins, and session creation all use
    // the same workspace identity.
    bindWorkspaceCwd();
    // Pi persists presentation package selections per session. For a local
    // Host, an omitted `-e` must therefore mean an explicit empty selection;
    // otherwise `--continue` can resurrect an older ResearchAgent custom TUI. Radius
    // does not accept local package paths, so it keeps Pi's undefined value.
    const command = parsed.command.pluginPackages === undefined && parsed.command.connect?.transport !== "radius"
      ? { ...parsed.command, pluginPackages: [] }
      : parsed.command;
    if (command.prompt !== undefined || process.stdin.isTTY !== true || process.stdout.isTTY !== true) {
      await runPrintClient(command);
    } else {
      const [{ createStaticFacetLoader }, { createResearchAgentNativeClientFacet }] = await Promise.all([
        loadPi("chord", sourceRoot),
        import("../terminal/commands/facet.mjs"),
      ]);
      await runTerminalSessions({
        command,
        workspaceId: process.env.RESEARCH_AGENT_WORKSPACE_ID,
        request: createHostRequest(),
        run: (selected, options) => runClientTui(selected, { directory: process.env.PI_SERVER_DIR, ...options }),
        createFacet: async (session) => createStaticFacetLoader([
          await createResearchAgentNativeClientFacet({ sourceRoot, session }),
        ]),
      });
    }
  } catch (error) {
    const diagnosticFile = process.env.RESEARCH_AGENT_DIAGNOSTIC_FILE
      || (process.env.RESEARCH_AGENT_STATE_ROOT
        ? `${process.env.RESEARCH_AGENT_STATE_ROOT.replace(/\/$/u, "")}/worker-diagnostics.log`
        : undefined);
    console.error(`Error: ${formatTerminalFailure(error, {
      installRoot: process.env.RESEARCH_AGENT_INSTALL_ROOT,
      diagnosticFile,
    })}`);
    process.exitCode = 1;
  }
}
