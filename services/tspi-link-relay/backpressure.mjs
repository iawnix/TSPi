import { LINK_HIGH_WATER_BYTES, LINK_LOW_WATER_BYTES, MAX_BUFFERED_BYTES } from "./protocol.mjs";

const pauseStates = new WeakMap();

export function holdSocket(socket, owner) {
  if (!socket || (typeof socket !== "object" && typeof socket !== "function")) return;
  let state = pauseStates.get(socket);
  if (!state) {
    state = { owners: new Set() };
    pauseStates.set(socket, state);
  }
  const alreadyHeld = state.owners.has(owner);
  state.owners.add(owner);
  if (alreadyHeld || state.owners.size !== 1) return;
  transportFor(socket)?.pause?.();
}

export function releaseSocket(socket, owner) {
  const state = pauseStates.get(socket);
  if (!state) return;
  state.owners.delete(owner);
  if (state.owners.size !== 0) return;
  pauseStates.delete(socket);
  transportFor(socket)?.resume?.();
}

/**
 * Forward WebSocket data without allowing a slow target to grow memory
 * without bound. The source is paused while the target drains.
 */
export function createWebSocketForwarder({
  source,
  target,
  encode = (value) => value,
  send,
  maxBufferedBytes = LINK_HIGH_WATER_BYTES,
  lowWaterBytes = LINK_LOW_WATER_BYTES,
  maxQueueBytes = MAX_BUFFERED_BYTES,
  onOverflow = () => {},
}) {
  const pauseOwner = {};
  const queue = [];
  let queuedBytes = 0;
  let timer;
  let closed = false;

  const targetOpen = () => target.readyState === target.OPEN;
  const targetBuffered = () => Number(target.bufferedAmount) || 0;

  const schedule = () => {
    if (timer || closed) return;
    timer = setTimeout(() => {
      timer = undefined;
      flush();
    }, 25);
    timer.unref?.();
  };

  const stop = () => {
    if (closed) return;
    closed = true;
    if (timer) clearTimeout(timer);
    timer = undefined;
    queue.length = 0;
    queuedBytes = 0;
    releaseSocket(source, pauseOwner);
  };

  const overflow = () => {
    stop();
    onOverflow();
  };

  const flush = () => {
    if (closed) return;
    if (!targetOpen()) {
      stop();
      return;
    }
    if (targetBuffered() > lowWaterBytes) {
      holdSocket(source, pauseOwner);
      schedule();
      return;
    }
    try {
      while (queue.length > 0 && targetBuffered() < maxBufferedBytes) {
        const value = queue.shift();
        queuedBytes -= value.byteLength;
        send(value);
      }
    } catch {
      overflow();
      return;
    }
    if (queue.length > 0 || targetBuffered() > lowWaterBytes) {
      holdSocket(source, pauseOwner);
      schedule();
    } else {
      releaseSocket(source, pauseOwner);
    }
  };

  const enqueue = (value) => {
    if (closed || !targetOpen()) return false;
    let encoded;
    try {
      encoded = encode(value);
    } catch {
      overflow();
      return false;
    }
    if (queue.length > 0 || targetBuffered() >= maxBufferedBytes) {
      if (queuedBytes + encoded.byteLength > maxQueueBytes) {
        overflow();
        return false;
      }
      queue.push(encoded);
      queuedBytes += encoded.byteLength;
      holdSocket(source, pauseOwner);
      schedule();
      return false;
    }
    try {
      send(encoded);
    } catch {
      overflow();
      return false;
    }
    if (targetBuffered() >= maxBufferedBytes) {
      holdSocket(source, pauseOwner);
      schedule();
    }
    return true;
  };

  return { enqueue, flush, stop };
}

function transportFor(socket) {
  return socket?._socket ?? socket;
}
