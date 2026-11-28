/** Live Reticulum status and announce views. This module does not start timers. */
import { $, model, api, escapeHTML, showToast } from "./core.js";
import { announceTime } from "./announce-time.js";
import { connectionStatus, connectionCounts } from "./connection-status.js";

let selectedAnnounce = null;
let actions;
let announcePage = 0;
let announceQuery = "";
const ANNOUNCES_PER_PAGE = 100;

/** Destination actions share the main client's conversation and DNS navigation. */
export function initAnnounces(callbacks) {
  actions = callbacks;
}

/** Fetch the latest receiver snapshot and update the connection summary. */
export async function refreshNetwork() {
  model.network = await api("network");
  renderNetworkStatus();
}

/** Describe local and TCP connectivity using actual peer counts. */
export function renderNetworkStatus() {
  const network = model.network;
  const { connected, label } = connectionStatus(network);
  const { lan: localPeers, tcp, total } = connectionCounts(network);
  $("connection-open").innerHTML =
    `<span class="dot ${connected ? "connected" : ""}"></span>${network.error && !network.localEnabled && network.phase === "running" ? "LAN unavailable · " : ""}${escapeHTML(label || network.phase)}<span>⌄</span>`;
  document.querySelector(".sidebar-footer").textContent =
    network.phase === "running"
      ? `${total} peer connections · ${localPeers} LAN / ${tcp} TCP`
      : `Reticulum · ${network.phase}`;
  $("connection-dialog").innerHTML =
    `<div class="dialog-top"><h2>Connection status</h2>
      <button data-close aria-label="Close">×</button></div>
    <div class="status-row"><span>Reticulum core</span><strong>${escapeHTML(network.phase)}</strong></div>
    <div class="status-row"><span>Local peer discovery</span><strong>${network.localEnabled ? `${localPeers} peers found` : "Disabled"}</strong></div>
    <div class="status-row"><span>Transport server</span><strong>${network.gateway?.serverAvailable ? "Reachable " + escapeHTML(network.gateway.server.kind) : "Not verified"}</strong></div>
    ${network.interfaces
      .map(
        (item) => `<div class="status-row"><span>${escapeHTML(item.name)}</span>
      <strong>${item.online ? "Online" : "Offline"} · ${item.type === "TCPClientInterface" ? `${item.online ? 1 : 0} peer connection` : item.type === "TCPServerInterface" ? "Listener" : `${item.peers} peers`}</strong></div>`,
      )
      .join("")}
    <div class="status-row"><span>Received / sent</span><strong>${network.rx || 0} / ${network.tx || 0} bytes</strong></div>
    <div class="status-row"><span>Fallback gateway</span><strong>${network.gateway ? escapeHTML(network.gateway.host + ":" + network.gateway.port + " · " + network.gateway.phase.replaceAll("_", " ")) : "Disabled"}</strong></div>
    ${network.error ? `<p class="error">${escapeHTML(network.error)}</p>` : ""}
    <p class="notice">A discovered peer is not necessarily a transport server.
      LXMF direct messaging is enabled. The automatic gateway connects only when no verified relay or transport server is available.
      LAN and TCP interface changes apply when settings are saved. Radio and UDP configuration are not implemented yet.</p>`;
}

/** Render announcements matching the search and retain the current selection. */
export function renderAnnounces() {
  const query = $("search").value.trim().toLowerCase();
  if (query !== announceQuery) {
    announceQuery = query;
    announcePage = 0;
  }
  const entries = model.network.announces.filter((entry) =>
    `${entry.address} ${entry.display_name || ""} ${entry.kind} ${entry.data}`
      .toLowerCase()
      .includes(query),
  );
  const pages = Math.max(1, Math.ceil(entries.length / ANNOUNCES_PER_PAGE));
  announcePage = Math.min(announcePage, pages - 1);
  const visible = entries.slice(
    announcePage * ANNOUNCES_PER_PAGE,
    (announcePage + 1) * ANNOUNCES_PER_PAGE,
  );
  const list = $("list-content");
  // Keep polling from rebuilding thousands of rows, or replacing unchanged ones.
  const signature = JSON.stringify([
    query,
    announcePage,
    entries.length,
    selectedAnnounce,
    model.network.phase,
    visible,
  ]);
  if (
    list.dataset.announcePage === signature &&
    list.querySelector(".announce-page")
  )
    return;
  list.dataset.announcePage = signature;
  list.replaceChildren();
  const navigation = document.createElement("div");
  navigation.className = "announce-page";
  navigation.setAttribute("aria-label", "Announce pages");
  for (const [label, direction] of [
    ["Previous", -1],
    ["Next", 1],
  ]) {
    const button = document.createElement("button");
    button.textContent = label;
    button.disabled =
      direction < 0 ? announcePage === 0 : announcePage === pages - 1;
    button.onclick = () => {
      announcePage += direction;
      renderAnnounces();
      list.scrollTop = 0;
    };
    navigation.append(button);
  }
  const count = document.createElement("span");
  count.textContent = `${announcePage + 1} / ${pages} · ${entries.length}`;
  navigation.insertBefore(count, navigation.lastChild);
  list.append(navigation);
  if (!entries.length) {
    $("list-content").innerHTML =
      `<div class="list-empty"><strong>${query ? "No matches" : "No announces received"}</strong>
      ${model.network.phase === "running" ? "Listening for live Reticulum announces." : "The network is not running."}</div>`;
  }
  for (const entry of visible) {
    const button = document.createElement("button");
    button.className = "announce-item compact-announce";
    const kind =
      {
        node: "nomadnet",
        lxmf: "station",
        nomadpl: "nomadpl",
        dns: "dns",
        relay: "relay",
        transport: "transport",
      }[entry.kind] || "unknown";
    const label = {
      nomadnet: "NomadNet",
      station: "Station",
      nomadpl: "NomadPL",
      dns: "DNS",
      relay: "Relay",
      transport: "Transport",
      unknown: "Other",
    }[kind];
    button.classList.add("entry-" + kind);
    button.classList.toggle(
      "entry-selected",
      selectedAnnounce === entry.address,
    );
    button.title = label + " · " + entry.address;
    button.innerHTML = `<div class="announce-heading"><strong>${escapeHTML(entry.display_name || label)}</strong><time data-announce-received="${entry.received}" title="${escapeHTML(new Date(entry.received * 1000).toLocaleString())}">${announceTime(entry.received)}</time></div><div class="announce-meta"><small class="entry-kind">${label}</small><small class="announce-hash">${escapeHTML(entry.address)}</small></div>`;
    /** Show the details belonging to this announced destination. */
    button.onclick = () => showAnnounce(entry);
    $("list-content").append(button);
  }
}

/** Use the latest known announce; saved contacts remain manageable without one. */
export function openContactAnnounce(address) {
  const entry = [...(model.network.announces || [])]
    .filter((item) => item.address === address && item.kind === "lxmf")
    .sort((a, b) => b.received - a.received)[0];
  showAnnounce(
    entry || {
      address,
      kind: "lxmf",
      identity: "Not available",
      data: "No announce received in this session.",
    },
  );
}

/** Display one destination's public metadata and supported open action. */
function showAnnounce(entry) {
  selectedAnnounce = entry.address;
  renderAnnounces();
  $("detail").innerHTML =
    `<button id="announce-back" class="back-button">← Back</button>
    <div class="browse-panel"><div class="eyebrow small">LIVE ANNOUNCE</div><h1>${escapeHTML(entry.kind === "dns" ? entry.display_name || "DNS server" : "Reticulum destination")}</h1>
    <p class="address-text">${escapeHTML(entry.address)}</p><h3>Identity hash</h3>
    <p class="address-text">${escapeHTML(entry.identity)}</p><h3>Application data</h3>
    <pre class="announce-data"></pre><p class="muted">Received ${entry.received ? new Date(entry.received * 1000).toLocaleString() : "not available in this session"}.
    Announce data is untrusted and displayed as text.</p></div>`;
  $("detail").querySelector("pre").textContent = entry.data || "None";
  if (entry.kind === "lxmf" || entry.kind === "dns") {
    const action = document.createElement("button");
    action.className = "primary";
    action.textContent = entry.kind === "lxmf" ? "Message" : "Add DNS server";
    action.onclick = () =>
      entry.kind === "lxmf"
        ? actions.onMessage(entry.address)
        : actions.onDNS(entry.address);
    $("detail").querySelector(".browse-panel").append(action);
  }
  if (entry.kind === "lxmf" && model.active) {
    const owner = model.active.id;
    const block = document.createElement("button");
    block.className = "contact-block-action";
    const update = () => {
      block.textContent = (model.blockedContacts || []).includes(entry.address)
        ? "Unblock contact"
        : "Block contact";
    };
    update();
    block.onclick = async () => {
      const blocked = !(model.blockedContacts || []).includes(entry.address);
      if (
        blocked &&
        !window.confirm(
          "Block this contact? New messages and notifications will be ignored. Saved history stays available.",
        )
      )
        return;
      block.disabled = true;
      try {
        const result = await api("messaging/block", {
          owner,
          peer: entry.address,
          blocked,
        });
        if (model.active?.id !== owner) return;
        model.blockedContacts = result.blocked;
        update();
        showToast(blocked ? "Contact blocked" : "Contact unblocked");
      } catch (error) {
        showToast(error.message);
      } finally {
        block.disabled = false;
      }
    };
    $("detail").querySelector(".browse-panel").append(block);
  }
  if (["node", "nomadpl"].includes(entry.kind)) {
    const open = document.createElement("button");
    open.className = "primary";
    open.textContent = "Open site";
    /** Open the selected site using the URL format belonging to its protocol. */
    open.onclick = () =>
      document.dispatchEvent(
        new CustomEvent("cixnet-open-node", {
          detail:
            entry.kind === "nomadpl"
              ? `nomadpl://${entry.address}/`
              : entry.address,
        }),
      );
    $("detail").querySelector(".browse-panel").append(open);
  }
  document.querySelector(".app-body").classList.add("mobile-content");
  /** Return from announcement details to the mobile list view. */
  $("announce-back").onclick = () =>
    document.querySelector(".app-body").classList.remove("mobile-content");
}

/** Refresh visible announcement ages without rebuilding their rows. */
export function updateAnnounceTimes() {
  if (model.tab !== "announces") return;
  document
    .querySelectorAll("time[data-announce-received]")
    .forEach((element) => {
      /** Update this announcement's age from its saved receipt timestamp. */

      element.textContent = announceTime(
        Number(element.dataset.announceReceived),
      );
    });
}
