/** Interface observations describe a link, not proof of a transport server. */
export function connectionCounts(network) {
  const lan = network.interfaces
    .filter((item) => item.type === "AutoInterface")
    .reduce((sum, item) => sum + item.peers, 0);
  const tcp = network.interfaces.filter(
    (item) => item.type === "TCPClientInterface" && item.online,
  ).length;
  return { lan, tcp, total: lan + tcp };
}

/** Describe actual connectivity without treating a listening socket as a peer. */
export function connectionStatus(network) {
  if (network.phase !== "running") {
    return {
      connected: false,
      label:
        network.phase === "starting"
          ? "Starting Reticulum…"
          : "Reticulum unavailable",
    };
  }
  if (network.gateway?.serverAvailable)
    return { connected: true, label: "Relay / transport server available" };
  if (network.gateway?.connected)
    return { connected: true, label: "Fallback gateway link active" };
  const links = network.interfaces.filter(
    (item) => item.type === "TCPClientInterface" && item.online,
  );
  if (links.some((item) => item.name.includes("Local test"))) {
    return { connected: true, label: "Local test link active" };
  }
  if (links.length)
    return { connected: true, label: "TCP link active · server unverified" };
  const peers = network.interfaces
    .filter((item) => item.type === "AutoInterface")
    .reduce((sum, item) => sum + item.peers, 0);
  return {
    connected: peers > 0,
    label:
      peers > 0
        ? "LAN peers found · server unverified"
        : "No network peers found",
  };
}
