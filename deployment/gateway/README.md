# ciXnet gateway deployment

The live gateway uses Debian 13, Reticulum 1.6.1, LXMF 1.3.1 and retdns 0.2.1. Reticulum and the application services run as the unprivileged `cixnet` account, with state under `/var/lib/cixnet`.

## Services

- `cixnet-reticulum.service`: transport and public TCP listeners on port 4242.
- `cixnet-lxmf.service`: propagation mailbox, using the shared Reticulum instance. Automatic propagation peering is disabled.
- `cixnet-retdns.service`: name resolution, using the same instance.
- `caddy.service`: the static settings page with automatic HTTPS and HTTP redirects. The Caddyfile has no access-log directive; service and certificate diagnostics still go to the system journal.

`site/index.html` is one page with inline CSS, no graphics, scripts, analytics or external assets. Its document root is `/var/www/cixnet-gateway`. The BusyBox service file in this folder is an earlier HTTP-only setup; it is disabled on the live server.

Cloudflare records for `gw.cixnet.org` are DNS-only. The browser page uses TCP 80/443 and the Reticulum listener uses TCP 4242. A client must not put `https://` in its Reticulum gateway hostname.

## Uplinks and discovery

Configured uplinks are CRN (`rns.reticulum.world:6666`), MichMesh (`rns.michmesh.net:7822`), Germany 002 (`193.26.158.230:4965`), Rmap (`rmap.world:4242`) and R3AKT (`134.122.46.48:37428`). Quad4 (`rns2.quad4.io:4242`) and BetweenTheBorders (`reticulum.betweentheborders.com:4242`) are configured but were unavailable at the last connection check.

The public listener announces as **ciXnet gateway**, reachable at `gw.cixnet.org:4242`, every 15 minutes. No coordinates are published.

## Station directory

`compile_stations.py` and `update_stations.py` prepare a static JSON file independently of the settings page. See [STATIONS.md](../../STATIONS.md). Directory distribution remains pending RMAP redistribution terms; clients do not scrape RMAP.

## Reticulum DNS

The VPS runs retdns 0.2.1 as `cixnet-retdns.service`, using the shared Reticulum instance. Its destination is `48a1ab73497b08453287f12630883de6`, named **ciXnet DNS**, with an announce interval of 900 seconds. No additional Internet port is needed.

Identity: `/var/lib/cixnet/retdns/server.identity`. Authoritative database: `/var/lib/cixnet/retdns/records.sqlite3`. Both belong to the unprivileged `cixnet` account. Retain the identity when moving or restoring the service; changing it changes the destination address pinned by clients.

Client suffix: `.cix`. The client strips that suffix before querying the authority. The initial records are `dns` (the DNS service itself) and `relay` (the propagation destination), with 86400-second TTLs. These are service destinations, not web pages. Add names locally with:

```sh
sudo -u cixnet /opt/cixnet/venv/bin/retdns records --database /var/lib/cixnet/retdns/records.sqlite3 add NAME DESTINATION_HASH
```

Record changes take effect without restarting retdns. Remote clients cannot register or alter names. After a manual Reticulum restart, check and restart `cixnet-retdns.service` alongside `cixnet-lxmf.service` if needed.
