# Client source review — 19 November 2026

Reviewed first-party Python, frontend JavaScript, Android receiver/WebView integration, native build inputs, and repository contents. Vendor code and generated bundles were checked at their integration boundaries.

## Fixed

- A completed send could erase a new draft after leaving and reopening the same conversation. Send completion now checks the original composer as well as identity and recipient.
- Closing a NomadPL session revoked requests but left its underlying transport open. Closure now releases the transport once, without blocking identity locking while a request finishes.
- The Windows build environment contained retdns 0.2.0 and NomadPL 0.2.0. Updated it to the pinned retdns 0.2.1 and NomadPL 0.3.0. Native builds now reject stale runtime dependency versions before packaging.
- First launch logged an expected missing pairing key as an error, and a damaged saved key could be overwritten. A new key is now created only when absent; damaged saved keys are preserved and reported.
- Added ignore rules for SQLite3 databases, identity-lock metadata and Android receiver credentials.
- Removed redundant callback comments and corrected outdated deployment and security notes.

## Boundaries checked

SQL values use parameters. Identity and attachment access checks bind requests to an existing owner. Export resolves a saved profile before opening a key file. Attachment names are display metadata, not filesystem paths. Private runtime data is excluded from the source export.

The local API checks Host, Origin, request framing and a mutation token. Android also requires a private bearer credential. Static files are constrained to the UI directory; directory listings are disabled. Reticulum/LXMF data and remote names are rendered as text or escaped markup.

NomadPL pages use separate loopback origins and sandboxed frames. The Android camera and location permission handlers reject remote page origins. Pairing uses authenticated Reticulum Links, owner-scoped access, revocation and deduplication of mutations. Private identity export is excluded from paired operations.

## Interoperability

Messages, images, files and appearance data use the existing LXMF fields. ciXnet receipt requests use optional custom metadata. Other clients can exchange ordinary messages without implementing ciXnet receipts; propagation storage does not count as recipient delivery. Testing with independent Sideband/NomadNet users is still needed.

## Remaining work

- Android fingerprint unlocking is unfinished. Windows Hello protects the interface; neither platform encrypts the stored keys or messages itself.
- Physical-device battery endurance, long idle reception and third-party client behaviour need field testing.
- Linux packaging needs native verification. Dependency advisory results and platform test notes belong in VALIDATION.md.
