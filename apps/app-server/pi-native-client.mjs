import { lstatSync } from "node:fs";
import { resolve, join } from "node:path";
import { pathToFileURL } from "node:url";

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
      // Pi owns the complete interactive surface: slash-command registry,
      // argument completions, selectors, transcript rendering, and busy-state
      // input handling. TSPi only supplies a client facet for its shared
      // command contract; it does not provide another editor or agent loop.
      const [{ createStaticFacetLoader }, { createTspiNativeClientFacet }] = await Promise.all([
        fromSource("packages/chord/src/index.ts"),
        import("./tspi-native-client-facet.mjs"),
      ]);
      const commandFacet = await createTspiNativeClientFacet({
        sourceRoot,
        packageRoot: process.env.TSPI_PACKAGE_ROOT,
      });
      await runClientTui(command, {
        directory: process.env.PI_SERVER_DIR,
        facetLoader: createStaticFacetLoader([commandFacet]),
      });
    }
  } catch (error) {
    console.error(`Error: ${error instanceof Error ? error.message : String(error)}`);
    process.exitCode = 1;
  }
}
