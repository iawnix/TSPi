import type { Theme } from "@earendil-works/pi-coding-agent";
import { visibleWidth, type Component } from "@earendil-works/pi-tui";
import { TS_PACKAGE_PROFILE } from "../shared/package-profile.ts";

const FULL_LAYOUT_MIN_WIDTH = 48;
const LABEL_WIDTH = 13;
const ITEM_SEPARATOR = " · ";
const PIXEL = "■";
const EMPTY_PIXEL = " ".repeat(visibleWidth(PIXEL));
const TSPI_COMPACT_LOGO = "TSπ";
const T_MASK = Object.freeze([
  "WWWWW",
  "  W  ",
  "  W  ",
  "  W  ",
  "  W  ",
  "  W  ",
  "  W  ",
]);
const S_MASK = Object.freeze([
  "WWWWW",
  "W    ",
  "W    ",
  "WWWWW",
  "    W",
  "    W",
  "WWWWW",
]);
const PI_MASK = Object.freeze([
  "PPPPPPP",
  " P   P ",
  " P   P ",
  " P   P ",
  " P   P ",
  " P  PP ",
  "P    PP",
]);
const TSPI_LOGO_MASK = Object.freeze(T_MASK.map((line, index) => `${line}  ${S_MASK[index]}  ${PI_MASK[index]}`));
const TSPI_LOGO_LINES = Object.freeze(TSPI_LOGO_MASK.map(renderPixelMask));
const TSPI_LOGO_WIDTH = Math.max(...TSPI_LOGO_LINES.map((line) => visibleWidth(line)));
const TSPI_LOGO_MIN_WIDTH = TSPI_LOGO_WIDTH + 4;

export function renderTspiStartupLines(workspaceRoot: string, width: number): string[] {
  const safeWidth = Math.max(1, Math.floor(width));
  const profile = TS_PACKAGE_PROFILE;
  const innerWidth = safeWidth >= 4 ? safeWidth - 2 : safeWidth;
  const content = renderTspiStartupContent(workspaceRoot, innerWidth);

  if (safeWidth < 4) return fitLines(content, safeWidth);
  return [
    frameLine("╭", "╮", `${profile.displayName} v${profile.version}`, safeWidth),
    ...content.map((line) => `│${padPlainText(line, innerWidth)}│`),
    frameLine("╰", "╯", "", safeWidth),
  ];
}

function renderTspiStartupContent(workspaceRoot: string, width: number): string[] {
  const profile = TS_PACKAGE_PROFILE;
  const logo = renderTspiLogo(width);

  if (width < FULL_LAYOUT_MIN_WIDTH - 2) {
    return fitLines([
      ...logo,
      profile.title,
      ...renderRow("Workspace", [workspaceRoot], width),
      ...renderRow(
        "Resources",
        [`1 skill`, `${profile.extensions.length} extensions`, profile.theme.name],
        width,
      ),
      ...renderRow("Commands", profile.commands, width),
    ], width);
  }

  return fitLines([
    ...logo,
    profile.title,
    profile.description,
    ...renderRow("Workspace", [workspaceRoot], width),
    ...renderRow("Skill", [profile.skill.name], width),
    ...renderRow("Extensions", profile.extensions.map((extension) => extension.name), width),
    ...renderRow("Theme", [profile.theme.name], width),
    ...renderRow("Commands", profile.commands, width),
  ], width);
}

export function createTspiStartupHeader(theme: Theme, workspaceRoot: string): Component {
  return {
    render(width: number): string[] {
      return renderTspiStartupLines(workspaceRoot, width).map((line) => colorLine(theme, line));
    },
    invalidate(): void {},
  };
}

function renderTspiLogo(width: number): string[] {
  if (width < TSPI_LOGO_MIN_WIDTH) return [centerPlainText(TSPI_COMPACT_LOGO, width)];
  return TSPI_LOGO_LINES.map((line) => centerPlainText(line, width));
}

function renderPixelMask(mask: string): string {
  return [...mask].map((cell) => cell === " " ? EMPTY_PIXEL : PIXEL).join("");
}

function renderRow(label: string, items: readonly string[], width: number): string[] {
  if (width <= LABEL_WIDTH + 3) {
    return [`${label} ${items.join(ITEM_SEPARATOR)}`];
  }

  const contentWidth = width - LABEL_WIDTH;
  const contentLines = wrapItems(items, contentWidth);
  return contentLines.map((line, index) => `${index === 0 ? label.padEnd(LABEL_WIDTH) : " ".repeat(LABEL_WIDTH)}${line}`);
}

function wrapItems(items: readonly string[], width: number): string[] {
  const lines: string[] = [];
  let current = "";

  for (const item of items) {
    const candidate = current ? `${current}${ITEM_SEPARATOR}${item}` : item;
    if (current && visibleWidth(candidate) > width) {
      lines.push(current);
      current = item;
    } else {
      current = candidate;
    }
  }

  if (current) lines.push(current);
  return lines.length > 0 ? lines : [""];
}

function fitLines(lines: string[], width: number): string[] {
  return lines.map((line) => truncatePlainText(line, width));
}

function centerPlainText(value: string, width: number): string {
  const clipped = truncatePlainText(value, width);
  const padding = Math.max(0, width - visibleWidth(clipped));
  return `${" ".repeat(Math.floor(padding / 2))}${clipped}`;
}

function frameLine(left: string, right: string, label: string, width: number): string {
  if (width === 1) return "─";
  const innerWidth = width - 2;
  const decoratedLabel = label ? `── ${label} ` : "";
  const body = visibleWidth(decoratedLabel) <= innerWidth
    ? `${decoratedLabel}${"─".repeat(innerWidth - visibleWidth(decoratedLabel))}`
    : "─".repeat(innerWidth);
  return `${left}${body}${right}`;
}

function padPlainText(value: string, width: number): string {
  const clipped = truncatePlainText(value, width);
  return `${clipped}${" ".repeat(Math.max(0, width - visibleWidth(clipped)))}`;
}

function truncatePlainText(value: string, width: number): string {
  if (visibleWidth(value) <= width) return value;
  let result = "";
  for (const character of value) {
    const candidate = `${result}${character}`;
    if (visibleWidth(candidate) > width) break;
    result = candidate;
  }
  return result;
}

function colorLine(theme: Theme, line: string): string {
  if (line.startsWith("╭") || line.startsWith("╰")) return theme.bold(theme.fg("accent", line));
  if (!line.startsWith("│") || !line.endsWith("│")) return theme.fg("muted", line);

  const content = line.slice(1, -1);
  const painted = colorContent(theme, content);
  return `${theme.fg("accent", "│")}${painted}${theme.fg("accent", "│")}`;
}

function colorContent(theme: Theme, content: string): string {
  const trimmed = content.trim();
  const paintedLogo = colorLogoContent(theme, content);
  if (paintedLogo) return paintedLogo;
  if (trimmed === TS_PACKAGE_PROFILE.title) return theme.bold(theme.fg("text", content));
  if (content.trimEnd() === TS_PACKAGE_PROFILE.description) return theme.fg("muted", content);

  const row = content.match(/^([A-Za-z]+)(\s{2,})(.*)$/);
  if (row) {
    return `${theme.bold(theme.fg("accent", row[1]))}${row[2]}${theme.fg("text", row[3])}`;
  }
  return theme.fg(content.startsWith(" ") ? "dim" : "muted", content);
}

function colorLogoContent(theme: Theme, content: string): string | undefined {
  const logo = paintLogoLines(theme, content, TSPI_LOGO_LINES, TSPI_LOGO_MASK);
  if (logo) return logo;
  if (content.includes(TSPI_COMPACT_LOGO)) {
    const painted = `${theme.fg("mdLink", "TS")}${theme.bold(theme.fg("text", "π"))}`;
    return replacePlainSegment(content, TSPI_COMPACT_LOGO, painted);
  }
  return undefined;
}

function paintLogoLines(
  theme: Theme,
  content: string,
  lines: readonly string[],
  masks: readonly string[],
): string | undefined {
  for (let index = 0; index < lines.length; index++) {
    const line = lines[index];
    if (content.includes(line)) {
      return replacePlainSegment(content, line, paintPixelMask(theme, masks[index]));
    }
  }
  return undefined;
}

function paintPixelMask(theme: Theme, mask: string): string {
  return [...mask].map((cell) => {
    if (cell === " ") return EMPTY_PIXEL;
    if (cell === "P") return theme.bold(theme.fg("text", PIXEL));
    return theme.fg("mdLink", PIXEL);
  }).join("");
}

function replacePlainSegment(content: string, segment: string, painted: string): string | undefined {
  const offset = content.indexOf(segment);
  if (offset < 0) return undefined;
  return `${content.slice(0, offset)}${painted}${content.slice(offset + segment.length)}`;
}
