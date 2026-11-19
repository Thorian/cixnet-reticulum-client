/** Recent announce ages use receipt time, never the remote station's clock. */
export function announceTime(received, now = Date.now() / 1000) {
  const seconds = Math.max(0, Math.floor(now - received));
  return seconds < 300
    ? `${seconds}s ago`
    : new Date(received * 1000).toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
      });
}
