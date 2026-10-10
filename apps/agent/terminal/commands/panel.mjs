import { stripVTControlCharacters } from 'node:util';

/** Command-only palette: never changes transcript or tool message colors. */
export function createPanelPainter({ theme, truncateToWidth, visibleWidth, monochrome = process.env.TERM === 'dumb' || 'NO_COLOR' in process.env }) {
  return (text, width, selected = false, role = 'text') => {
    const size = Math.max(1, width);
    const fitted = truncateToWidth(text, size);
    const padded = fitted + ' '.repeat(Math.max(0, size - visibleWidth(fitted)));
    const current = typeof theme === 'function' ? theme() : theme;
    if (monochrome || !current) return stripVTControlCharacters(padded);
    return current.style(padded, { fg: selected ? 'text' : role, ...(selected ? { bg: 'selectedBg' } : {}) });
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
      let start = 0, itemHeight = 1, headerHeight = 1, pressed;
      return {
        setViewport(height) { viewport = height; },
        invalidate() {},
        render(width) {
          const height = viewport ?? Math.min(15, rows() - 5);
          const descriptions = width >= 45 && height >= 8;
          itemHeight = descriptions ? 2 : 1;
          headerHeight = height >= 7 ? 2 : 1;
          size = Math.max(1, Math.min(6, Math.floor((height - headerHeight - 1) / itemHeight)));
          start = Math.max(0, Math.min(index - Math.floor(size / 2), items.length - size));
          const body = items.slice(start, start + size).flatMap((item, i) => {
            const focused = start + i === index;
            return [paint(` ${focused ? '›' : ' '} ${item.value === selectedValue ? '[current] ' : ''}${item.label}`, width, focused),
              ...(descriptions ? [paint(`    ${item.description || item.value}`, width, focused, 'muted')] : [])];
          });
          return [paint(` /${command} · ${title}`, width), ...(headerHeight === 2 ? [paint(` ${command === 'resume' ? 'Workspace' : scope} · ${items.length ? index + 1 : 0}/${items.length}`, width, false, 'muted')] : []),
            ...(body.length ? body : [paint(' No options available', width)]),
            paint(width < 45 ? ' Esc Back · ↑↓ · Enter' : ' Esc Back · ↑↓ Move · Enter Apply · PgUp/PgDn Page', width, false, 'muted')];
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
        handleMouse(event) {
          if (event.type === 'wheel' && event.wheelDelta) {
            index = Math.max(0, Math.min(items.length - 1, index + Math.sign(event.wheelDelta)));
            pressed = undefined;
            return { handled: true, render: true };
          }
          if (event.button !== 'left' || !['press', 'click'].includes(event.type)) return;
          const row = Math.floor((event.y - headerHeight) / itemHeight);
          if (row < 0 || row >= Math.min(size, items.length - start)) { pressed = undefined; return; }
          if (event.type === 'press') {
            pressed = start + row;
            index = pressed;
            return { handled: true, render: true };
          }
          // Rendering can recenter the viewport between press and release.
          const target = pressed ?? start + row;
          pressed = undefined;
          if (items[target]) onSelect(items[target].value);
          return { handled: true, render: true };
        },
      };
    },
    feedback({ command, message, kind }) {
      const label = { running: '… Running', success: '✓ Done', error: '! Error', info: 'i Info' }[kind];
      return {
        invalidate() {},
        render(width) {
          // Executing a command is a status update, not an interactive panel.
          const hint = kind === 'error' ? ' · F2 Details' : '';
          const text = ` /${command} · ${label} · ${message.split('\n')[0]}`;
          const body = options.truncateToWidth(text, Math.max(1, width - hint.length));
          return [paint(body + hint, width, false, kind === 'error' ? 'error' : kind === 'success' ? 'success' : 'muted')];
        },
        ...(kind === 'error' && options.createDocument ? { details: () => options.createDocument({
          command, title: 'Command error', body: message, mode: 'auto', scope,
        }) } : {}),
      };
    },
  };
}
