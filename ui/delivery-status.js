/** Delivery proof means reception by the client, never that a person read it. */
export function deliveryStatus(status) {
  return (
    {
      queued: {
        mark: "◷",
        tone: "pending",
        label: "Queued — waiting for a route",
      },
      sending: { mark: "↑", tone: "pending", label: "Sending" },
      stored_on_relays: {
        mark: "✓",
        tone: "relay",
        label: "Stored on relays; awaiting recipient",
      },
      delivered: {
        mark: "✓✓",
        tone: "delivered",
        label: "Received by recipient client",
      },
      cancelled: { mark: "⊘", tone: "pending", label: "Retries stopped" },
      interrupted: {
        mark: "!",
        tone: "relay",
        label: "Interrupted legacy message",
      },
      failed: { mark: "!", tone: "failed", label: "Delivery failed" },
    }[status] || { mark: "", tone: "pending", label: status || "" }
  );
}
