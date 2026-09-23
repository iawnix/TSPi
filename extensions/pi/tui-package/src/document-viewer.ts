import type { KeybindingsManager, Theme } from "@earendil-works/pi-coding-agent";
import { Key, matchesKey, truncateToWidth, wrapTextWithAnsi, type Component, type TUI } from "@earendil-works/pi-tui";

const OVERLAY_HEIGHT_RATIO = 0.88;

export function overlayLineBudget(tui: TUI): number {
  const rows = Number.isFinite(tui.terminal.rows) ? Math.floor(tui.terminal.rows) : 1;
  // Pi resolves percentage maxHeight against the full terminal, then clamps
  // it to the one-row margin on each side used by these overlays.
  return Math.max(1, Math.min(Math.max(1, rows - 2), Math.floor(rows * OVERLAY_HEIGHT_RATIO)));
}

export class WrappedDocumentViewer implements Component {
  private readonly title: string;
  private readonly content: string;
  private readonly tui: TUI;
  private readonly theme: Theme;
  private readonly keybindings: KeybindingsManager;
  private readonly done: () => void;
  private offset = 0;
  private bodyHeight = 1;
  private wrappedLines: string[] = [""];

  constructor(
    title: string,
    content: string,
    tui: TUI,
    theme: Theme,
    keybindings: KeybindingsManager,
    done: () => void,
  ) {
    this.title = title;
    this.content = content;
    this.tui = tui;
    this.theme = theme;
    this.keybindings = keybindings;
    this.done = done;
  }

  render(width: number): string[] {
    const safeWidth = Math.max(16, Math.floor(width));
    const lineBudget = overlayLineBudget(this.tui);
    if (lineBudget === 1) return [this.theme.fg("accent", truncateToWidth(this.title, safeWidth, ""))];

    this.bodyHeight = Math.max(1, lineBudget - 2);
    this.wrappedLines = wrapTextWithAnsi(this.content, safeWidth);
    this.clampOffset();

    const start = this.offset;
    const end = Math.min(this.wrappedLines.length, start + this.bodyHeight);
    const page = Math.floor(start / this.bodyHeight) + 1;
    const pages = Math.max(1, Math.ceil(this.wrappedLines.length / this.bodyHeight));
    const lines = [this.theme.fg("accent", truncateToWidth(this.title, safeWidth, ""))];
    for (let index = start; index < end; index += 1) {
      lines.push(this.theme.fg("text", truncateToWidth(this.wrappedLines[index] || "", safeWidth, "")));
    }
    while (lines.length < lineBudget - 1) lines.push("");
    lines.push(this.theme.fg(
      "dim",
      truncateToWidth(
        `Page ${page}/${pages} · Lines ${start + 1}-${Math.max(start + 1, end)}/${this.wrappedLines.length} · ↑/↓ scroll · PgUp/PgDn page · Home/End · Esc close`,
        safeWidth,
        "",
      ),
    ));
    return lines;
  }

  invalidate(): void {}

  handleInput(data: string): void {
    let next = this.offset;
    if (this.keybindings.matches(data, "tui.select.up")) next -= 1;
    else if (this.keybindings.matches(data, "tui.select.down")) next += 1;
    else if (this.keybindings.matches(data, "tui.select.pageUp")) next -= this.bodyHeight;
    else if (this.keybindings.matches(data, "tui.select.pageDown")) next += this.bodyHeight;
    else if (matchesKey(data, Key.home)) next = 0;
    else if (matchesKey(data, Key.end)) next = this.maxOffset();
    else if (this.keybindings.matches(data, "tui.select.cancel")) {
      this.done();
      return;
    } else return;

    this.offset = Math.max(0, Math.min(this.maxOffset(), next));
    this.tui.requestRender();
  }

  private maxOffset(): number {
    return Math.max(0, this.wrappedLines.length - this.bodyHeight);
  }

  private clampOffset(): void {
    this.offset = Math.max(0, Math.min(this.maxOffset(), this.offset));
  }
}
