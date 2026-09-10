import { parseArgs } from "node:util";
import * as PiTui from "@earendil-works/pi-tui";
import { HostClient, hostConnection } from "./host-client.mjs";
import { TerminalController } from "./controller.mjs";
import { TerminalView, safeText } from "./view.mjs";

async function main() {
  const { values } = parseArgs({ options: {
    "install-root": { type: "string" }, workspace: { type: "string" },
    "session-id": { type: "string" }, latest: { type: "boolean" },
  } });
  if (!values["install-root"]) throw new Error("--install-root is required");
  if (!process.stdin.isTTY || !process.stdout.isTTY) throw new Error("The thin terminal requires a TTY; use --standalone for native Pi batch/RPC modes.");
  const client = new HostClient(await hostConnection(values["install-root"]));
  const version = await client.request("/version");
  if (!version.capabilities?.includes("terminal.attach")) {
    throw new Error("This Host does not support terminal attachment. Synchronize the complete TSPi package and restart Host.");
  }
  const terminal = new PiTui.ProcessTerminal();
  // Pi 0.85 names the existing main-screen renderer TuiMainScreen.
  const Renderer = PiTui.TuiMainScreen ?? PiTui.TUI;
  if (!Renderer) throw new Error("The selected Pi installation has no supported terminal renderer.");
  const tui = new Renderer(terminal, true);
  const controller = new TerminalController(client);
  let quit;
  const done = new Promise((resolve) => { quit = resolve; });
  const view = new TerminalView(tui, controller, quit);
  const interrupted = () => quit();
  process.once("SIGTERM", interrupted);
  process.once("SIGINT", interrupted);
  process.once("SIGHUP", interrupted);
  terminal.write("\x1b[?1049h");
  try {
    tui.addChild(view);
    tui.setFocus(view);
    tui.start();
    void view.perform(() => view.start({ workspaceId: values.workspace, sessionId: values["session-id"], latest: values.latest }));
    await done;
  } finally {
    client.close();
    await controller.close();
    tui.stop();
    await terminal.drainInput();
    terminal.write("\x1b[?1049l");
    process.off("SIGTERM", interrupted);
    process.off("SIGINT", interrupted);
    process.off("SIGHUP", interrupted);
  }
  process.stdout.write(`Detached from Host. Worker and remote calculations are unchanged.${controller.unconfirmed ? " A message receipt is unconfirmed; inspect history before resending." : ""}\n`);
}

main().catch((error) => { process.stderr.write(`TSPi: ${safeText(error.message)}\n`); process.exitCode = 1; });
