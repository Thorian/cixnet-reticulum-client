# Validation — 19 November 2026

## Automated checks

- 80 Python tests passed, including independent receiver processes over loopback TCP, restart persistence, attachments, offline propagation, browser requests, DNS resolution, phone pairing and access revocation.
- 39 frontend tests passed, including rendering, hostile text, camera cleanup, location, service filters, LXMF links, duplicate-action handling and preservation of a new draft after a late send response.
- Ruff lint and formatting passed for 72 Python files. First-party frontend formatting and bundle compilation passed.
- The Android APK built successfully with the existing signing key. Windows packaging completed with RNS 1.6.0, LXMF 1.3.0, retdns 0.2.1 and NomadPL 0.3.0. Native builds now reject stale dependency versions. The Windows package passed a fresh-profile startup check, and the APK signature matches the existing debug certificate.
- An OSV query of the 23 packages installed in the Windows build environment returned no known advisories after updating its pip build tool. This check covers package versions, not bundled operating-system runtimes or every upstream code path.

## Live service checks

The public gateway at `gw.cixnet.org:4242` accepts clients and has five working public uplinks. HTTPS setup instructions are available at https://gw.cixnet.org/.

The propagation node stored a message while its recipient was offline and delivered it on retrieval with a valid signature. Destination: `49ec09143c134d6bb5d8b522c4cefa37`.

The retdns service announced as **ciXnet DNS** at `48a1ab73497b08453287f12630883de6`. Forward and reverse lookups passed through the gateway. A fresh client resolved `relay.cix` using its default authority. The browser preview also added `.cix` directly from the received DNS announce.

Browse filters were checked in the preview and retained their state after refresh. An LXMF URI switched Browse to the matching conversation. NomadPL page navigation displayed and cleared its loading indicator.

## Field testing still needed

Independent users running other LXMF clients should test direct and propagated messages, attachments, stamp requirements and receipt behaviour. The automated two-client tests do not establish interoperability with every release of Sideband or NomadNet.

Long idle reception, notification behaviour and battery endurance need more physical Android testing. Android fingerprint unlocking is unfinished. Linux instructions are available, but its packaged GUI has not been verified. This preview is intended for public testing through GitHub.
