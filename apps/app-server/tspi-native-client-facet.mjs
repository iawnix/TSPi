import { execFile } from "node:child_process";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { promisify } from "node:util";

import {
  parseSlashCommand,
  slashCompletions,
  SLASH_COMMAND_DEFINITIONS,
} from "../../packages/ts-agent-runtime/host-api/commands.mjs";

const executeFile = promisify(execFile);

/**
 * Client-only TSPi command facet for Pi's native ExperimentalClientTui.
 *
 * The worker owns tools and the AgentController; this facet only restores the
 * familiar command names and renders their structured command result. It is
 * intentionally independent of the old ExtensionAPI/UI package so loading it
 * cannot create a second ordinary Pi runtime.
 */
export async function createTspiNativeClientFacet({ sourceRoot, packageRoot = process.env.TSPI_PACKAGE_ROOT } = {}) {
  if (typeof sourceRoot !== "string" || sourceRoot.length === 0) throw new TypeError("sourceRoot is required");
  const fromSource = (relative) => import(pathToFileURL(join(sourceRoot, relative)).href);
  const [
    { defineFacet },
    { SlashCommands },
    { PresentationLayout },
    { PresentationUI },
    { TspiSystemPrompt },
    { RunHistoryBrowser, runRecords },
    { WrappedDocumentViewer },
  ] = await Promise.all([
    fromSource("packages/chord/src/index.ts"),
    fromSource("packages/coding-agent/src/experimental/services/slash-commands.ts"),
    fromSource("packages/coding-agent/src/experimental/services/presentation-layout.ts"),
    fromSource("packages/coding-agent/src/experimental/services/presentation-ui.ts"),
    fromSource("packages/coding-agent/src/experimental/services/slash-commands-provider.ts"),
    import("../../extensions/pi/tui-package/src/runs.ts"),
    import("../../extensions/pi/tui-package/src/document-viewer.ts"),
  ]);
  const root = typeof packageRoot === "string" && packageRoot.length > 0 ? packageRoot : process.cwd();
  const python = process.env.TSPI_WORKSPACE_PYTHON || process.env.TS_AGENT_PYTHON || "python3";
  const apiScript = join(root, "scripts/ts_api.py");

  return defineFacet({
    id: "@tspi/native-client-commands",
    setup(env) {
      const commands = env.use(SlashCommands);
      const ui = env.use(PresentationUI);
      const layout = env.use(PresentationLayout);
      const systemPrompt = env.use(TspiSystemPrompt);
      env.onActivate(() => {
        for (const name of ["research", "compute", "debug"]) {
          env.own(commands.replace(commandFor(name, ui, python, apiScript)));
        }
        env.own(commands.replace(runsCommand(layout, ui, runRecords, RunHistoryBrowser, python, apiScript)));
        env.own(commands.replace(systemPromptCommand(layout, ui, systemPrompt, WrappedDocumentViewer)));
      });
    },
  });
}

function commandFor(name, ui, python, apiScript) {
  const definition = SLASH_COMMAND_DEFINITIONS[name];
  return {
    name,
    description: `${definition?.description || `TSPi ${name}`} (native client)`,
    ...(definition?.usage ? { argumentHint: definition.usage } : {}),
    getArgumentCompletions(prefix) {
      return slashCompletions(name, prefix) || [];
    },
    async run(args, context) {
      if (name === "debug") {
        ui.showStatus(JSON.stringify({
          schema_version: "tspi-client-command-result/1",
          command: "/debug",
          state: "remote_unsupported",
          message: "The debug modal is presentation-local; use /sys_prompt for the shared prompt manifest.",
        }, null, 2), context);
        return undefined;
      }
      try {
        const invocation = parseSlashCommand(name, args);
        const result = await executeCanonicalCommand(invocation, python, apiScript, process.cwd(), context);
        ui.showStatus(JSON.stringify({
          schema_version: "tspi-client-command-result/1",
          command: `/${name}`,
          invocation,
          result,
        }, null, 2), context);
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        ui.showStatus(JSON.stringify({
          schema_version: "tspi-client-command-result/1",
          command: `/${name}`,
          state: "failed",
          error: { code: error?.name === "CommandUsageError" ? "usage" : "command_failed", message },
        }, null, 2), context);
      }
      return undefined;
    },
  };
}

function runsCommand(layout, ui, runRecords, RunHistoryBrowser, python, apiScript) {
  return {
    name: "runs",
    description: "Browse active and recorded Compute and Review runs.",
    async run(args, context) {
      if (args.trim().length > 0) throw new Error("/runs takes no arguments");
      try {
        const report = await executeCanonicalCommand(
          { command: "compute.runs", params: Object.freeze({}) },
          python,
          apiScript,
          layout.getContext().cwd,
          context,
        );
        const records = runRecords(report);
        if (records.length === 0) {
          ui.showStatus("No TS subagent runs are available in this workspace", context);
          return undefined;
        }
        ui.showStatus("", context);
        const tuiContext = layout.getContext();
        let handle;
        const browser = new RunHistoryBrowser(
          records,
          tuiContext.tui,
          tuiContext.theme,
          tuiContext.keybindings,
          () => handle?.hide(),
        );
        handle = tuiContext.tui.showOverlay(browser, { width: "94%", maxHeight: "88%", margin: 1 });
      } catch (error) {
        ui.showStatus(`Unable to read TS runs: ${error instanceof Error ? error.message : String(error)}`, context);
      }
      return undefined;
    },
  };
}

function systemPromptCommand(layout, ui, systemPrompt, WrappedDocumentViewer) {
  return {
    name: "sys_prompt",
    description: "Show the effective system prompt and provenance",
    async run(args, context) {
      if (args.trim().length > 0) throw new Error("/sys_prompt takes no arguments");
      try {
        const manifest = await systemPrompt.inspect(context);
        const tuiContext = layout.getContext();
        ui.showStatus("", context);
        let handle;
        const viewer = new WrappedDocumentViewer(
          "Effective system prompt",
          JSON.stringify(manifest, null, 2),
          tuiContext.tui,
          tuiContext.theme,
          tuiContext.keybindings,
          () => handle?.hide(),
        );
        handle = tuiContext.tui.showOverlay(viewer, { width: "94%", maxHeight: "88%", margin: 1 });
      } catch (error) {
        ui.showStatus(`Unable to inspect system prompt: ${error instanceof Error ? error.message : String(error)}`, context);
      }
      return undefined;
    },
  };
}

async function executeCanonicalCommand(invocation, python, apiScript, cwd, context) {
  const args = [invocation.command, "--root", cwd];
  for (const [key, flag] of [["kind", "--kind"], ["id", "--id"], ["name", "--name"], ["query", "--query"]]) {
    if (invocation.params?.[key] !== undefined) args.push(flag, String(invocation.params[key]));
  }
  const completed = await executeFile(python, [apiScript, ...args], {
    cwd,
    env: { ...process.env, PYTHONNOUSERSITE: "1" },
    timeout: 60_000,
    maxBuffer: 4 * 1024 * 1024,
    signal: context?.abortSignal,
  });
  return JSON.parse(completed.stdout.trim() || "{}");
}
