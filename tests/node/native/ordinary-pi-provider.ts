import { createAssistantMessageEventStream } from "@earendil-works/pi-ai";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

/** Local deterministic provider: integration tests never contact a model API. */
export default function fixture(pi: ExtensionAPI) {
  pi.registerProvider("tspi-fixture", {
    baseUrl: "http://127.0.0.1:1", apiKey: "fixture-only", api: "tspi-fixture-api",
    models: [{ id: "echo", name: "Local fixture", reasoning: false, input: ["text"],
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 200000, maxTokens: 1024 }],
    streamSimple(model, context) {
      const stream = createAssistantMessageEventStream();
      const user = context.messages.findLast((message) => message.role === "user");
      const text = typeof user?.content === "string" ? user.content : user?.content.map((block) => block.type === "text" ? block.text : "").join("") || "";
      const output: any = { role: "assistant", content: [], api: model.api, provider: model.provider, model: model.id,
        usage: { input: 1, output: 1, cacheRead: 0, cacheWrite: 0, totalTokens: 2, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } },
        stopReason: "stop", timestamp: Date.now() };
      void (async () => {
        stream.push({ type: "start", partial: output });
        output.content.push({ type: "text", text: "" });
        stream.push({ type: "text_start", contentIndex: 0, partial: output });
        await new Promise((done) => setTimeout(done, 100));
        output.content[0].text = `fixture reply: ${text}`;
        stream.push({ type: "text_delta", contentIndex: 0, delta: output.content[0].text, partial: output });
        stream.push({ type: "text_end", contentIndex: 0, content: output.content[0].text, partial: output });
        stream.push({ type: "done", reason: "stop", message: output });
        stream.end();
      })();
      return stream;
    },
  });
}
