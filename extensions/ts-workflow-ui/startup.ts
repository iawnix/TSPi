import type { ExtensionAPI, ExtensionContext, Theme } from "@earendil-works/pi-coding-agent";
import { truncateToWidth, visibleWidth, type Component, type TUI } from "@earendil-works/pi-tui";
import { TS_PACKAGE_PROFILE } from "../shared/package-profile.ts";
import {
  borderLine,
  boxedLine,
  center,
  formatCwd,
  formatModelLabel,
  formatThinkingLabel,
  headerColumnWidths,
  padRight,
  stripAnsi,
  twoColumn,
} from "./render-utils.ts";

const LOGO_ANIMATION_INTERVAL_MS = 90;
const PIXEL = "██";
const EMPTY_PIXEL = " ".repeat(visibleWidth(PIXEL));
const TSPI_COMPACT_LOGO = "TSπ";
const TSPI_ANIMATION_FRAMES = 11;
const T_MASK = Object.freeze([
  "TTTTT",
  "  T  ",
  "  T  ",
  "  T  ",
  "  T  ",
  "  T  ",
  "  T  ",
]);
const S_MASK = Object.freeze([
  "SSSSS",
  "S    ",
  "S    ",
  "SSSSS",
  "    S",
  "    S",
  "SSSSS",
]);
const PI_MASK = Object.freeze([
  "PPPPPPP",
  " P   P ",
  " P   P ",
  " P   P ",
  " P   P ",
  " P   P ",
  "PP   PP",
]);
const TSPI_MASK = Object.freeze(T_MASK.map((line, index) => `${line}  ${S_MASK[index]}  ${PI_MASK[index]}`));
const TSPI_LOGO_WIDTH = TSPI_MASK[0]!.length * visibleWidth(PIXEL);

interface StartupPalette {
  accent: (text: string) => string;
  dim: (text: string) => string;
  link: (text: string) => string;
  muted: (text: string) => string;
  success: (text: string) => string;
  text: (text: string) => string;
  warning: (text: string) => string;
  bold: (text: string) => string;
}

export interface TspiStartupDetails {
  compact?: boolean;
  frame?: number;
  notificationDisplayTarget?: string;
  remoteDisplayTarget?: string;
  remoteConfigured?: boolean;
  modelLabel?: string;
  thinkingLabel?: string;
}

export function renderTspiStartupLines(
  workspaceRoot: string,
  width: number,
  details: TspiStartupDetails = {},
): string[] {
  return renderStartup(
    workspaceRoot,
    width,
    {
      accent: identity,
      dim: identity,
      link: identity,
      muted: identity,
      success: identity,
      text: identity,
      warning: identity,
      bold: identity,
    },
    details,
  ).map(stripAnsi);
}

export function createTspiStartupHeader(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  tui: TUI,
  workspaceRoot = process.env.TS_WORKSPACE_ROOT || ctx.cwd,
): Component & { dispose(): void } {
  let frame = 0;
  let timer: ReturnType<typeof setInterval> | undefined;

  const component = {
    render(width: number): string[] {
      const theme = ctx.ui.theme;
      return renderStartup(workspaceRoot, width, themePalette(theme), {
        compact: tui.terminal.rows > 0 && tui.terminal.rows < 25,
        frame,
        notificationDisplayTarget: process.env.TS_NOTIFICATION_DISPLAY_TARGET,
        remoteDisplayTarget: process.env.TS_REMOTE_DISPLAY_TARGET,
        remoteConfigured: Boolean(process.env.TS_REMOTE_CONFIG),
        modelLabel: formatModelLabel(ctx.model),
        thinkingLabel: formatThinkingLabel(pi.getThinkingLevel()),
      });
    },
    invalidate(): void {},
    dispose(): void {
      if (!timer) return;
      clearInterval(timer);
      timer = undefined;
    },
  };

  timer = setInterval(() => {
    if (frame >= TSPI_ANIMATION_FRAMES - 1) {
      component.dispose();
      return;
    }
    frame += 1;
    tui.requestRender();
  }, LOGO_ANIMATION_INTERVAL_MS);
  timer.unref?.();
  return component;
}

function renderStartup(
  workspaceRoot: string,
  width: number,
  palette: StartupPalette,
  details: TspiStartupDetails,
): string[] {
  const safeWidth = Math.max(1, Math.floor(width));
  const profile = TS_PACKAGE_PROFILE;
  if (safeWidth < 20) {
    return [truncateToWidth(palette.accent(`${TSPI_COMPACT_LOGO} ${profile.displayName}`), safeWidth, "")];
  }

  const innerWidth = safeWidth - 2;
  const { leftWidth, rightWidth, useRightColumn } = headerColumnWidths(innerWidth);
  const frame = details.frame ?? TSPI_ANIMATION_FRAMES - 1;
  const model = details.modelLabel || "Default model";
  const thinking = details.thinkingLabel || "ready";
  const cwd = formatCwd(workspaceRoot);
  const fullLogo = leftWidth >= TSPI_LOGO_WIDTH;
  const logo = fullLogo
    ? renderLogoFrame(frame, palette)
    : [palette.accent(TSPI_COMPACT_LOGO)];
  const visibleLogo = details.compact && logo.length > 1 ? logo.slice(1, 6) : logo;
  const heroLines = [
    ...visibleLogo.map((line) => center(line, leftWidth)),
    center(palette.muted("Evidence-driven transition-state workflow."), leftWidth),
    center(palette.dim(`${model} · ${thinking}`), leftWidth),
    center(palette.dim(cwd), leftWidth),
  ];

  const divider = palette.accent("─".repeat(Math.max(8, Math.min(22, rightWidth))));
  const packageSummary = `1 skill · ${profile.extensions.length} extensions`;
  const rightLines = [
    "",
    palette.accent(palette.bold(details.remoteConfigured ? "Remote configured" : "Remote")),
    palette.muted(remoteLabel(details.remoteDisplayTarget)),
    palette.muted(`Email · ${notificationLabel(details.notificationDisplayTarget)}`),
    divider,
    palette.accent(palette.bold("Package")),
    palette.muted(packageSummary),
    palette.muted("1 theme"),
    divider,
    palette.accent(palette.bold("Commands")),
    ...profile.commands.map((command) => palette.muted(command)),
  ];

  const bodyHeight = useRightColumn ? Math.max(heroLines.length, rightLines.length) : heroLines.length;
  const label = `${palette.accent(TSPI_COMPACT_LOGO)} ${palette.dim(`v${profile.version}`)}`;
  const lines = [borderLine("╭", label, "╮", safeWidth, palette.accent)];
  for (let index = 0; index < bodyHeight; index++) {
    const left = heroLines[index] || "";
    const content = useRightColumn
      ? twoColumn(left, rightLines[index] || "", leftWidth, rightWidth, palette.accent)
      : padRight(left, leftWidth);
    lines.push(boxedLine(content, safeWidth, palette.accent));
  }
  lines.push(borderLine("╰", "", "╯", safeWidth, palette.accent));
  return lines.map((line) => truncateToWidth(line, safeWidth, ""));
}

function renderLogoFrame(frameIndex: number, palette: StartupPalette): string[] {
  const frame = Math.max(0, Math.min(TSPI_ANIMATION_FRAMES - 1, frameIndex));
  return TSPI_MASK.map((row, y) => {
    let line = "";
    for (const cell of row) {
      if (cell === " ") {
        line += EMPTY_PIXEL;
        continue;
      }
      const offset = cell === "T" ? 0 : cell === "S" ? 1 : 2;
      line += frame >= Math.min(7, y + offset) ? paintLogoCell(cell, frame, palette) : EMPTY_PIXEL;
    }
    return line;
  });
}

function paintLogoCell(cell: string, frame: number, palette: StartupPalette): string {
  if (frame === 8) return palette.warning(PIXEL);
  if (frame === 9) return palette.accent(PIXEL);
  if (cell === "P") return palette.text(PIXEL);
  if (cell === "S") return palette.success(PIXEL);
  return palette.link(PIXEL);
}

function remoteLabel(displayTarget?: string): string {
  return displayTarget?.trim() || "not configured";
}

function notificationLabel(displayTarget?: string): string {
  return displayTarget?.trim() || "not configured";
}

function themePalette(theme: Theme): StartupPalette {
  return {
    accent: (text) => theme.fg("accent", text),
    dim: (text) => theme.fg("dim", text),
    link: (text) => theme.fg("mdLink", text),
    muted: (text) => theme.fg("muted", text),
    success: (text) => theme.fg("success", text),
    text: (text) => theme.fg("text", text),
    warning: (text) => theme.fg("warning", text),
    bold: (text) => theme.bold(text),
  };
}

function identity(text: string): string {
  return text;
}
