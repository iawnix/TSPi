import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

// The pinned source-only Pi interfaces are deliberately confined to this map.
const MODULES = Object.freeze({
  resolver: "packages/coding-agent/src/experimental/source-resolver.ts",
  worker: "packages/coding-agent/src/experimental/session-worker.ts",
  process: "packages/coding-agent/src/experimental/process.ts",
  setup: "packages/coding-agent/src/experimental/durable/harness-setup.ts",
  skills: "packages/coding-agent/src/core/skills.ts",
  modelRuntime: "packages/coding-agent/src/core/model-runtime.ts",
  settings: "packages/coding-agent/src/core/settings-manager.ts",
  estimate: "packages/ai/src/utils/estimate.ts",
  submissions: "packages/durable/src/harness/submissions.ts",
  compaction: "packages/durable/src/harness/compaction.ts",
  server: "packages/coding-agent/src/experimental/server.ts",
  clientRuntime: "packages/coding-agent/src/experimental/client-runtime.ts",
  clientCommand: "packages/coding-agent/src/cli/experimental/commands/client.ts",
  client: "packages/coding-agent/src/experimental/client.ts",
  clientTui: "packages/coding-agent/src/experimental/client-tui.ts",
  clientChat: "packages/coding-agent/src/experimental/client-tui-chat.ts",
  slashCommands: "packages/coding-agent/src/experimental/services/slash-commands.ts",
  presentationUI: "packages/coding-agent/src/experimental/services/presentation-ui.ts",
  transcript: "packages/coding-agent/src/experimental/services/transcript.ts",
  theme: "packages/coding-agent/src/modes/interactive/theme/theme.ts",
  toolsManager: "packages/coding-agent/src/utils/tools-manager.ts",
  grep: "packages/coding-agent/src/core/tools/grep.ts",
  find: "packages/coding-agent/src/core/tools/find.ts",
  ls: "packages/coding-agent/src/core/tools/ls.ts",
  chord: "packages/chord/src/index.ts",
  context: "packages/chord/src/context/index.ts",
  tui: "packages/tui/src/index.ts",
});

export function piSourceRoot() {
  const root = process.env.RESEARCH_AGENT_PI_RUNTIME_ROOT;
  if (!root) throw new Error("RESEARCH_AGENT_PI_RUNTIME_ROOT is required");
  return resolve(root);
}

export function piModulePath(name, root = piSourceRoot()) {
  if (!Object.hasOwn(MODULES, name)) throw new Error(`Unknown Pi source module: ${name}`);
  return join(root, MODULES[name]);
}

export function loadPi(name, root) {
  return import(pathToFileURL(piModulePath(name, root)).href);
}
