import { refreshProtection } from "./protection-ui.js";
import { initStations } from "./stations-ui.js";
/** Apply validated LAN/TCP settings without changing identity fields. */
import { $, model, api, escapeHTML, showDialog, showToast } from "./core.js";

let interfaceDrafts = [];
let editingIndex = null;

/** Render editable network drafts alongside their currently applied interface state. */
function renderInterfaces() {
  $("interface-list").replaceChildren();
  interfaceDrafts.forEach((item, index) => {
    /** Build controls and status text for one editable interface draft. */

    const row = document.createElement("div");
    row.className = "interface-row";
    const tcp = item.type === "TCPClientInterface";
    const enabled = item.enabled ?? Boolean(item.host);
    const live = model.network.interfaces.find((entry) =>
      entry.name.includes(`[ciXnet ${item.name}/`),
    );
    const saved = model.settings.interfaces.some(
      (entry) => JSON.stringify(entry) === JSON.stringify(item),
    );
    const status = !saved
      ? "Pending save"
      : !enabled
        ? "Disabled"
        : live?.online
          ? "Connected"
          : "Connecting / retrying";
    row.innerHTML = `<span>${escapeHTML(item.name)}<small>${tcp ? `${escapeHTML(item.host || "No host")} : ${item.port || "—"} · ${status}` : `${escapeHTML(item.type)} · Not implemented`}</small></span>`;
    if (tcp) {
      const toggle = document.createElement("input");
      toggle.type = "checkbox";
      toggle.checked = enabled;
      toggle.setAttribute("aria-label", `Enable ${item.name}`);
      /** Change this draft's enabled state without applying network settings yet. */
      toggle.onchange = () => {
        item.enabled = toggle.checked;
        renderInterfaces();
      };
      const edit = document.createElement("button");
      edit.type = "button";
      edit.textContent = "Edit";
      /** Load this interface draft into the edit fields. */
      edit.onclick = () => {
        editingIndex = index;
        $("interface-name").value = item.name;
        $("interface-host").value = item.host || "";
        $("interface-port").value = item.port || 4242;
        $("interface-add").textContent = "Update";
        $("interface-name").focus();
      };
      row.append(toggle, edit);
    }
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "Remove";
    /** Remove the selected draft and reset the interface editor. */
    remove.onclick = () => {
      interfaceDrafts.splice(index, 1);
      editingIndex = null;
      $("interface-add").textContent = "Add";
      renderInterfaces();
    };
    row.append(remove);
    $("interface-list").append(row);
  });
}

/** Populate the settings dialog from the current saved configuration. */
function openSettings() {
  $("local-discovery").checked = model.settings.localDiscovery;
  $("fallback").checked = model.settings.fallback;
  $("fallback-host").value = model.settings.fallbackHost || "gw.cixnet.org";
  $("fallback-port").value = model.settings.fallbackPort || 4242;
  const gateway = model.network.gateway;
  $("fallback-status").textContent = gateway
    ? `${gateway.host}:${gateway.port} · ${gateway.phase.replaceAll("_", " ")}`
    : "Automatic gateway";
  $("media").value = model.settings.media;
  $("announce-minutes").value = model.settings.announceMinutes;
  $("propagation-servers").value = (
    model.settings.propagationServers || []
  ).join("\n");
  $("delivery-mode").value = model.settings.deliveryMode || "auto";
  $("mailbox-check-minutes").value = model.settings.mailboxCheckMinutes ?? 5;
  $("propagation-discovered").replaceChildren(
    new Option("Discovered relays…", ""),
  );
  for (const entry of model.network.announces.filter(
    (item) => item.kind === "relay",
  )) {
    $("propagation-discovered").add(
      new Option(
        `${entry.display_name || "Relay"} · ${entry.address.slice(0, 8)}…`,
        entry.address,
      ),
    );
  }
  $("propagation-status").textContent =
    "Save changes before checking mailboxes. Automatic checks visit each configured relay.";
  // Cancel must not mutate the saved list through a shared array reference.
  // The LAN switch owns AutoInterface; old prototype rows are redundant.
  interfaceDrafts = structuredClone(model.settings.interfaces).filter(
    (item) => item.type !== "AutoInterface",
  );
  editingIndex = null;
  $("interface-add").textContent = "Add";
  $("settings-error").textContent = "";
  renderInterfaces();
  showDialog("settings-dialog");
  refreshProtection().catch((error) => showToast(error.message));
}

/** Validate the submitted settings and apply them through the local API. */
async function saveSettings(event) {
  event.preventDefault();
  const settings = {
    localDiscovery: $("local-discovery").checked,
    fallback: $("fallback").checked,
    fallbackHost: $("fallback-host").value.trim(),
    fallbackPort: Number($("fallback-port").value),
    media: $("media").value,
    announceMinutes: Number($("announce-minutes").value),
    interfaces: interfaceDrafts,
    propagationServers: $("propagation-servers")
      .value.split(/[\s,;]+/)
      .filter(Boolean),
    deliveryMode: $("delivery-mode").value,
    mailboxCheckMinutes: Number($("mailbox-check-minutes").value),
  };
  try {
    await api("settings", settings);
    model.settings = structuredClone(settings);
    $("settings-dialog").close();
    showToast("Settings saved and interfaces applied");
  } catch (error) {
    $("settings-error").textContent = error.message;
  }
}

/** Bind network, relay, identity and announce controls in the settings dialog. */
export function initSettings({ onManageIdentity }) {
  initStations();
  /** Add the selected announced relay to the editable server list. */
  $("propagation-add").onclick = () => {
    const address = $("propagation-discovered").value;
    if (!address) return;
    const entries = $("propagation-servers")
      .value.split(/[\s,;]+/)
      .filter(Boolean);
    if (!entries.includes(address)) entries.push(address);
    $("propagation-servers").value = entries.join("\n");
  };
  /** Request a mailbox check for the explicitly selected identity. */
  $("propagation-sync").onclick = async () => {
    try {
      if (!model.active) throw new Error("Select an identity first");
      await api("messaging/sync", { owner: model.active.id });
      $("propagation-status").textContent =
        "Checking configured relay mailboxes…";
    } catch (error) {
      $("propagation-status").textContent = error.message;
    }
  };
  /** Ask the receiver to announce identities immediately. */
  $("announce-now").onclick = async () => {
    try {
      await api("identities/announce", {});
      showToast("Identity announces requested");
    } catch (error) {
      $("settings-error").textContent = error.message;
    }
  };
  $("settings-open").onclick = openSettings;
  $("mobile-settings-open").onclick = openSettings;
  $("settings-form").onsubmit = saveSettings;
  /** Leave settings and edit the active identity's metadata. */
  $("settings-identity").onclick = () => {
    $("settings-dialog").close();
    onManageIdentity(model.active);
  };
  /** Validate and add or replace the interface currently being edited. */
  $("interface-add").onclick = () => {
    const name = $("interface-name").value.trim();
    if (!name) return $("interface-name").focus();
    const host = $("interface-host").value.trim();
    const port = Number($("interface-port").value);
    if (!host || !Number.isInteger(port) || port < 1 || port > 65535) {
      $("settings-error").textContent =
        "Enter a host and TCP port from 1 to 65535.";
      return;
    }
    const item = {
      name,
      type: "TCPClientInterface",
      host,
      port,
      enabled: true,
    };
    if (editingIndex === null) interfaceDrafts.push(item);
    else interfaceDrafts[editingIndex] = item;
    editingIndex = null;
    $("interface-add").textContent = "Add";
    $("interface-name").value = "";
    $("interface-host").value = "";
    $("interface-port").value = "4242";
    $("settings-error").textContent = "";
    renderInterfaces();
  };
}
