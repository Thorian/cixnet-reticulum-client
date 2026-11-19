/** Keep one conversation row, previewing the newest text that matches the query. */
export function conversationMatches(
  messages,
  query,
  nameOf,
  draftPeer = null,
  savedMatches = [],
) {
  const term = query.trim().toLocaleLowerCase();
  const latest = new Map();
  const matches = new Map();
  for (const message of messages) {
    latest.set(message.peer, message);
    if (term && (message.content || "").toLocaleLowerCase().includes(term))
      matches.set(message.peer, message);
  }
  if (draftPeer && !latest.has(draftPeer))
    latest.set(draftPeer, {
      peer: draftPeer,
      content: "New conversation",
      timestamp: Date.now() / 1000,
    });
  if (!term)
    return [...latest.values()].sort((a, b) => b.timestamp - a.timestamp);
  for (const [peer, message] of latest) {
    if (`${peer} ${nameOf(peer)}`.toLocaleLowerCase().includes(term))
      matches.set(peer, message);
  }
  for (const message of savedMatches) matches.set(message.peer, message);
  return [...matches.values()].sort((a, b) => b.timestamp - a.timestamp);
}
