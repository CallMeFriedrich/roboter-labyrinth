// Reconnecting WebSocket with JSON messages.

export function connect(path, { onMessage, onOpen, onClose }) {
  let socket = null;
  let closedByUs = false;
  let retry = 0;

  function open() {
    const scheme = location.protocol === "https:" ? "wss" : "ws";
    socket = new WebSocket(`${scheme}://${location.host}${path}`);
    socket.addEventListener("open", () => {
      retry = 0;
      onOpen?.();
    });
    socket.addEventListener("message", (event) => {
      let data;
      try { data = JSON.parse(event.data); } catch { return; }
      onMessage?.(data);
    });
    socket.addEventListener("close", (event) => {
      onClose?.(event);
      if (closedByUs || event.code === 4401) return;   // 4401: not logged in
      retry = Math.min(retry + 1, 5);
      setTimeout(open, 300 * retry);
    });
    socket.addEventListener("error", () => socket.close());
  }
  open();

  return {
    send(message) {
      if (socket && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify(message));
        return true;
      }
      return false;
    },
    get open() { return socket !== null && socket.readyState === WebSocket.OPEN; },
    close() { closedByUs = true; socket?.close(); },
    reopen() { closedByUs = false; socket?.close(); open(); },
  };
}
