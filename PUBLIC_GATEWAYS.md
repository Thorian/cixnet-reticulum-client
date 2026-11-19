# Public gateway shortlist

Checked 16 November 2026. These are candidates for an optional, disabled-by-default
gateway picker, not automatically enabled interfaces. No running client settings
were changed. ciXnet's own gateway remains the intended default fallback.

Reticulum's [current connection page](https://reticulum.network/connect.html)
points to community directories and recommends local infrastructure plus bootstrap
connections. Historical testnet examples should not be copied into release presets.

| Operator | Host | TCP port | Evidence |
| --- | --- | --- | --- |
| MichMesh | rns.michmesh.net | 7822 | [Operator instructions](https://michmesh.com/docs/Reticulum/Getting_Started/) explicitly offer a public TCP hub and instructions for multiple clients. |
| dismail | rns.dismail.de | 7822 | [Operator service page](https://dismail.de/info.html) publishes the Reticulum TCP endpoint; [homepage](https://dismail.de/) identifies the operator's services and maintenance notices. Some upstream-peer names on the service page are historical. |
| RMAP | rmap.world | 4242 | [Operator services](https://rmap.world/services.html) publishes the public backbone and TCPClientInterface configuration. |

RMAP also publishes port **4343**, on the same server. Offer it as an alternative
port, not independent redundancy. Its propagation mailbox is currently marked
offline on the operator page; do not add that mailbox as an operational preset.

## What was checked

- Current operator-published endpoint and an explicit public connection offer.
- One successful TCP connection to each listed endpoint, including RMAP 4343.
- No message, identity announce, registration or operator contact was sent by
  these checks. DNS lookup and TCP handshakes expose the usual connection metadata.

This is an initial shortlist, not an uptime ranking, security audit or proof of
Reticulum routing. A TCP handshake alone cannot establish any of those. Before
shipping presets, test actual Reticulum path establishment and message delivery,
observe reconnect behaviour over time, and confirm operators welcome inclusion
in a distributed client. Public access is not evidence of unlimited capacity.
No operator has yet been contacted on ciXnet's behalf.

## Suggested app behaviour

- Keep all third-party entries disabled until the user chooses one.
- Show operator, source link, endpoint and last review date.
- Say “Community gateway”; do not label them “verified” or promise availability.
- Start with one selected connection; avoid enabling the entire list together.
- Preserve user edits. Do not silently activate a replacement endpoint.
- Configure LXMF propagation mailboxes separately from TCP gateway connections.
- Keep a manual TCP interface option if a preset becomes stale.

## Excluded from the initial shortlist

Old Amsterdam/Dublin testnet addresses and mirrored testnet pages do not provide
current deployment evidence. BetweenTheBorders appeared in historical material,
but the operator-hosted page found during this review is a dated mirror, so it
was not promoted into this shortlist. Other directory-only entries were excluded
where current operator instructions could not be established in this review.
Exclusion does not imply that those operators are unsafe or offline.
