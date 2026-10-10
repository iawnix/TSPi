import { createPanelPainter } from '../commands/panel.mjs';

/** A document with a fixed viewport and logical anchors across refreshes and resizing. */
export function createDocumentView({ title, command, scope = 'Session', body, mode = 'auto', wrapText, truncateToWidth, visibleWidth, monochrome, matchesKey = () => false, rows = () => process.stdout.rows || 24 }) {
  const paint = createPanelPainter({ truncateToWidth, visibleWidth, monochrome });
  let offset = 0, pageSize = 1, viewport, fullPage = false, lastWidth = 0, lastBody, lines = [], positions = [];
  function layout(width) {
    const text = typeof body === 'function' ? body() : body;
    if (lastWidth !== width || lastBody !== text) {
      const anchor = positions[offset] || { line: 0, part: 0 };
      lastWidth = width; lastBody = text;
      lines = []; positions = [];
      String(text ?? '').split('\n').forEach((line, index) => {
        const wrapped = wrapText(line, Math.max(1, width - 2));
        for (let part = 0; part < wrapped.length; part++) {
          lines.push(wrapped[part]); positions.push({ line: index, part });
        }
      });
      const next = positions.findIndex(p => p.line === anchor.line && p.part >= anchor.part);
      const lineStart = positions.findIndex(p => p.line >= anchor.line);
      offset = next >= 0 ? next : lineStart >= 0 ? lineStart : Math.max(0, lines.length - 1);
    }
  }
  const maxOffset = () => Math.max(0, lines.length - pageSize);
  return {
    mode,
    setViewport(height, page = false) { viewport = Math.max(4, height); fullPage = page; },
    preferredHeight(width) { layout(width); return lines.length + 3; },
    invalidate() { lastWidth = 0; },
    render(width) {
      layout(width);
      const height = viewport ?? Math.max(4, Math.min(15, rows() - 5));
      pageSize = Math.max(1, height - 3);
      offset = Math.min(offset, maxOffset());
      const scrollable = maxOffset() > 0;
      const content = lines.slice(offset, offset + pageSize);
      // Page height is independent of the remaining content at the scroll position.
      if (mode === 'page' || fullPage) while (content.length < pageSize) content.push('');
      const hint = scrollable
        ? width < 55 ? ' Esc Back · ↑↓ Scroll · ←→ Page' : ' Esc Back · ↑↓ Scroll · ←→/PgUp/PgDn Page · Home/End'
        : ' Esc Back';
      return [paint(` /${command} · ${title}`, width),
        paint(` ── ${scope}${scrollable ? ` · ${offset + 1}–${Math.min(lines.length, offset + pageSize)}/${lines.length}` : ''}`, width),
        ...content.map(line => paint(` ${line}`, width)), paint(hint, width)];
    },
    handleInput(data) {
      if (['\x1b[C', '\x1b[6~', ' '].includes(data) || matchesKey(data, 'right') || matchesKey(data, 'pageDown')) offset += pageSize;
      else if (['\x1b[D', '\x1b[5~'].includes(data) || matchesKey(data, 'left') || matchesKey(data, 'pageUp')) offset -= pageSize;
      else if (data === '\x1b[A' || matchesKey(data, 'up')) offset--;
      else if (data === '\x1b[B' || matchesKey(data, 'down')) offset++;
      else if (data === '\x1b[H' || matchesKey(data, 'home')) offset = 0;
      else if (data === '\x1b[F' || matchesKey(data, 'end')) offset = maxOffset();
      offset = Math.max(0, Math.min(offset, maxOffset()));
    },
  };
}
