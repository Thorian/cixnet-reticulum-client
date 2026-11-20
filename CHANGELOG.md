# Changelog

## 0.1.2 — 20 November 2026

- Update retdns to 0.3.0 and require signed destination announces in DNS replies.
- Restore verified destination keys and metadata from network lookups and saved DNS cache entries.
- Upgrade existing DNS caches in place, retaining configured authorities and suffixes.
- Speed up Android link-request stamps with native OpenSSL X25519 public-key generation, retaining Reticulum's standard difficulty and verification.

Custom DNS servers must support signed-announce replies. Older address-only authorities need upgrading. The default ciXnet authority has been upgraded.

## 0.1.1 — 19 November 2026

- Fix fallback socket startup after the Reticulum upgrade, preventing corrupted or stalled page transfers.
- Retry NomadPL route discovery if a page opens before the gateway connects.
- Update Reticulum to 1.6.1 and LXMF to 1.3.1.
- Retain messages from unknown senders until their public keys arrive and signatures can be checked.
- Remember identity disclosure across pages on the same node.
- Use a 45-minute client announce interval by default; preserve saved settings.
- Probe Windows Hello availability in the background so state polling stays responsive.

## 0.1.0-preview — 19 November 2026

Initial client preview for Windows and Android:

- Persistent LXMF conversations, search, contact blocking and identity management.
- File/image transfer, image reduction and photo capture.
- Multiple propagation mailboxes with durable retries and recipient receipts.
- Micron and NomadPL browsing, name resolution, bookmarks and browser bridge.
- Encrypted desktop-to-phone pairing with existing phone history.
- Configurable automatic gateway fallback.
- Offline radio-station learning, compiled directory imports and one-shot station location.

The public gateway, LXMF propagation mailbox and retdns service are deployed. Station-directory distribution is still pending.

Recent changes include alphabetical Browse lists with saved service filters, transport announce labels, LXMF link handling, DNS setup from announces and progress feedback for long requests.
