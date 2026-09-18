/** One command catalog for the Pi client and package profile. */
export const TS_COMMAND_CATALOG = Object.freeze([
  Object.freeze({ name: "research", description: "Read and validate the current ResearchMap." }),
  Object.freeze({ name: "compute", description: "Inspect configured local and remote compute environments." }),
  Object.freeze({ name: "runs", description: "Browse durable compute and review records." }),
  Object.freeze({ name: "debug", description: "Inspect TSPi runtime diagnostics." }),
]);

export const TS_COMMAND_NAMES = Object.freeze(TS_COMMAND_CATALOG.map((command) => `/${command.name}`));
