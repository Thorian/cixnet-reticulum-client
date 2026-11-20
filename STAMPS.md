# Stamps

The client now uses Reticulum 1.6.1 and LXMF 1.3.1. Reticulum generates network stamps by default, including destination announces and path requests. These are separate from LXMF message stamps.

Production keeps Reticulum’s stamp difficulty defaults. First use of a new destination can require substantial CPU work; Reticulum caches its completed destination stamp for reuse. Client configuration limits stamp workers to one. Android uses Reticulum’s portable worker because its embedded Python runtime cannot fork processes.

Messages that arrive before the sender’s public key are retained locally and verified when that key becomes available. They are not displayed and do not produce notifications until verified. This pending buffer is bounded to 100 messages / 64 MiB, with a seven-day expiry.

The following notes record the earlier source review.

# Stamp-system review

Reviewed the user-supplied Reticulum 1.6.0 and LXMF 1.3.0 sources on 2026-11-12. This is a source review, not an end-to-end test against an external stamp-enforcing node.

## Two distinct layers

LXMF message stamps are computational proof of work used to make unsolicited messaging expensive. They are not payment tokens and do not require a wallet, subscription, stamp vendor, or monetary fee. A recipient advertises a required work cost. LXMF also supports tickets that can exempt correspondents from doing that work again.

Reticulum 1.6.0 additionally implements network-level stamps for destination announces, path requests, and link requests. Those settings are separate from LXMF message stamps. Configuring one does not configure the other.

## Current client behavior

The client delegates outbound messaging to LXMRouter.handle_outbound. In this LXMF version, LXMessage defaults to deferred stamping. The router reads the last advertised recipient cost, handles available tickets, and queues deferred stamp generation. Our client does not replace or disable that mechanism.

Our registered delivery identities currently have no inbound stamp cost, and the router uses the upstream default of no inbound stamp enforcement. That means we do not currently demand proof of work from people sending to us.

The Reticulum source defaults to stamping link requests when a destination requires it; destination and path-request stamping are off by default. Global stamp enforcement is also off. Our generated private config preserves those defaults. Therefore this review does not establish interoperability with a network that requires stamps on announces or path requests.

Relevant source entry points: LXMF/LXMessage.py (__init__, get_stamp), LXMF/LXMRouter.py (handle_outbound, set_inbound_stamp_cost, enforce_stamps, lxmf_delivery, process_deferred_stamps); RNS/Transport.py (STAMP_* defaults); RNS/Reticulum.py ([stamps] configuration); RNS/Destination.py (_await_stamp, announce).

## What to implement before public service launch

1. Show when outbound work is being prepared and why delivery may take longer. Add cancellation and a user-controlled ceiling for unexpectedly expensive requests.
2. Provide optional per-identity/service inbound stamp cost and enforcement together, with zero/no requirement as the compatibility-friendly default. Test signed unstamped, valid stamped, invalid stamped, and ticket-assisted traffic against independent clients.
3. Expose network-level stamp generation separately from strict enforcement. Test the required network modes before enabling generation or enforcement broadly.
4. Choose service-specific policies for public mail/group bots rather than treating stamps as a universal solution to moderation or abuse.
5. Test propagation-node costs separately when offline/propagated delivery is implemented.

No stamp settings were silently enabled by this change, and no existing identity or message history was altered.
