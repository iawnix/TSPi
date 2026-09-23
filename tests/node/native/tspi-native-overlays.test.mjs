import assert from "node:assert/strict";
import { chmod, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import test from "node:test";

import { createFacetHost } from "@earendil-works/chord";
import { RunHistoryBrowser, runRecords } from "../../../extensions/pi/tui-package/src/runs.ts";
import { WrappedDocumentViewer } from "../../../extensions/pi/tui-package/src/document-viewer.ts";
import {
  createTspiPackageRootRestoreFacet,
  withTspiPackageRootHidden,
} from "../../../apps/app-server/native-client-env.mjs";

const sourceRoot = process.env.TSPI_PI_SOURCE;
const piSlashModules = sourceRoot
  ? await Promise.all([
      import(pathToFileURL(join(sourceRoot, "packages/coding-agent/src/experimental/services/slash-commands-provider.ts")).href),
      import(pathToFileURL(join(sourceRoot, "packages/coding-agent/src/experimental/services/slash-commands.ts")).href),
      import(pathToFileURL(join(sourceRoot, "packages/coding-agent/src/experimental/services/presentation-ui.ts")).href),
    ])
  : undefined;

const theme = {
  fg: (_name, value) => value,
  bg: (_name, value) => value,
};

function fakeTui(rows = 12) {
  return {
    terminal: { rows },
    renders: 0,
    requestRender() { this.renders += 1; },
    showOverlay(component) {
      this.overlay = component;
      return { hide: () => { this.hidden = true; } };
    },
  };
}

function keybindings() {
  return { matches(data, key) { return data === key; } };
}

test("run records consume the compute.runs envelope and wrap long detail text", () => {
  const records = runRecords({
    schema_version: "compute-runs/1",
    runs: [{
      task_id: "sub_long",
      role: "compute",
      operation: "transition-state-validation-with-a-deliberately-long-operation-name",
      status: "failed",
      result_outcome: "failure",
      node_refs: [],
      claim_refs: [],
      summary: "A long summary that must remain readable in a narrow overlay instead of being silently truncated.",
      error_message: "The calculation stream disconnected before completion and left a useful diagnostic message.",
    }],
    attempts: [],
    summary: {},
  });
  assert.equal(records.length, 1);
  const tui = fakeTui(12);
  const browser = new RunHistoryBrowser(records, tui, theme, keybindings(), () => {});
  const first = browser.render(34);
  assert.ok(first.some((line) => line.includes("TS Subagent History")));
  browser.handleInput("tui.select.confirm");
  const detail = browser.render(34);
  const firstDetail = detail.join("\n");
  browser.handleInput("tui.select.pageDown");
  const secondDetail = browser.render(34).join("\n");
  assert.match(`${firstDetail}\n${secondDetail}`, /disconnected before/);
  assert.ok(detail.length <= 10);
  assert.ok(detail.every((line) => line.replace(/\x1b\[[0-9;]*m/g, "").length <= 34));
  assert.notEqual(secondDetail, firstDetail);
});

test("system prompt viewer pages wrapped content and closes without transcript work", () => {
  const tui = fakeTui(12);
  let closed = false;
  const viewer = new WrappedDocumentViewer(
    "Effective system prompt",
    Array.from({ length: 30 }, (_value, index) => `line-${index + 1} with additional content`).join("\n"),
    tui,
    theme,
    keybindings(),
    () => { closed = true; },
  );
  const first = viewer.render(34).join("\n");
  viewer.handleInput("tui.select.pageDown");
  const second = viewer.render(34).join("\n");
  assert.notEqual(second, first);
  viewer.handleInput("tui.select.cancel");
  assert.equal(closed, true);
  assert.ok(tui.renders >= 1);
});

test("overlay input is focused and Pi restores the editor focus on close", { skip: !sourceRoot }, async () => {
  const [{ TuiAltScreen }, { VirtualTerminal }, { KeybindingsManager }] = await Promise.all([
    import(pathToFileURL(join(sourceRoot, "packages/tui/src/tui-alt-screen.ts")).href),
    import(pathToFileURL(join(sourceRoot, "packages/tui/test/virtual-terminal.ts")).href),
    import(pathToFileURL(join(sourceRoot, "packages/coding-agent/src/core/keybindings.ts")).href),
  ]);
  const terminal = new VirtualTerminal(60, 20);
  const tui = new TuiAltScreen(terminal);
  const editor = {
    focused: false,
    render() { return ["editor"]; },
    invalidate() {},
    handleInput() {},
  };
  tui.addChild(editor);
  tui.setFocus(editor);
  tui.start();
  await terminal.waitForRender();
  let handle;
  const viewer = new WrappedDocumentViewer(
    "Prompt",
    Array.from({ length: 60 }, (_value, index) => `line-${index + 1}`).join("\n"),
    tui,
    theme,
    KeybindingsManager.create(),
    () => handle.hide(),
  );
  handle = tui.showOverlay(viewer, { width: "94%", maxHeight: "88%", margin: 1 });
  await terminal.waitForRender();
  assert.equal(tui.focusedComponent, viewer);
  const before = terminal.getViewport().join("\n");
  terminal.sendInput("\x1b[6~");
  await terminal.waitForRender();
  assert.notEqual(terminal.getViewport().join("\n"), before);
  terminal.sendInput("\x1b");
  await terminal.waitForRender();
  assert.equal(tui.focusedComponent, editor);
  tui.stop();
});

test("package root is hidden only during facet setup and restored on every path", { skip: !piSlashModules }, async () => {
  const [{ createSlashCommandsRuntimeFacet }, { SlashCommands }, { PresentationUI }] = piSlashModules;
  const previous = process.env.TSPI_PACKAGE_ROOT;
  try {
    process.env.TSPI_PACKAGE_ROOT = "/tmp/tspi-package-root-test";
    const seen = [];
    const restoreFacet = await withTspiPackageRootHidden(async (restore) => {
      assert.equal(process.env.TSPI_PACKAGE_ROOT, undefined);
      const host = await createFacetHost({
        facets: [
          createSlashCommandsRuntimeFacet(),
          {
            id: "test-presentation-bridge",
            setup(env) {
              env.provide(PresentationUI, {});
            },
          },
          {
            id: "test-built-in",
            setup(env) {
              env.use(SlashCommands);
              env.use(PresentationUI);
              seen.push(["setup", process.env.TSPI_PACKAGE_ROOT]);
              env.onActivate(() => seen.push(["activate", process.env.TSPI_PACKAGE_ROOT]));
            },
          },
          createTspiPackageRootRestoreFacet(restore, PresentationUI),
        ],
      });
      await host.dispose();
      return process.env.TSPI_PACKAGE_ROOT;
    });
    assert.equal(restoreFacet, "/tmp/tspi-package-root-test");
    assert.deepEqual(seen, [["setup", undefined], ["activate", undefined]]);
    assert.equal(process.env.TSPI_PACKAGE_ROOT, "/tmp/tspi-package-root-test");

    await assert.rejects(
      withTspiPackageRootHidden(async () => {
        assert.equal(process.env.TSPI_PACKAGE_ROOT, undefined);
        throw new Error("expected failure");
      }),
      /expected failure/,
    );
    assert.equal(process.env.TSPI_PACKAGE_ROOT, "/tmp/tspi-package-root-test");

    await assert.rejects(
      withTspiPackageRootHidden(() => {
        assert.equal(process.env.TSPI_PACKAGE_ROOT, undefined);
        throw new Error("expected sync failure");
      }),
      /expected sync failure/,
    );
    assert.equal(process.env.TSPI_PACKAGE_ROOT, "/tmp/tspi-package-root-test");

    delete process.env.TSPI_PACKAGE_ROOT;
    await withTspiPackageRootHidden(async () => {
      assert.equal(process.env.TSPI_PACKAGE_ROOT, undefined);
    });
    assert.equal(process.env.TSPI_PACKAGE_ROOT, undefined);
  } finally {
    if (previous === undefined) delete process.env.TSPI_PACKAGE_ROOT;
    else process.env.TSPI_PACKAGE_ROOT = previous;
  }
});

test("native facet source is available for overlay integration tests", { skip: !sourceRoot }, async () => {
  const { createTspiNativeClientFacet } = await import("../../../apps/app-server/tspi-native-client-facet.mjs");
  const root = await mkdtemp(join(tmpdir(), "tspi-native-overlay-"));
  const previousPython = process.env.TSPI_WORKSPACE_PYTHON;
  const fakePython = join(root, "fake-python.sh");
  await writeFile(fakePython, [
    "#!/bin/sh",
    "printf '%s' '{\"schema_version\":\"compute-runs/1\",\"runs\":[{\"task_id\":\"sub_1\",\"role\":\"compute\",\"operation\":\"launch\",\"status\":\"completed\",\"node_refs\":[],\"claim_refs\":[],\"summary\":\"done\"}],\"attempts\":[],\"summary\":{}}'",
  ].join("\n"));
  await chmod(fakePython, 0o755);
  process.env.TSPI_WORKSPACE_PYTHON = fakePython;
  try {
    const facet = await withTspiPackageRootHidden(() => createTspiNativeClientFacet({ sourceRoot, packageRoot: process.cwd() }));
    assert.equal(facet.id, "@tspi/native-client-commands");
    let activate;
    const commands = [];
    const usedServices = [];
    const statuses = [];
    const tui = fakeTui(12);
    const context = {
      cwd: root,
      tui,
      theme,
      keybindings: keybindings(),
      requestRender() {},
    };
    const implementations = new Map([
      ["pi.local.slash-commands", { replace(command) { commands.push(command); return () => {}; } }],
      ["pi.local.presentation-ui", { showStatus(value) { statuses.push(value); } }],
      ["pi.local.presentation-layout", { getContext() { return context; } }],
      ["tspi.system-prompt", { async inspect() { return { effective: "prompt" }; } }],
    ]);
    facet.setup({
      use(service) {
        usedServices.push(service.id);
        return implementations.get(service.id);
      },
      onActivate(callback) { activate = callback; },
      own() {},
    });
    activate();
    assert.deepEqual(commands.map(({ name }) => name).sort(), ["compute", "debug", "research", "runs", "sys_prompt"]);
    assert.equal(usedServices.includes("pi.local.transcript"), false);

    await commands.find(({ name }) => name === "runs").run("", { abortSignal: new AbortController().signal });
    assert.equal(tui.overlay.constructor.name, "RunHistoryBrowser");
    assert.deepEqual(statuses, [""]);

    await commands.find(({ name }) => name === "sys_prompt").run("", { abortSignal: new AbortController().signal });
    assert.equal(tui.overlay.constructor.name, "WrappedDocumentViewer");
    assert.deepEqual(statuses, ["", ""]);
  } finally {
    if (previousPython === undefined) delete process.env.TSPI_WORKSPACE_PYTHON;
    else process.env.TSPI_WORKSPACE_PYTHON = previousPython;
    await rm(root, { recursive: true, force: true });
  }
});
