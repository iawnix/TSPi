import type { Theme } from "@earendil-works/pi-coding-agent";
import { truncateToWidth, visibleWidth, type Component, type TUI } from "@earendil-works/pi-tui";
import { fitColumns, formatCwd } from "../../ui/render-utils.ts";
import type { PresentationLayoutContext } from "@earendil-works/pi-coding-agent/experimental/plugin";

const LOGO = [
  "█████  █████  ███████",
  "  █    █      █   █  ",
  "  █    █      █   █  ",
  "  █    █████  █   █  ",
  "  █        █  █   █  ",
  "  █        █  █   █  ",
  "  █    █████  ███████",
];

export function createTspiPresentationHeader(
  context: PresentationLayoutContext,
  workspaceRoot: string,
  details: () => { modelLabel?: string; thinkingLabel?: string },
): Component & { dispose(): void } {
  let frame = 0;
  let timer: ReturnType<typeof setInterval> | undefined;
  const component = {
    render(width: number): string[] {
      return renderHeader(context.tui, context.theme, workspaceRoot, details(), frame, width);
    },
    invalidate(): void {},
    dispose(): void {
      if (!timer) return;
      clearInterval(timer);
      timer = undefined;
    },
  };
  timer = setInterval(() => {
    if (frame >= 5) {
      component.dispose();
      return;
    }
    frame += 1;
    context.requestRender();
  }, 90);
  timer.unref?.();
  return component;
}

function renderHeader(
  tui: TUI,
  theme: Theme,
  workspaceRoot: string,
  details: { modelLabel?: string; thinkingLabel?: string },
  frame: number,
  width: number,
): string[] {
  const safeWidth = Math.max(1, Math.floor(width));
  if (safeWidth < 20) return [truncateToWidth(theme.fg("accent", "TSπ TSPi"), safeWidth, "")];
  const inner = safeWidth - 2;
  const compact = tui.terminal.rows > 0 && tui.terminal.rows < 25;
  const leftWidth = Math.max(16, Math.floor((inner - 3) * 0.55));
  const rightWidth = Math.max(12, inner - leftWidth - 3);
  const logo = compact ? "TSπ" : frame < 5 ? LOGO[Math.min(frame, LOGO.length - 1)]! : "TSπ  TSPi";
  const left = [
    center(theme.fg("accent", logo), leftWidth),
    center(theme.fg("muted", "DAG-based transition-state research."), leftWidth),
    center(theme.fg("dim", `${details.modelLabel || "Default model"} · ${details.thinkingLabel || "ready"}`), leftWidth),
    center(theme.fg("dim", formatCwd(workspaceRoot)), leftWidth),
  ];
  const right = [
    theme.bold(theme.fg("accent", "TSPi")),
    theme.fg("muted", process.env.TS_COMPUTE_DISPLAY_TARGET?.trim() || "Compute not configured"),
    theme.fg("muted", `Email · ${process.env.TS_NOTIFICATION_DISPLAY_TARGET?.trim() || "not configured"}`),
    theme.fg("dim", "Theme · ts-theme"),
  ];
  const bodyHeight = Math.max(left.length, right.length);
  const lines = [theme.fg("accent", `╭─ TSπ ${"─".repeat(Math.max(0, safeWidth - 8))}╮`)];
  for (let index = 0; index < bodyHeight; index += 1) {
    const content = safeWidth >= 64
      ? fitColumns(left[index] || "", right[index] || "", inner)
      : `${left[index] || ""}`;
    lines.push(theme.fg("accent", "│") + pad(content, inner) + theme.fg("accent", "│"));
  }
  lines.push(theme.fg("accent", `╰${"─".repeat(Math.max(0, safeWidth - 2))}╯`));
  return lines.map((line) => truncateToWidth(line, safeWidth, ""));
}

function center(text: string, width: number): string {
  const clipped = truncateToWidth(text, width, "…");
  const padding = Math.max(0, width - visibleWidth(clipped));
  return `${" ".repeat(Math.floor(padding / 2))}${clipped}${" ".repeat(Math.ceil(padding / 2))}`;
}

function pad(text: string, width: number): string {
  const clipped = truncateToWidth(text, width, "…");
  return clipped + " ".repeat(Math.max(0, width - visibleWidth(clipped)));
}
