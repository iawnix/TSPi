import { SLASH_COMMAND_NAMES } from "../packages/ts-agent-runtime/host-api/commands.mjs";

export const TS_PACKAGE_PROFILE = Object.freeze({
  displayName: "TSPi",
  version: "0.17.0",
  title: "TSPi research orchestration",
  description: "Phase-guided TS research with a ResearchNode DAG and deterministic validation.",
  skills: Object.freeze([
    Object.freeze({ name: "tspi-orchestration", path: "./skills/tspi-orchestration" }),
    Object.freeze({ name: "tspi-transition-state-search", path: "./skills/tspi-transition-state-search" }),
    Object.freeze({ name: "tspi-xtb", path: "./skills/tspi-xtb" }),
    Object.freeze({ name: "tspi-gaussian", path: "./skills/tspi-gaussian" }),
    Object.freeze({ name: "tspi-connectivity", path: "./skills/tspi-connectivity" }),
    Object.freeze({ name: "tspi-mechanism", path: "./skills/tspi-mechanism" }),
    Object.freeze({ name: "tspi-render", path: "./skills/tspi-render" }),
    Object.freeze({ name: "tspi-report", path: "./skills/tspi-report" }),
    Object.freeze({ name: "tspi-email", path: "./skills/tspi-email" }),
  ]),
  extensions: Object.freeze([
    Object.freeze({ name: "research", path: "./extensions/pi/research/index.ts" }),
    Object.freeze({ name: "ui", path: "./extensions/pi/ui/index.ts" }),
    Object.freeze({ name: "review", path: "./extensions/pi/review/index.ts" }),
    Object.freeze({ name: "compute", path: "./extensions/pi/compute/index.ts" }),
    Object.freeze({ name: "artifacts", path: "./extensions/pi/artifacts/index.ts" }),
  ]),
  theme: Object.freeze({ name: "ts-theme", path: "./themes/ts-theme.json" }),
  commands: SLASH_COMMAND_NAMES,
});
