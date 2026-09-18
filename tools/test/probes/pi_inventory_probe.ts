import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export default function (pi: ExtensionAPI) {
  pi.registerCommand("ts-test-inventory", {
    description: "Emit the active tool inventory for the offline Pi integration test.",
    handler: async (_args, ctx) => {
      ctx.ui.notify(
        `TS_TEST_INVENTORY:${JSON.stringify({ active: pi.getActiveTools(), all: pi.getAllTools().map((tool) => tool.name) })}`,
        "info",
      );
    },
  });
}
