/** A presentation-owned event connection; snapshots recover events missed during reconnect. */
export function subscribeMonitor({ connect, workspaceId, onChange, onError, retryMs = 5000 }) {
  let stopped = false, peer, timer;
  async function open() {
    try {
      const connection = await connect();
      if (stopped) { connection.close(); return; }
      peer = connection;
      connection.on('notification', event => {
        if (!stopped && event.method === 'monitor/event' && event.params.workspace_id === workspaceId) onChange();
      });
      connection.on('close', () => {
        if (peer !== connection || stopped) return;
        peer = undefined; onError(); timer = setTimeout(open,retryMs); timer.unref?.();
      });
      await connection.request('monitor/status',{workspace_id:workspaceId});
      if (!stopped) onChange();
    } catch {
      if (stopped) return;
      const previous = peer; peer = undefined; previous?.close();
      onError(); clearTimeout(timer); timer = setTimeout(open,retryMs); timer.unref?.();
    }
  }
  void open();
  return () => { stopped = true; clearTimeout(timer); peer?.close(); peer = undefined; };
}
