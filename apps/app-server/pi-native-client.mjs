import { lstatSync } from "node:fs";
import { resolve, join } from "node:path";
import { pathToFileURL } from "node:url";

import { formatTerminalFailure } from "./tspi-terminal-errors.mjs";
import { runTerminalSessions } from "./tspi-terminal-session.mjs";
import { subscribeMonitor } from "./tspi-monitor-subscription.mjs";
import { connectHost } from "./tspi-host-client.mjs";
import { createTspiToolRenderers } from "./tspi-tool-renderers.mjs";
import { PUBLIC_TOOL_CANONICAL_NAMES } from "../../packages/agent-runtime/host-api/tools.mjs";

if (!process.env.TSPI_PI_RUNTIME_ROOT) throw new Error("remote Pi client requires TSPI_PI_RUNTIME_ROOT");
const sourceRoot = resolve(process.env.TSPI_PI_RUNTIME_ROOT);
const fromSource = (relative) => import(pathToFileURL(join(sourceRoot, relative)).href);

const [commandModule, clientModule, tuiModule] = await Promise.all([
  fromSource("packages/coding-agent/src/cli/experimental/commands/client.ts"),
  fromSource("packages/coding-agent/src/experimental/client.ts"),
  fromSource("packages/coding-agent/src/experimental/client-tui.ts"),
]);
const { clientCommand } = commandModule;
const { runClient } = clientModule;
const { runClientTui } = tuiModule;
const [{ configureToolRenderers }, tuiComponents] = await Promise.all([
  fromSource("packages/coding-agent/src/experimental/client-tui-chat.ts"),
  fromSource("packages/tui/src/index.ts"),
]);
configureToolRenderers(createTspiToolRenderers(tuiComponents, Object.values(PUBLIC_TOOL_CANONICAL_NAMES)));

function createHostRequest() {
  const socketPath = process.env.TSPI_HOST_SOCKET?.trim();
  if (!socketPath) throw new Error("Terminal commands require the Host connection");
  const expectedReleaseId = process.env.TSPI_HOST_RELEASE_ID?.trim() || undefined;
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
  const cwd = process.env.TSPI_SESSION_CWD?.trim();
  if (!cwd) return process.cwd();
  const resolvedCwd = resolve(cwd);
  const info = lstatSync(resolvedCwd);
  if (!info.isDirectory() || info.isSymbolicLink()) {
    throw new Error(`TSPi session cwd must be a regular directory: ${resolvedCwd}`);
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
    // otherwise `--continue` can resurrect an older TSPi custom TUI. Radius
    // does not accept local package paths, so it keeps Pi's undefined value.
    const command = parsed.command.pluginPackages === undefined && parsed.command.connect?.transport !== "radius"
      ? { ...parsed.command, pluginPackages: [] }
      : parsed.command;
    if (command.prompt !== undefined || process.stdin.isTTY !== true || process.stdout.isTTY !== true) {
      await runPrintClient(command);
    } else {
      const [{ createStaticFacetLoader }, { createTspiNativeClientFacet }] = await Promise.all([
        fromSource("packages/chord/src/index.ts"),
        import("./tspi-native-client-facet.mjs"),
      ]);
      await runTerminalSessions({
        command,
        workspaceId: process.env.TSPI_WORKSPACE_ID,
        request: createHostRequest(),
        run: (selected, options) => runClientTui(selected, { directory: process.env.PI_SERVER_DIR, ...options }),
        createFacet: async (session) => createStaticFacetLoader([
          await createTspiNativeClientFacet({ sourceRoot, session }),
        ]),
      });
    }
  } catch (error) {
    const diagnosticFile = process.env.TSPI_DIAGNOSTIC_FILE
      || (process.env.TSPI_STATE_ROOT
        ? `${process.env.TSPI_STATE_ROOT.replace(/\/$/u, "")}/worker-diagnostics.log`
        : undefined);
    console.error(`Error: ${formatTerminalFailure(error, {
      installRoot: process.env.TSPI_INSTALL_ROOT,
      diagnosticFile,
    })}`);
    process.exitCode = 1;
  }
}
