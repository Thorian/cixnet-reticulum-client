# Development guide

The client shares its Python receiver and web interface across the browser preview, Windows package and Android app. Linux packaging uses the same desktop launcher.

## Where to look

| File | Responsibility |
| --- | --- |
| `server.py` | Arguments, dependency locations, main-thread startup |
| `http_api.py` | Local HTTP boundary, request validation, explicit API routing |
| `profiles.py` | Profile metadata, atomic JSON saves, key import/export, preferences |
| `web_services.py` | Explicit per-identity DNS suffix choices, library resolver/cache, isolated HTML gateways |
| `nomad_browser.py` | Bounded native requests, link lifecycle, isolated bookmarks/downloads |
| `ui/browser-ui.js` | Browser navigation, request polling, node discovery and forms |
| `ui/micron.js` | Micron parsing and safe DOM rendering |
| `network.py` | Reticulum lifecycle, interface statistics, bounded announces |
| `messaging.py` | LXMF routers, callbacks, per-identity SQLite history |
| `appearance.py` | Validate and encode the LXMF icon-name/RGB wire format |
| `ui/app.js` | Startup, navigation, identity selection, single polling loop |
| `ui/core.js` | Shared UI state, request and text-escaping helpers |
| `ui/identity-ui.js` | Identity selector, editor, explicit private-key download |
| `ui/messaging-ui.js` | Conversations, composition, message/status rendering |
| `ui/network-ui.js` | Live connection status and announce views |
| `ui/settings.js` | Connection drafts and media settings |
| `ui/icons.js` | Local icon catalog, safe SVG rendering, icon picker |
| `ui/shell.js` | Welcome and announce views |
| `ui/about.html` | Project information, upstream links, credits, licenses |

## Build and formatting

Use Node.js and install the pinned development dependencies with `npm ci`. Run `npm run build` after editing JavaScript. It produces a non-minified `ui/dist/client.js` with a source map. Edit the source modules, not the generated bundle. The committed bundle allows the preview to run without requiring Node.js at launch.

The single browser asset also avoids ES-module fetching problems in the desktop preview browser. Source modules still use ordinary imports and explicit initialization; features do not wrap or replace one another's functions.

`npm run format` formats first-party HTML/CSS/JavaScript; `npm run format:check` checks it. Vendor assets, licenses, and generated output are excluded. Use Ruff for Python: `ruff format .` and `ruff check .`. The tools are development dependencies, not requirements for running the client.

## Tests

From this directory:

```text
python -m unittest discover -s tests -v
npm test
```

Install requirements-dev.txt before testing. Dependencies are normally imported from the active environment. RETICULUM_SOURCE, LXMF_SOURCE, RETDNS_SOURCE and NOMADPL_SOURCE optionally add source-checkout paths. No machine-specific paths are required.

The integration suite starts two independent temporary Reticulum/LXMF processes on available loopback ports. It verifies real delivery, appearance transfer, identity backup, persistence across restart, and API request boundaries. It never uses existing user profiles. Pure frontend tests cover text escaping and safe avatar rendering; browser smoke checks still matter for actual controls, layout, and downloads.

## Important design decisions

- Reticulum and LXMF install signal handlers: construct them on the main thread. The local HTTP server deliberately uses `HTTPServer`, not a threaded request server. Network deliveries and SQLite callbacks are threaded separately.
- SQLite is protected by a lock because delivery callbacks run off the request thread. Every query is scoped to its owning identity. Repeated delivery does not duplicate a message row.
- A nickname, display name, or avatar edit never regenerates keys. UI profile metadata contains no private keys. Raw keys reach the browser only through explicit import/export operations.
- Polling schedules the next request after the current cycle finishes. Identity switches discard stale responses. Unchanged conversation rows stay mounted to preserve focus and click targets.
- Incoming messages render as text. Icon names resolve against the bundled catalog; received colors must be fixed-size RGB values. Do not render arbitrary peer HTML or CSS.
- Outgoing payloads and attachments commit atomically before delivery. The durable outbox resumes after restart and tracks each relay separately. Only recipient proof completes delivery; relay acceptance completes that copy. Legacy messages without saved payloads remain labelled `interrupted`.
- User keys and history remain outside the source directory under the selected `--data` directory. Windows Hello protects interface access on supported Windows devices. Android biometric integration is unfinished; saved keys and history remain unencrypted at rest.

## Commenting convention

Use names that explain what code does. Comments should explain why a constraint exists, a protocol boundary, a security decision, or a non-obvious lifecycle choice. Avoid comments that merely repeat the next line. Keep upstream code and notices distinct from original ciXnet code.

## Attachment modules

attachments.py validates bounded payloads, sanitizes display names, detects raster types, and translates standard LXMF fields. Messaging stores attachment BLOBs and message rows in one SQLite transaction; history includes descriptors without file bytes. The authenticated attachment endpoint uses exact owner/message/position keys and never resolves a filename as a path.

ui/attachments-ui.js handles file reads, image reduction, blob downloads, and optional raster previews. ui/camera-ui.js owns the camera dialog and stream cleanup. Original photos stay untouched; camera output and reduced files enter the same attachment draft/send flow.

NomadNet source was consulted for existing attachment field layouts, with no application implementation copied. Browser canvas and camera APIs require no new bundled library.

Restart recovery: the page renews its per-process request token after an explicitly rejected request and retries that request once. It never replays accepted requests or retries arbitrary network failures. Binary attachment downloads and identity exports use the same recovery helper. Known public contact names persist in SQLite. Identity selection shows saved message counts; histories remain separate for each cryptographic identity.

Interface definitions and validation live in interface_config.py. Network.apply_interfaces reconciles managed LAN/TCP entries through the upstream public attach/detach API. Unchanged interfaces and built-in test links are retained; failed application attempts restore the previous config. RNode/UDP prototype drafts remain inactive and are labeled unsupported.

The native browser integration fixture uses the supplied server PageSite class and its actual main/community page files. It additionally tests relative requests, identified forms, native binary downloads, cancellation, bookmark restart persistence, and owner isolation.

The HTML frame has a separate per-identity/destination loopback hostname and a sandbox. Never serve remote HTML from the main client origin or expose private-key APIs to remote page scripts. retdns and NomadPL remain separately installable dependencies.

## Repository checks

GitHub Actions runs the Python suite and frontend checks on Windows and Linux using Python 3.12 and Node.js 22. Local fixture pages are included under tests/fixtures. Device tests and packaging are separate; CI does not publish releases.
