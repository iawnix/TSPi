import { resolve, join } from "node:path";
import { pathToFileURL } from "node:url";

if (!process.env.TSPI_PI_SOURCE) throw new Error("remote Pi client requires TSPI_PI_SOURCE");
const sourceRoot = resolve(process.env.TSPI_PI_SOURCE);

const fromSource = (relative) => import(pathToFileURL(join(sourceRoot, relative)).href);
const [commandModule, runtimeModule, clientModule, tuiModule, viewportModule, editorModule, themeModule, themeControllerModule,
  settingsModule, resourceModule, configModule, keybindingsModule, tuiCoreModule, assistantModule, userModule, toolModule,
  statusModule, renderersModule] = await Promise.all([
  fromSource("packages/coding-agent/src/cli/experimental/commands/client.ts"),
  fromSource("packages/coding-agent/src/experimental/client-runtime.ts"),
  fromSource("packages/coding-agent/src/experimental/client.ts"),
  fromSource("packages/coding-agent/src/modes/interactive/tui-renderer.ts"),
  fromSource("packages/coding-agent/src/modes/interactive/chat-viewport.ts"),
  fromSource("packages/coding-agent/src/modes/interactive/components/custom-editor.ts"),
  fromSource("packages/coding-agent/src/modes/interactive/theme/theme.ts"),
  fromSource("packages/coding-agent/src/modes/interactive/theme/theme-controller.ts"),
  fromSource("packages/coding-agent/src/core/settings-manager.ts"),
  fromSource("packages/coding-agent/src/core/resource-loader.ts"),
  fromSource("packages/coding-agent/src/config.ts"),
  fromSource("packages/coding-agent/src/core/keybindings.ts"),
  fromSource("packages/tui/src/index.ts"),
  fromSource("packages/coding-agent/src/modes/interactive/components/assistant-message.ts"),
  fromSource("packages/coding-agent/src/modes/interactive/components/user-message.ts"),
  fromSource("packages/coding-agent/src/modes/interactive/components/tool-execution.ts"),
  fromSource("packages/coding-agent/src/modes/interactive/components/status-indicator.ts"),
  fromSource("packages/coding-agent/src/core/tools/renderers/index.ts"),
]);
const { BACKGROUND_CONTEXT } = await fromSource("packages/chord/src/context/index.ts");

const { clientCommand } = commandModule;
const { activateBuiltinClientServices, openClientRuntime } = runtimeModule;
const { runClient } = clientModule;
const { createInteractiveTui } = tuiModule;
const { createChatViewport } = viewportModule;
const { CustomEditor } = editorModule;
const { getEditorTheme, setRegisteredThemes, stopThemeWatcher, theme } = themeModule;
const { InteractiveThemeController } = themeControllerModule;
const { SettingsManager } = settingsModule;
const { DefaultResourceLoader } = resourceModule;
const { getAgentDir } = configModule;
const { KeybindingsManager } = keybindingsModule;
const { CombinedAutocompleteProvider, Container, setKeybindings, Spacer, Text, TruncatedText } = tuiCoreModule;
const { AssistantMessageComponent } = assistantModule;
const { UserMessageComponent } = userModule;
const { ToolExecutionComponent } = toolModule;
const { WorkingStatusIndicator } = statusModule;
const { createAllToolRenderers } = renderersModule;

function sessionCreateOptions(id) {
  const cwd = process.env.TSPI_SESSION_CWD?.trim();
  return {
    ...(id === undefined ? {} : { id }),
    ...(cwd === undefined || cwd.length === 0 ? {} : { cwd }),
  };
}

function sessionMatchesCwd(summary) {
  const cwd = process.env.TSPI_SESSION_CWD?.trim();
  return cwd === undefined || cwd.length === 0 || summary.cwd === cwd;
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

class RemoteTranscript {
  constructor(ui, cwd, document, pending, status, requestRender) {
    this.ui = ui;
    this.cwd = cwd;
    this.document = document;
    this.pending = pending;
    this.status = status;
    this.requestRender = requestRender;
    this.renderers = createAllToolRenderers();
    this.indicator = undefined;
  }

  apply(snapshot) {
    this.document.clear();
    this.pending.clear();
    this.status.clear();
    this.indicator?.dispose();
    this.indicator = undefined;
    const tools = new Map();
    for (const entry of snapshot.transcript || []) this.addEntry(entry, tools);
    const operation = snapshot.operation;
    if (operation?.streamingMessage) this.addAssistant(operation.streamingMessage, true, tools);
    for (const running of operation?.runningTools || []) {
      const component = this.tool(tools, running.toolName, running.toolCallId, running.args);
      if (running.status === "running") component.markExecutionStarted();
      if (running.result !== undefined) component.updateResult({ ...running.result, isError: running.isError === true }, running.status === "running");
    }
    for (const item of snapshot.queues || []) {
      const text = item.type === "message" ? messageText(item.message).replace(/\s+/gu, " ") : `<${item.customType}>`;
      this.pending.addChild(new TruncatedText(theme.fg("muted", `[${item.kind}] ${text}`), 1, 0));
    }
    if (operation) this.indicator = new WorkingStatusIndicator(this.ui, "Working... (esc to abort)");
    if (this.indicator) this.status.addChild(this.indicator);
    this.document.invalidate();
    this.pending.invalidate();
    this.status.invalidate();
    this.requestRender();
  }

  dispose() {
    this.indicator?.dispose();
    this.indicator = undefined;
  }

  addEntry(entry, tools) {
    if (entry.type === "compaction") {
      this.addText(`[compaction] compacted from ${entry.tokensBefore} tokens`);
      for (const retained of entry.retainedTail || []) this.addMessage(retained, tools);
      return;
    }
    if (entry.type === "branch_summary") {
      this.addText("[branch summary]");
      this.addText(entry.summary);
      return;
    }
    if (entry.type === "custom") {
      this.addText(`[${entry.customType}]`);
      return;
    }
    this.addMessage(entry.message, tools);
  }

  addMessage(message, tools) {
    if (message.role === "user") {
      this.document.addChild(new Spacer(1));
      this.document.addChild(new UserMessageComponent(messageText(message)));
    } else if (message.role === "assistant") {
      this.addAssistant(message, false, tools);
    } else if (message.role === "toolResult") {
      this.tool(tools, message.toolName, message.toolCallId).updateResult(message);
    }
  }

  addAssistant(message, streaming, tools) {
    const component = new AssistantMessageComponent(message, false);
    component.updateContent(message, streaming);
    this.document.addChild(component);
    for (const content of message.content || []) {
      if (content.type === "toolCall") this.tool(tools, content.name, content.id, content.arguments).setArgsComplete();
    }
  }

  tool(tools, name, id, args = {}) {
    let component = tools.get(id);
    if (component) {
      if (args !== undefined) component.updateArgs(args);
      return component;
    }
    component = new ToolExecutionComponent(name, id, args, {}, this.renderers[name], this.ui, this.cwd);
    this.document.addChild(component);
    tools.set(id, component);
    return component;
  }

  addText(value) {
    this.document.addChild(new Spacer(1));
    this.document.addChild(new Text(theme.fg("muted", value), 1, 0));
  }
}

async function runNativeRemoteClient(command) {
  const cwd = process.env.TSPI_SESSION_CWD?.trim() || process.cwd();
  const agentDir = getAgentDir();
  const settings = SettingsManager.create(cwd, agentDir);
  const resources = new DefaultResourceLoader({ cwd, agentDir, settingsManager: settings, noExtensions: true, noSkills: true, noPromptTemplates: true, noContextFiles: true });
  await resources.reload();
  setRegisteredThemes(resources.getThemes().themes);
  const runtime = await openClientRuntime(command, { directory: process.env.PI_SERVER_DIR });
  const services = await prepareSession(runtime, command);
  const tui = createInteractiveTui({ tuiMode: "fullscreen", showHardwareCursor: settings.getShowHardwareCursor(), logDirectory: agentDir });
  tui.setClearOnShrink(settings.getClearOnShrink());
  const keybindings = KeybindingsManager.create();
  setKeybindings(keybindings);
  const document = new Container();
  const transcriptContainer = new Container();
  const pending = new Container();
  const status = new Container();
  const editorContainer = new Container();
  const footer = new Text("", 1, 0);
  const header = new Text("", 1, 0);
  document.addChild(header);
  document.addChild(transcriptContainer);
  const editor = new CustomEditor(tui, getEditorTheme(), keybindings, { paddingX: 1, embedWorkingStatus: true });
  editorContainer.addChild(editor);
  const viewport = createChatViewport({ document, pendingMessages: pending, status, editor: editorContainer, footer,
    scrollbarTrackStyle: (value) => theme.fg("scrollbarTrack", value), scrollbarThumbStyle: (value) => theme.fg("scrollbarThumb", value) });
  const transcript = new RemoteTranscript(tui, cwd, transcriptContainer, pending, status, () => tui.requestRender());
  let closed = false;
  let unsubscribe;
  let resolveFinish;
  const finished = new Promise((resolve) => { resolveFinish = resolve; });
  const finish = () => { if (closed) return; closed = true; resolveFinish(); };
  const showStatus = (value) => { status.clear(); if (value) status.addChild(new Text(theme.fg("muted", value), 1, 0)); tui.requestRender(); };
  const refresh = () => {
    const snapshot = services.transcript.state.value?.snapshot;
    const model = snapshot?.configuration?.model;
    const thinking = snapshot?.configuration?.thinkingLevel || "off";
    header.setText(theme.bold(theme.fg("accent", "Pi")) + theme.fg("dim", "  remote Host") + theme.fg("dim", `\n  ${cwd}`));
    footer.setText(theme.fg("dim", `${model ? `${model.provider}/${model.modelId}` : "model pending"} · ${thinking} · /model · /thinking · /compact · /new · /session · /tree · /abort · /quit`));
    if (snapshot) transcript.apply(snapshot);
    tui.requestRender();
  };
  const submit = async (value) => {
    const text = value.trim();
    if (!text) return;
    editor.setText("");
    if (text.startsWith("/")) return executeCommand(text.slice(1));
    const snapshot = services.transcript.state.value?.snapshot;
    const running = snapshot?.operation !== null && snapshot?.operation !== undefined;
    showStatus(running ? "Queueing steering message..." : "Running turn...");
    const response = running
      ? await services.agent.steer({ message: text, images: null }, BACKGROUND_CONTEXT)
      : await services.agent.prompt({ message: text, images: null }, BACKGROUND_CONTEXT);
    if (!response.accepted) showStatus(response.error.message);
  };
  const executeCommand = async (line) => {
    const space = line.indexOf(" ");
    const name = (space === -1 ? line : line.slice(0, space)).toLowerCase();
    const args = space === -1 ? "" : line.slice(space + 1).trim();
    try {
      if (["quit", "exit"].includes(name)) return finish();
      if (name === "abort") {
        const operation = services.transcript.state.value?.snapshot?.operation;
        if (operation) await services.agent.requestAbort(operation.id, BACKGROUND_CONTEXT);
        return showStatus(operation ? `Aborting ${operation.id}...` : "No active turn.");
      }
      if (name === "model") return await changeModel(services, args, showStatus);
      if (name === "thinking") return await changeThinking(services, args, showStatus);
      if (name === "compact") return report(await services.agent.compact({ customInstructions: args || null }, BACKGROUND_CONTEXT), showStatus);
      if (name === "new") return await startNewSession(services, showStatus);
      if (name === "session") return showStatus(`Session ${services.sessionId}`);
      if (name === "tree") return showStatus((services.directory.state.value?.sessions || []).map((item) => `${item.sessionId}${item.sessionId === services.sessionId ? " *" : ""}`).join("\n") || "No sessions");
      if (name === "resume") return await resumeSession(services, args, showStatus);
      if (name === "hotkeys") return showStatus("Esc abort · Ctrl+D quit · / commands · follow-up key queues a message");
      if (name === "reload") return showStatus("Host session resources are already live; reconnect to reload.");
      return showStatus(`Unknown command: /${name}`);
    } catch (error) {
      showStatus(`Error: ${error instanceof Error ? error.message : String(error)}`);
    }
  };
  editor.onSubmit = (value) => void submit(value).catch((error) => showStatus(`Error: ${error.message || error}`));
  editor.onEscape = () => {
    const operation = services.transcript.state.value?.snapshot?.operation;
    if (operation) void services.agent.requestAbort(operation.id, BACKGROUND_CONTEXT).catch((error) => showStatus(String(error)));
  };
  editor.onCtrlD = finish;
  editor.onAction("app.clear", () => {
    const operation = services.transcript.state.value?.snapshot?.operation;
    if (operation) {
      void services.agent.requestAbort(operation.id, BACKGROUND_CONTEXT).catch((error) => showStatus(String(error)));
    } else {
      editor.setText("");
    }
  });
  editor.onAction("app.model.select", () => void executeCommand("model"));
  editor.onAction("app.message.followUp", () => { const value = editor.getText().trim(); if (value) { editor.setText(""); void services.agent.followUp({ message: value, images: null }, BACKGROUND_CONTEXT); } });
  editor.setAutocompleteProvider(new CombinedAutocompleteProvider(["model", "thinking", "compact", "new", "session", "tree", "resume", "abort", "hotkeys", "quit"].map((name) => ({ name })), cwd));
  const themeController = new InteractiveThemeController(tui, { getSettingsManager: () => settings, showError: showStatus, onChanged: refresh });
  unsubscribe = services.transcript.state.subscribe(() => refresh());
  refresh();
  tui.addChild(viewport.root);
  tui.setLayoutRoot(viewport.root);
  tui.setFocus(editor);
  tui.start();
  await themeController.applyFromSettings();
  await finished;
  unsubscribe?.();
  transcript.dispose();
  themeController.dispose();
  stopThemeWatcher();
  tui.stop();
  await runtime.dispose();
}

async function prepareSession(runtime, command) {
  const candidates = await Promise.all(runtime.servers.map(activateBuiltinClientServices));
  let selected;
  if (command.sessionId) {
    const matches = candidates.filter((candidate) => (candidate.directory.state.value?.sessions || []).some(
      (item) => item.sessionId === command.sessionId && sessionMatchesCwd(item),
    ));
    if (matches.length > 1) throw new Error(`Session ${command.sessionId} is available from more than one server`);
    selected = matches[0];
    if (!selected) {
      if (candidates.length !== 1) throw new Error(`No discovered server contains session ${command.sessionId}`);
      selected = candidates[0];
      await selected.management.create(sessionCreateOptions(command.sessionId), BACKGROUND_CONTEXT);
    }
  } else if (command.continue || command.resume) {
    selected = candidates.flatMap((candidate) => candidate.directory.state.value?.sessions || [])
      .filter(sessionMatchesCwd)
      .sort((a, b) => b.createdAt - a.createdAt)
      .map((item) => candidates.find((candidate) => candidate.route.serverId === item.serverId))
      .find(Boolean);
  }
  if (!selected) {
    if (candidates.length !== 1) throw new Error("Starting a Session requires exactly one server");
    selected = candidates[0];
  }
  const sessionId = command.sessionId
    ? command.sessionId
    : command.continue || command.resume
      ? selected?.directory.state.value?.sessions?.filter(sessionMatchesCwd).sort((a, b) => b.createdAt - a.createdAt)[0]?.sessionId
        || (await selected.management.create(sessionCreateOptions(), BACKGROUND_CONTEXT)).sessionId
      : (await selected.management.create(sessionCreateOptions(), BACKGROUND_CONTEXT)).sessionId;
  await selected.plugins.prepareSession({ sessionId, packagePaths: command.pluginPackages || null }, BACKGROUND_CONTEXT);
  await selected.management.attach(sessionId, BACKGROUND_CONTEXT);
  return { ...selected, sessionId };
}

async function changeModel(services, args, showStatus) {
  const models = services.models.state.value?.catalog.availableModels || [];
  if (!args) return showStatus(models.map((model) => `${model.provider}/${model.modelId}`).join("\n") || "No models available");
  const [provider, modelId] = args.includes("/") ? args.split("/", 2) : [undefined, args];
  const selected = models.find((model) => model.modelId === modelId && (provider === undefined || model.provider === provider));
  if (!selected) throw new Error(`Unknown model: ${args}`);
  await services.models.select({ provider: selected.provider, modelId: selected.modelId }, BACKGROUND_CONTEXT);
  showStatus(`Selected ${selected.provider}/${selected.modelId}.`);
}

async function changeThinking(services, args, showStatus) {
  const levels = await services.models.getThinkingLevels(BACKGROUND_CONTEXT);
  if (!args) return showStatus(`Thinking levels: ${levels.join(", ")}`);
  if (!levels.includes(args.toLowerCase())) throw new Error(`Unknown thinking level: ${args}`);
  await services.models.selectThinking(args.toLowerCase(), BACKGROUND_CONTEXT);
  showStatus(`Thinking level: ${args.toLowerCase()}.`);
}

async function startNewSession(services, showStatus) {
  const summary = await services.management.create(sessionCreateOptions(), BACKGROUND_CONTEXT);
  await services.plugins.prepareSession({ sessionId: summary.sessionId, packagePaths: null }, BACKGROUND_CONTEXT);
  await services.management.attach(summary.sessionId, BACKGROUND_CONTEXT);
  services.sessionId = summary.sessionId;
  showStatus(`Started session ${summary.sessionId}.`);
}

async function resumeSession(services, requestedId, showStatus) {
  const sessions = (services.directory.state.value?.sessions || []).filter(sessionMatchesCwd);
  const target = requestedId
    ? sessions.find((item) => item.sessionId === requestedId)
    : [...sessions].sort((left, right) => right.createdAt - left.createdAt).find((item) => item.sessionId !== services.sessionId);
  if (!target) throw new Error(requestedId ? `Unknown session: ${requestedId}` : "No other session is available");
  if (target.sessionId === services.sessionId) return showStatus(`Session ${target.sessionId} is already active.`);
  await services.management.detach(BACKGROUND_CONTEXT);
  await services.management.attach(target.sessionId, BACKGROUND_CONTEXT);
  services.sessionId = target.sessionId;
  showStatus(`Resumed session ${target.sessionId}.`);
}

function report(response, showStatus) {
  showStatus(response.accepted ? "" : response.error.message);
}

function messageText(message) {
  if (!message || message.role !== "user") return "";
  return typeof message.content === "string" ? message.content : (message.content || []).filter((part) => part.type === "text").map((part) => part.text).join("");
}

const parsed = clientCommand.parse(process.argv.slice(2));
if (!parsed.ok) {
  for (const error of parsed.errors) console.error(`Error: ${error}`);
  process.exitCode = 1;
} else {
  try {
    if (parsed.command.prompt !== undefined || process.stdin.isTTY !== true || process.stdout.isTTY !== true) {
      await runPrintClient(parsed.command);
    } else {
      await runNativeRemoteClient(parsed.command);
    }
  } catch (error) {
    console.error(`Error: ${error instanceof Error ? error.message : String(error)}`);
    process.exitCode = 1;
  }
}
