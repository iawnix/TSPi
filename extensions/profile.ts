import { SLASH_COMMAND_NAMES } from "../packages/ts-agent-runtime/host-api/commands.mjs";

export const TS_PACKAGE_PROFILE = Object.freeze({
  displayName: "TSPi",
  version: "0.17.0",
  title: "TSPi research workspace",
  description: "Domain-neutral ResearchMap scientific workflows with deterministic execution.",
  skills: Object.freeze([
    Object.freeze({ name: "tspi-research-kernel", path: "./skills/tspi-research-kernel" }),
    Object.freeze({ name: "tspi-orchestration", path: "./skills/tspi-orchestration" }),
    Object.freeze({ name: "tspi-ts-candidate-generation", path: "./skills/tspi-ts-candidate-generation" }),
    Object.freeze({ name: "tspi-ts-validation", path: "./skills/tspi-ts-validation" }),
    Object.freeze({ name: "tspi-irc", path: "./skills/tspi-irc" }),
    Object.freeze({ name: "tspi-energetics", path: "./skills/tspi-energetics" }),
    Object.freeze({ name: "tspi-method-selection", path: "./skills/tspi-method-selection" }),
    Object.freeze({ name: "cf22d", path: "./skills/cf22d" }),
    Object.freeze({ name: "tspi-xtb", path: "./skills/tspi-xtb" }),
    Object.freeze({ name: "tspi-crest", path: "./skills/tspi-crest" }),
    Object.freeze({ name: "tspi-qbics", path: "./skills/tspi-qbics" }),
    Object.freeze({ name: "tspi-gaussian", path: "./skills/tspi-gaussian" }),
    Object.freeze({ name: "tspi-report", path: "./skills/tspi-report" }),
    Object.freeze({ name: "tspi-render", path: "./skills/tspi-render" }),
    Object.freeze({ name: "tspi-email", path: "./skills/tspi-email" }),
    Object.freeze({ name: "tspi-mechanism-reasoning", path: "./skills/tspi-mechanism-reasoning" }),
    Object.freeze({ name: "tspi-chemical-input", path: "./skills/tspi-chemical-input" }),
  ]),
  // Native Pi Harness owns the agent loop and server tools. Direct
  // ExtensionAPI modules are retired and must not be auto-loaded.
  extensions: Object.freeze([]),
  theme: Object.freeze({ name: "ts-theme", path: "./themes/ts-theme.json" }),
  commands: SLASH_COMMAND_NAMES,
});
