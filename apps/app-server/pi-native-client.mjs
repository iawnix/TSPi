import { randomUUID } from "node:crypto";
import { lstatSync } from "node:fs";
import { resolve, join } from "node:path";
import { pathToFileURL } from "node:url";

import { formatError } from "./tspi-terminal-errors.mjs";
import { createTspiPackageRootRestoreFacet, withTspiPackageRootHidden } from "./native-client-env.mjs";
import { connectHost } from "./tspi-host-client.mjs";

if (!process.env.TSPI_PI_SOURCE) throw new Error("remote Pi client requires TSPI_PI_SOURCE");
const sourceRoot = resolve(process.env.TSPI_PI_SOURCE);
const fromSource = (relative) => import(pathToFileURL(join(sourceRoot, relative)).href);

const [commandModule, clientModule, tuiModule] = await Promise.all([
  fromSource("packages/coding-agent/src/cli/experimental/commands/client.ts"),
  fromSource("packages/coding-agent/src/experimental/client.ts"),
  fromSource("packages/coding-agent/src/experimental/client-tui.ts"),
]);
const { clientCommand } = commandModule;
const { runClient } = clientModule;
const { runClientTui } = tuiModule;

function createHostResumeSession() {
  const socketPath = process.env.TSPI_HOST_SOCKET?.trim();
  const workspaceId = process.env.TSPI_WORKSPACE_ID?.trim();
  if (!socketPath || !workspaceId) return undefined;
  return async (sessionId) => {
    if (typeof sessionId !== "string" || sessionId.length === 0) throw new TypeError("sessionId is required");
    const peer = await connectHost({ socketPath });
    try {
      const result = await peer.request("session/resume", {
        request_id: `terminal-resume-${process.pid}-${randomUUID()}`,
        workspace_id: workspaceId,
        session_id: sessionId,
        presentation: "terminal",
      });
      const returnedSessionId = result?.client?.session_id ?? result?.session?.session_id;
      if (returnedSessionId !== sessionId) {
        throw new Error(`Host resumed an unexpected session: expected ${sessionId}, got ${returnedSessionId || "none"}`);
      }
      return result;
    } finally {
      peer.close();
    }
  };
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
    const resumeSession = createHostResumeSession();
    if (command.prompt !== undefined || process.stdin.isTTY !== true || process.stdout.isTTY !== true) {
      await runPrintClient(command);
    } else {
      // Pi owns the complete interactive surface: slash-command registry,
      // argument completions, selectors, transcript rendering, and busy-state
      // input handling. TSPi only supplies a client facet for its shared
      // command contract; it does not provide another editor or agent loop.
      const [{ createStaticFacetLoader }, { SlashCommands }, { PresentationUI }, { createTspiNativeClientFacet }] = await Promise.all([
        fromSource("packages/chord/src/index.ts"),
        fromSource("packages/coding-agent/src/experimental/services/slash-commands.ts"),
        fromSource("packages/coding-agent/src/experimental/services/presentation-ui.ts"),
        import("./tspi-native-client-facet.mjs"),
      ]);
      const commandFacet = await createTspiNativeClientFacet({
        sourceRoot,
        packageRoot: process.env.TSPI_PACKAGE_ROOT,
      });
      // The restore facet depends on PresentationUI, which the built-in
      // presentation bridge also provides. Its position after the shared
      // command facet lets Pi inspect the opt-in env before restoration; the
      // finally path still covers startup failures.
      await withTspiPackageRootHidden(async (restore) => runClientTui(command, {
        directory: process.env.PI_SERVER_DIR,
        resumeSession,
        facetLoader: createStaticFacetLoader([
          commandFacet,
          createTspiPackageRootRestoreFacet(restore, PresentationUI),
        ]),
      }));
    }
  } catch (error) {
    console.error(`Error: ${formatError(error)}`);
    process.exitCode = 1;
  }
}
