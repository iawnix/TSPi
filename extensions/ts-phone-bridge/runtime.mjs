import { homedir } from "node:os";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { parseArgs } from "node:util";
import {
  SettingsManager, ModelRuntime, SessionManager, createAgentSessionServices,
  createAgentSessionFromServices, createAgentSessionRuntime, runRpcMode, initTheme,
} from "@earendil-works/pi-coding-agent";

export function sessionSettings(source) {
  // Preserve Pi's project/global merge rules, but never write preferences back
  // to either file. Model changes remain in the conversation's Pi history.
  const values = {
    global: JSON.stringify(source.getGlobalSettings()),
    project: JSON.stringify(source.getProjectSettings()),
  };
  return SettingsManager.fromStorage({
    withLock(scope, update) {
      const next = update(values[scope]);
      if (next !== undefined) values[scope] = next;
    },
  }, { projectTrusted: true });
}

export function projectModel(model) {
  return { provider: model.provider, id: model.id, name: model.name || model.id,
    contextWindow: model.contextWindow };
}

export async function main(args) {
  const agentDir = resolve(process.env.PI_CODING_AGENT_DIR || resolve(homedir(), ".pi/agent"));
  process.env.PI_OFFLINE = "1";
  const modelRuntime = await ModelRuntime.create({
    authPath: resolve(agentDir, "auth.json"), modelsPath: resolve(agentDir, "models.json"),
    allowModelNetwork: false,
  });
  if (args.length === 1 && args[0] === "--catalog") {
    const models = (await modelRuntime.getAvailable()).map(projectModel);
    if (modelRuntime.getError()) throw new Error("model_check_failed");
    process.stdout.write(JSON.stringify({ schemaVersion: "ts-phone-models/1", models }) + "\n");
    return;
  }
  const { values } = parseArgs({ args, options: {
    mode: { type: "string" }, "session-id": { type: "string" }, session: { type: "string" },
    "session-dir": { type: "string" }, name: { type: "string" }, model: { type: "string" },
    "no-extensions": { type: "boolean" }, "no-skills": { type: "boolean" },
    "no-themes": { type: "boolean" }, "no-prompt-templates": { type: "boolean" },
    approve: { type: "boolean" }, skill: { type: "string", multiple: true },
    theme: { type: "string", multiple: true }, extension: { type: "string", short: "e", multiple: true },
  } });
  if (values.mode !== "rpc" || !process.env.TS_SESSION_ID || process.env.TS_PHONE_WORKER !== "1") {
    throw new Error("phone_worker_contract_invalid");
  }
  const cwd = process.cwd();
  const sessionDir = resolve(cwd, values["session-dir"] || ".pi/sessions");
  const matches = (await SessionManager.list(cwd, sessionDir)).filter((item) => item.id === values["session-id"]);
  if (matches.length > 1) throw new Error("session_guard_invalid");
  const sessionManager = matches[0]
    ? SessionManager.open(matches[0].path, sessionDir, cwd)
    : SessionManager.create(cwd, sessionDir, { id: values["session-id"] });
  if (sessionManager.getSessionId() !== process.env.TS_SESSION_ID) throw new Error("stale_session");
  process.env.TS_PHONE_SESSION_SETTINGS = "memory";
  const factory = async (target) => {
    if (target.cwd !== cwd || target.sessionManager.getSessionId() !== process.env.TS_SESSION_ID) {
      throw new Error("phone_worker_contract_invalid");
    }
    const settingsManager = sessionSettings(SettingsManager.create(cwd, agentDir));
    const services = await createAgentSessionServices({ cwd, agentDir, settingsManager, modelRuntime,
      resourceLoaderOptions: {
        noExtensions: true, noSkills: true, noThemes: true, noPromptTemplates: true,
        additionalExtensionPaths: values.extension,
        additionalSkillPaths: values.skill, additionalThemePaths: values.theme,
      },
    });
    const saved = sessionManager.getBranch().filter((entry) => entry.type === "model_change").at(-1);
    const selection = saved
      ? `${saved.provider}/${saved.modelId}`
      : values.model || `${settingsManager.getDefaultProvider()}/${settingsManager.getDefaultModel()}`;
    const available = await modelRuntime.getAvailable();
    const model = available.find((item) => `${item.provider}/${item.id}` === selection);
    // Never silently select a different provider when the saved model is missing.
    if (!model) throw new Error("model_unavailable");
    const created = await createAgentSessionFromServices({ services, sessionManager, model,
      sessionStartEvent: target.sessionStartEvent });
    if (values.name) created.session.setSessionName(values.name);
    return { ...created, services, diagnostics: services.diagnostics };
  };
  initTheme("dark", false);
  const runtime = await createAgentSessionRuntime(factory, { cwd, agentDir, sessionManager });
  await runRpcMode(runtime);
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  main(process.argv.slice(2)).catch((error) => {
    // Model configuration and provider errors can contain credentials.
    const safeCodes = new Set(["model_unavailable", "model_check_failed", "phone_worker_contract_invalid",
      "session_guard_invalid", "stale_session"]);
    const code = safeCodes.has(error?.message) ? error.message : "worker_start_failed";
    process.stderr.write(JSON.stringify({ type: "tspi.startup_error", code }) + "\n");
    process.exitCode = 1;
  });
}
