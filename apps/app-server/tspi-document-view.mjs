import { createPanelPainter } from './tspi-command-panel.mjs';

/** A bounded command document; logical anchors survive width and height changes. */
export function createDocumentView({ title, command, scope = 'Session', body, wrapText, truncateToWidth, visibleWidth, monochrome, matchesKey = () => false, rows = () => process.stdout.rows || 24 }) {
  const paint = createPanelPainter({ truncateToWidth, visibleWidth, monochrome });
  let offset = 0, pageSize = 1, lastWidth = 0, lastHeight = 0, lines = [];
  const source = body.split('\n'); let anchor = { line: 0, part: 0 }; let positions = [];
  function layout(width) {
    const height = Math.max(1, rows() - 10);
    if (lastWidth === width && lastHeight === height) return;
    if (positions[offset]) anchor = positions[offset];
    lastWidth = width; lastHeight = height; pageSize = height;
    lines = []; positions = [];
    source.forEach((line, index) => {
      const wrapped = wrapText(line, Math.max(1,width-2));
      for (let part=0;part<wrapped.length;part++) { lines.push(wrapped[part]); positions.push({line:index,part}); }
    });
    offset = Math.max(0, positions.findIndex(p => p.line === anchor.line && p.part >= anchor.part));
    offset = Math.min(offset,Math.max(0,lines.length-1));
  }
  return {
    invalidate() { lastWidth = 0; },
    render(width) {
      layout(width);
      return [paint(` /${command} · ${title}`, width),
        paint(` ── Read only · ${scope} · ${offset+1}–${Math.min(lines.length,offset+pageSize)}/${lines.length}`, width),
        ...lines.slice(offset,offset+pageSize).map(line=>paint(` ${line}`, width)),
        paint(width < 55 ? ' Esc Back · ↑↓ Scroll · ←→ Page' : ' Esc Back · ↑↓ Scroll · ←→/PgUp/PgDn Page · Home/End', width)];
    },
    handleInput(data) {
      if ((['\x1b[C','\x1b[6~',' '].includes(data) || matchesKey(data,'right') || matchesKey(data,'pageDown')) && offset+pageSize < lines.length) offset += pageSize;
      else if ((['\x1b[D','\x1b[5~'].includes(data) || matchesKey(data,'left') || matchesKey(data,'pageUp'))) offset = Math.max(0,offset-pageSize);
      else if (data === '\x1b[A' || matchesKey(data,'up')) offset = Math.max(0,offset-1);
      else if (data === '\x1b[B' || matchesKey(data,'down')) offset = Math.min(Math.max(0,lines.length-1),offset+1);
      else if (data === '\x1b[H' || matchesKey(data,'home')) offset = 0;
      else if (data === '\x1b[F' || matchesKey(data,'end')) offset = Math.max(0,lines.length-pageSize);
    },
  };
}
