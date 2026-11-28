# Validation — 25 November 2026

## 0.1.4 release checks

- All 94 Python tests and 44 frontend tests passed; UI formatting and Python lint checks passed.
- Windows: portable build completed and passed fresh-profile startup.
- Android: version code 18, with the existing application ID and signing key.
- The download implementation passed Android 13 emulator checks for public Downloads/ciXnet storage, exact file contents, completed-file publication and native HTTP downloads. These checks ran on version code 17 before the release version bump.
- A 17 MB response passed through the NomadPL download bridge. Frontend tests cover download progress, chunk acknowledgements and failed-write cancellation.

## 0.1.3 release checks

- Discovery retains 10,000 destinations, updates existing entries, and evicts the least recently heard entry at capacity.
- The automatic Internet gateway accepts normal public-network announce traffic while retaining burst control. Tests cover ordinary traffic and flood limiting. Live discovery recovered both NomadNet and NomadPL sites after this change.
- Native browsing accepts `nomadnet://` addresses with an optional page path, while rejecting credentials, query strings and unsupported paths.
- Android uses the existing signing certificate and application ID, with version code 16. The download filename remains `ciXnet-debug.apk`.
- A fresh Android emulator run was unavailable because the configured system image is missing. Previous Android device checks are listed below; they do not establish testing of this APK.

## 0.1.2 release checks

- Updated retdns to 0.3.0. The client explicitly requires signed destination announces from configured DNS authorities.
- All 41 retdns tests passed, including the real-network test. Client regression coverage rejects address-only replies without caching them.
- The gateway retains its DNS identity and records. Both registered destinations have signed announces. Existing retdns 0.2.1 clients still resolve against the upgraded server.
- A fresh client resolved relay.cix, verified and cached its signed announce, restored keys from cache without a network lookup, and opened a real link to the resolved propagation destination. The DNS self-record also returned its signed announce.
- Windows and Android builds completed. The Windows package passed fresh-profile startup, and the APK retains its existing signing certificate and application ID.
- All 87 Python tests and 39 frontend tests passed. The local DNS fixture registers genuine signed site announces for the co-hosted sites.
- The Android emulator resolved relay.cix through the public DNS server, then resolved it again after restarting without a network connection. The saved destination announce passed signature verification.
- Android X25519 public-key generation uses the bundled OpenSSL 3.5.9 and checks the RFC 7748 public-key vector at receiver startup. A production-strength DNS link succeeded where pure-Python stamp generation had timed out.
- Packaged Android crypto checks matched eight random public keys against Reticulum's original implementation. In this emulator, 1,000 public-key derivations took 0.087 seconds and a valid production-cost stamp took 0.233 seconds.

## 0.1.1 release checks

- Client runtime pins and native build checks now use Reticulum 1.6.1 and LXMF 1.3.1.
- All 86 Python tests and 39 frontend tests pass. The isolated network fixtures use valid lower-cost stamps to avoid repeating production-strength stamp work for every throwaway identity; production retains the upstream stamp costs.
- Node identity choices persist across page paths, query strings, restarts and DNS aliases, while other nodes and local identities remain separate. Legacy page choices are retained on upgrade.
- Client announces default to 45 minutes; saved custom intervals and server intervals are preserved.
- Windows startup passed with a fresh data folder. The Android package uses Reticulum’s portable stamp worker in Chaquopy.
- Gateway, propagation and DNS services are upgraded and retain their identities. Live DNS resolution and offline message upload/retrieval passed. Linux image/chat services restarted on the new versions; 36 tests and both local health probes passed.
- The fallback TCP interface now starts one reader on its supplied socket. A real fallback delivery test and live identified NomadPL page load passed.
- NomadPL 0.3.1 retries route discovery within the request deadline when the gateway connects after a page is opened.
- Windows packaging and a fresh-profile packaged startup check passed. Android uses the existing signing certificate, application ID and APK filename.
- The Android 15 emulator received messages and posted notifications without message bodies, kept receiving after the interface process closed, recovered its receiver and saved history after process termination, and delivered a queued message after reconnecting.
- 0.1.1 is published as a regular GitHub release. The 0.1.0 preview remains unchanged.

The notes below describe the original preview checks.


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
