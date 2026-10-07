/** A bounded document surface with resize-aware pages and normal-weight body text. */
export function createDocumentView({ title, body, wrapText, truncateToWidth, theme, matchesKey = () => false, rows = () => process.stdout.rows || 24 }) {
  let offset = 0, pageSize = 1, lastWidth = 0, lastHeight = 0, lines = [];
  const source = body.split('\n'); let anchor = { line: 0, part: 0 }; let positions = [];
  function layout(width) {
    const height = Math.max(1, rows() - 9);
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
      const fit = value => truncateToWidth(value,Math.max(1,width-2));
      const page = Math.floor(offset/pageSize)+1; const pages = Math.max(1,Math.ceil(lines.length/pageSize));
      return [` ${theme.bold(fit(`${title}  ${page}/${pages}`))}`, '',
        ...lines.slice(offset,offset+pageSize).map(line=>` ${line}`), '',
        ` ${theme.fg('muted',fit('← Previous · → Next · Esc Close'))}`];
    },
    handleInput(data) {
      if ((['\x1b[C','\x1b[6~',' '].includes(data) || matchesKey(data,'right') || matchesKey(data,'pageDown')) && offset+pageSize < lines.length) offset += pageSize;
      else if ((['\x1b[D','\x1b[5~'].includes(data) || matchesKey(data,'left') || matchesKey(data,'pageUp'))) offset = Math.max(0,offset-pageSize);
      else if (data === '\x1b[H') offset = 0;
      else if (data === '\x1b[F') offset = Math.max(0,lines.length-pageSize);
    },
  };
}
