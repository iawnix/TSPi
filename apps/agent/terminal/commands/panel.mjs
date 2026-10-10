import { stripVTControlCharacters } from 'node:util';

/** Command-only palette: never changes transcript or tool message colors. */
export function createPanelPainter({ truncateToWidth, visibleWidth, monochrome = process.env.TERM === 'dumb' || 'NO_COLOR' in process.env }) {
  return (text, width, selected = false) => {
    const size = Math.max(1, width);
    const fitted = truncateToWidth(text, size);
    const padded = fitted + ' '.repeat(Math.max(0, size - visibleWidth(fitted)));
    if (monochrome) return stripVTControlCharacters(padded);
    const colors = selected ? '\x1b[48;2;122;162;247m\x1b[38;2;23;27;36m' : '\x1b[48;2;32;40;50m\x1b[38;2;200;211;220m';
    return colors + padded.replaceAll('\x1b[0m', '\x1b[0m' + colors) + '\x1b[0m';
  };
}

export function createCommandPresentation(options) {
  const { matchesKey, rows = () => process.stdout.rows || 24, scope = 'Session' } = options;
  const paint = createPanelPainter(options);
  return {
    selection({ command, title, items, selectedValue, onSelect, onCancel }) {
      let index = Math.max(0, items.findIndex(item => item.value === selectedValue));
      let size = 1;
      let viewport;
      return {
        setViewport(height) { viewport = height; },
        invalidate() {},
        render(width) {
          const height = viewport ?? Math.min(15, rows() - 5);
          const descriptions = height >= 5;
          size = Math.max(1, Math.min(6, Math.floor((height - 3) / (descriptions ? 2 : 1))));
          const start = Math.max(0, Math.min(index - Math.floor(size / 2), items.length - size));
          const body = items.slice(start, start + size).flatMap((item, i) => {
            const focused = start + i === index;
            return [paint(` ${focused ? '›' : ' '} ${item.value === selectedValue ? '[current] ' : ''}${item.label}`, width, focused),
              ...(descriptions ? [paint(`    ${item.description || item.value}`, width, focused)] : [])];
          });
          return [paint(` /${command} · ${title}`, width), paint(` ── Select · ${command === 'resume' ? 'Workspace' : scope} · ${items.length ? index + 1 : 0}/${items.length}`, width),
            ...(body.length ? body : [paint(' No options available', width)]),
            paint(width < 45 ? ' Esc Back · ↑↓ · Enter Apply' : ' Esc Cancel · ↑↓ Move · Enter Apply · PgUp/PgDn Page', width)];
        },
        handleInput(data) {
          if (matchesKey(data, 'escape')) { onCancel(); return; }
          if (matchesKey(data, 'enter')) { if (items[index]) onSelect(items[index].value); return; }
          if (matchesKey(data, 'up')) index--;
          else if (matchesKey(data, 'down')) index++;
          else if (matchesKey(data, 'pageUp')) index -= size;
          else if (matchesKey(data, 'pageDown')) index += size;
          else if (matchesKey(data, 'home')) index = 0;
          else if (matchesKey(data, 'end')) index = items.length - 1;
          index = Math.max(0, Math.min(index, items.length - 1));
        },
      };
    },
    feedback({ command, message, kind }) {
      const label = { running: '… Running', success: '✓ Done', error: '! Error', info: 'i Info' }[kind];
      return {
        invalidate() {},
        render(width) {
          // Executing a command is a status update, not an interactive panel.
          const text = ` /${command} · ${label} · ${message.replace(/\s+/g, ' ')}`;
          return [stripVTControlCharacters(options.truncateToWidth(text, Math.max(1, width)))];
        },
      };
    },
  };
}
