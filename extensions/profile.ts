import { SLASH_COMMAND_NAMES } from "../packages/agent-runtime/host-api/commands.mjs";

export const TS_PACKAGE_PROFILE = Object.freeze({
  displayName: "TSPi",
  version: "0.17.0",
  title: "TSPi research workspace",
  description: "Domain-neutral ResearchMap scientific workflows with deterministic execution.",
  skills: Object.freeze([
    Object.freeze({ name: "research-state", path: "./extensions/core/skills/research-state" }),
    Object.freeze({ name: "orchestration", path: "./extensions/core/skills/orchestration" }),
    Object.freeze({ name: "candidate-generation", path: "./extensions/chemical/skills/candidate-generation" }),
    Object.freeze({ name: "validation", path: "./extensions/chemical/skills/validation" }),
    Object.freeze({ name: "irc", path: "./extensions/chemical/skills/irc" }),
    Object.freeze({ name: "energetics", path: "./extensions/chemical/skills/energetics" }),
    Object.freeze({ name: "method-selection", path: "./extensions/chemical/skills/method-selection" }),
    Object.freeze({ name: "cf22d", path: "./extensions/chemical/skills/cf22d" }),
    Object.freeze({ name: "xtb", path: "./extensions/chemical/skills/xtb" }),
    Object.freeze({ name: "crest", path: "./extensions/chemical/skills/crest" }),
    Object.freeze({ name: "qbics", path: "./extensions/chemical/skills/qbics" }),
    Object.freeze({ name: "gaussian", path: "./extensions/chemical/skills/gaussian" }),
    Object.freeze({ name: "chemical-input", path: "./extensions/chemical/skills/chemical-input" }),
    Object.freeze({ name: "mechanism-reasoning", path: "./extensions/chemical/skills/mechanism-reasoning" }),
    Object.freeze({ name: "email", path: "./extensions/email" }),
  ]),
  // Native Pi Harness owns the agent loop and server tools. Direct
  // ExtensionAPI modules are retired and must not be auto-loaded.
  extensions: Object.freeze([]),
  // Installed Skills, capability providers, and explicitly allowlisted
  // Harness tools are discovered by the App Server from manifest paths; they
  // are not part of this profile's static core inventory.
  installedExtensionManifests: Object.freeze({
    environment: "TSPI_EXTENSION_MANIFESTS",
    serverAllowlistEnvironment: "TSPI_INSTALLED_SERVER_EXTENSIONS",
    schema: "tspi-extension/1",
  }),
  theme: Object.freeze({ name: "ts-theme", path: "./packages/agent-ui/themes/ts-theme.json" }),
  commands: SLASH_COMMAND_NAMES,
});
