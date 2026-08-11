export const TS_PACKAGE_PROFILE = Object.freeze({
  displayName: "TSPi",
  version: "0.3.1",
  title: "Transition-state workflow",
  description: "Evidence-driven TS search, compute, validation, and audit.",
  skill: Object.freeze({
    name: "transition-state-workflow",
    path: "./skills/transition-state-workflow",
  }),
  extensions: Object.freeze([
    Object.freeze({ name: "control", path: "./extensions/ts-workflow-control" }),
    Object.freeze({ name: "ui", path: "./extensions/ts-workflow-ui/index.ts" }),
    Object.freeze({ name: "review", path: "./extensions/ts-workflow-review/index.ts" }),
    Object.freeze({ name: "compute", path: "./extensions/ts-workflow-compute/index.ts" }),
    Object.freeze({ name: "artifacts", path: "./extensions/ts-workflow-artifacts/index.ts" }),
  ]),
  theme: Object.freeze({ name: "ts-theme", path: "./themes/ts-theme.json" }),
  commands: Object.freeze(["/ts-context", "/ts-validate", "/ts-mcp"]),
});
