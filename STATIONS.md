# Saved radio stations

Open Settings → Saved stations and radio profiles. The directory is client-wide,
persists in stations.sqlite, and remains usable without Internet access. Supply
latitude/longitude to sort by distance; leaving both blank sorts by last heard.
The position is not saved, uploaded to a directory operator or announced.
The API request stays within the local client (or the approved phone pairing).

The receiver registers Reticulum 1.6's InterfaceAnnounceHandler. Its upstream
signature and discovery-stamp validation runs before our learning callback.
Encrypted discovery is handled by upstream rules; we do not bypass encryption.
Only RNode entries with coordinates and complete radio settings are retained.
Public first/last heard times are stored with the profile. Local discoveries
appear immediately: the publication age filters do not apply to local learning.
The client never copies IFAC passwords, raw configurations or operator contacts
into this database. Discovery does not enable interfaces or transport mode.

Learned records and imported directory records are stored separately. Importing
a new directory replaces only that directory snapshot, preserving learned data
and all existing manual interface settings. Profiles are grouped by frequency,
bandwidth, spreading factor and coding rate. Different radio profiles on the
same transport identity remain separate. Limits: 10,000 records per source,
4 MiB compiled input, 200 rows displayed at once, rollback on invalid imports.

Records say “advertised”: hearing an announce through TCP or a radio does not
prove a direct radio neighbour. No direct reception or coverage claim is made.
This version prepares scan candidates; it does not tune, scan or transmit on an
RNode, and does not determine regional legal settings or hardware compatibility.
Use my location requests one device location fix on demand. Android asks for foreground location permission and accepts approximate or precise access. Remote web origins are denied access to this native permission flow. Location watching ends after a fix, denial/timeout, dialog close or hiding the app. Accuracy is displayed; manual entry remains available. No background-location permission or location announcement is added.

## Directory updates

- Import a version-1 JSON file using the chooser.
- “Update from ciXnet” asynchronously fetches only
  https://gw.cixnet.org/stations-v1.json. It never requests RMAP from the client.
  Redirects are refused; failed/invalid downloads leave the previous list intact.
- For Reticulum, paste a native destination:/file/stations-v1.json address and
  request a transfer. Existing owner-scoped browser jobs carry the file and the
  validated JSON is imported after completion. Closing the dialog cancels a
  pending transfer. Review the chosen source: imports are not independently
  signed station truth. Their advertised metadata may be incorrect.

Both update services need actual deployment; no public file destination is yet
configured and no Reticulum node address has been invented. The HTTPS endpoint
requires TLS even if the separate information page stays plain HTTP. A failure
is visible in the dialog; there is no fallback to scraping RMAP. No automatic
client update loop or bundled third-party snapshot is enabled in this preview.

## Weekly compiler on ciXnet infrastructure

deployment/gateway/compile_stations.py accepts an operator-fetched nodes.php
snapshot and writes a compact static stations-v1.json. It parses the embedded
JSON without executing scripts. update_stations.py supplies the once-weekly
upstream fetch; the systemd service/timer are deployment templates, not enabled
jobs. Obtain redistribution agreement before publishing or scheduling them.

The compilation includes only stations with:

- First heard strictly before one calendar month prior to compilation (UTC).
- Last heard strictly less than 24 hours before compilation, never in the future.
- Valid coordinates and complete RNode frequency/bandwidth/SF/coding-rate values.

A calendar month is used, clamping the date for shorter months. Exact cutoff
times are excluded. Empty results, changed input format and failed fetches keep
the previous published file. The file carries its compilation timestamp.

For deployment, install the Python scripts with stations.py at the same relative
layout under /opt/cixnet-directory. Create the cixnet-directory service account,
serve the generated file read-only from /var/lib/cixnet-directory through the
chosen static HTTPS host, and expose a copy through the intended Reticulum
/file/ service. Do not serve private application databases. The HTML information
page and stylesheet-free design remain independent of this offline batch job.
