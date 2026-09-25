import { execFile } from "node:child_process";
import { join } from "node:path";
import { promisify } from "node:util";
import { defineFacet } from "@earendil-works/chord";
import {
  PresentationLayout,
  type PresentationLayoutContext,
  PresentationUI,
  SlashCommands,
  Transcript,
} from "@earendil-works/pi-coding-agent/experimental/plugin";
import { type Component, truncateToWidth } from "@earendil-works/pi-tui";
import { fitColumns, formatCwd } from "../../ui/render-utils.ts";
import { tspiIconLabel, tspiModelIconLabel } from "../../shared/icons.ts";
import { TspiPresentationEditor } from "./editor.ts";
import { createTspiPresentationHeader } from "./header.ts";
import { RunHistoryBrowser, runRecords } from "./runs.ts";
import {
  NATIVE_PRESENTATION_TOOL_NAMES,
  renderTsNativeCall,
  renderTsNativeResult,
} from "../../shared/native-tool-presentation.ts";
import {
  renderTsArtifactCall,
  renderTsArtifactResult,
  type ArtifactToolKind,
} from "../../shared/artifact-tool-presentation.ts";
import { renderTsReviewCall, renderTsReviewResult } from "../../shared/review-tool-presentation.ts";

const PRESENTATION_TOOL_RENDERERS = Object.freeze({
  ...Object.fromEntries(
    (["seed", "compare", "analyze", "import", "render", "report"] as ArtifactToolKind[]).map((kind) => [
      `ts_${kind === "import" ? "import" : kind}`,
      {
        renderCall: (args: Record<string, unknown>, theme: any) => renderTsArtifactCall(kind, args, theme),
        renderResult: (result: any, options: any, theme: any, context: any) =>
          renderTsArtifactResult(kind, result, options, theme, context.isError),
      },
    ]),
  ),
  ts_review: {
    renderCall: (args: Record<string, unknown>, theme: any) => renderTsReviewCall(args, theme),
    renderResult: (result: any, options: any, theme: any, context: any) =>
      renderTsReviewResult(result, options, theme, context.isError),
  },
  ...Object.fromEntries(
    NATIVE_PRESENTATION_TOOL_NAMES.map((toolName) => [
      toolName,
      {
        renderCall: (args: Record<string, unknown>, theme: any) => renderTsNativeCall(toolName, args, theme),
        renderResult: (result: any, options: any, theme: any, context: any) =>
          renderTsNativeResult(toolName, result, options, theme, context.isError),
      },
    ]),
  ),
});

const execFileAsync = promisify(execFile);

class TspiFooter implements Component {
  constructor(
    private readonly context: PresentationLayoutContext,
    private readonly transcript: { readonly state: { readonly value: any } },
  ) {}

  render(width: number): string[] {
    const snapshot = this.transcript.state.value?.snapshot;
    const session = snapshot?.stats?.messageCount === undefined ? "session" : `${snapshot.stats.messageCount} messages`;
    const model = snapshot?.configuration?.model;
    const modelText = model ? tspiModelIconLabel({ provider: model.provider, id: model.modelId }) : "model pending";
    const thinking = snapshot?.configuration?.thinkingLevel;
    const left = this.context.theme.fg(
      "muted",
      [tspiIconLabel("session", session), width >= 96 ? tspiIconLabel("cwd", formatCwd(this.context.cwd)) : undefined]
        .filter((value): value is string => Boolean(value))
        .join(" · "),
    );
    const right = this.context.theme.fg(
      "muted",
      [width >= 72 && thinking ? tspiIconLabel("thinking", thinking) : undefined, modelText]
        .filter((value): value is string => Boolean(value))
        .join(" · "),
    );
    if (width < 58) return [truncateToWidth(right, width, "")];
    return [fitColumns(left, right, width)];
  }

  invalidate(): void {}
}

async function readRunReport(root: string): Promise<Record<string, unknown>> {
  const packageRoot = process.env.TSPI_PACKAGE_ROOT;
  if (!packageRoot) throw new Error("TSPi package root is unavailable");
  const python = process.env.TS_AGENT_PYTHON || "python3";
  const script = join(packageRoot, "scripts", "ts_api.py");
  const result = await execFileAsync(python, [script, "compute.runs", "--root", root], {
    cwd: root,
    maxBuffer: 8 * 1024 * 1024,
    encoding: "utf8",
  });
  const parsed: unknown = JSON.parse(result.stdout);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("compute.runs returned invalid data");
  return parsed as Record<string, unknown>;
}

async function showRuns(
  layout: PresentationLayout,
  ui: PresentationUI,
  commandContext: import("@earendil-works/chord").Context,
): Promise<void> {
  const context = layout.getContext();
  let report: Record<string, unknown>;
  try {
    report = await readRunReport(context.cwd);
  } catch (error) {
    ui.showStatus(`Unable to read TS runs: ${error instanceof Error ? error.message : String(error)}`, commandContext);
    return;
  }
  const records = runRecords(report);
  if (records.length === 0) {
    ui.showStatus("No TS subagent runs are available in this workspace", commandContext);
    return;
  }
  let handle: { hide(): void } | undefined;
  const browser = new RunHistoryBrowser(
    records,
    context.tui,
    context.theme,
    context.keybindings,
    () => handle?.hide(),
  );
  handle = context.tui.showOverlay(browser, { width: "94%", maxHeight: "88%", margin: 1 });
}

export default defineFacet({
  id: "@iawnix/tspi-presentation/tui",
  setup(env) {
    const layout = env.use(PresentationLayout);
    const ui = env.use(PresentationUI);
    const commands = env.use(SlashCommands);
    const transcript = env.use(Transcript);
    const rendererOnly = process.env.TSPI_PRESENTATION_RENDERERS_ONLY === "1";
    let latestSnapshot: any;
    env.onActivate(() => {
      if (rendererOnly) {
        env.own(layout.setToolRenderers(PRESENTATION_TOOL_RENDERERS));
        return;
      }
      latestSnapshot = transcript.state.value?.snapshot;
      const context = layout.getContext();
      const workspaceRoot = process.env.TS_WORKSPACE_ROOT || context.cwd;
      const unsubscribe = transcript.state.subscribe((value) => {
        latestSnapshot = value.snapshot;
        // Transcript rendering is coalesced by the native client. Avoid
        // scheduling an extra frame for high-frequency streaming events.
        const eventType = value.event?.type;
        if (eventType !== "message_update" && eventType !== "tool_update" && eventType !== "usage") {
          layout.requestRender();
        }
      });
      layout.setHeader((headerContext) => createTspiPresentationHeader(
        headerContext,
        workspaceRoot,
        () => {
          const model = latestSnapshot?.configuration?.model;
          return {
            modelLabel: model ? `${model.provider}/${model.modelId}` : undefined,
            thinkingLabel: latestSnapshot?.configuration?.thinkingLevel,
          };
        },
      ));
      layout.setFooter((footerContext) => new TspiFooter(footerContext, transcript));
      layout.setEditor((editorContext) => new TspiPresentationEditor(editorContext));
      const removeToolRenderers = layout.setToolRenderers(PRESENTATION_TOOL_RENDERERS);
      layout.setTitle(`TSPi · ${formatCwd(workspaceRoot)}`);
      const removeRuns = commands.replace({
        name: "runs",
        description: "Browse active and recorded Compute and Review runs.",
        async run(_args, commandContext) {
          await showRuns(layout, ui, commandContext);
        },
      });
      env.own(() => {
        removeRuns();
        unsubscribe();
        layout.setHeader(undefined);
        layout.setFooter(undefined);
        layout.setEditor(undefined);
        removeToolRenderers();
      });
    });
  },
});
