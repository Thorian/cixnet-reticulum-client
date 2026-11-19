import { beginActivity } from "./activity.js";
/** Shared UI state. Private keys never belong here; export is an explicit action. */
export const model = {
  token: null,
  accessKey: new URLSearchParams(globalThis.location?.hash?.slice(1) || "").get(
    "client",
  ),
  profiles: [],
  settings: {},
  active: null,
  tab: "contacts",
  conversation: null,
  draftPeer: null,
  ownAddress: null,
  messages: [],
  appearances: {},
  peerNames: {},
  network: { phase: "not_started", interfaces: [], announces: [], peers: 0 },
};

/** Find a client control by its stable element identifier. */
export const $ = (id) => document.getElementById(id);

/** Escape peer-controlled text before placing it inside an HTML template. */
export function escapeHTML(value) {
  const replacements = {
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  };
  return String(value).replace(
    /[&<>"']/g,
    (character) => replacements[character],
  );
}

let tokenRefresh = null;

/** A restarted service invalidates the old token. Refresh once after a rejected
 * request; never retry accepted requests or arbitrary network failures.
 */
export async function apiResponse(path, body) {
  /** Send one API attempt with the current per-process mutation token. */
  const send = () =>
    fetch(
      `/api/${path}`,
      body === undefined
        ? {
            headers: model.accessKey
              ? { Authorization: "Bearer " + model.accessKey }
              : {},
          }
        : {
            method: "POST",
            headers: {
              ...(model.accessKey
                ? { Authorization: "Bearer " + model.accessKey }
                : {}),
              "Content-Type": "application/json",
              "X-Cixnet-Token": model.token,
            },
            body: JSON.stringify(body),
          },
    );
  const response = await send();
  if (body === undefined || response.status !== 403) return response;
  if (!tokenRefresh) {
    tokenRefresh = (async () => {
      /** Fetch the new receiver token after an explicitly rejected mutation. */

      const stateResponse = await fetch("/api/state", {
        headers: model.accessKey
          ? { Authorization: "Bearer " + model.accessKey }
          : {},
      });
      if (!stateResponse.ok)
        throw new Error("Could not reconnect to the local service.");
      const state = await stateResponse.json();
      if (typeof state.token !== "string" || !state.token)
        throw new Error("Invalid service response.");
      model.token = state.token;
    })().finally(() => {
      /** Allow a later restart to begin a fresh token-recovery attempt. */

      tokenRefresh = null;
    });
  }
  await tokenRefresh;
  return send();
}

/** Keep mutations on the local origin and include the per-process request token. */
const pendingActions = new Map();
const actionLabels = {
  settings: "Saving settings",
  "messaging/send": "Submitting message",
  "messaging/sync": "Checking mailboxes",
  "messaging/activate": "Opening identity",
  "messaging/block": "Updating contact",
  "identity/update": "Saving identity",
  "identities/announce": "Announcing identity",
  "dns/save": "Saving name server",
  "browser/bookmark": "Saving bookmark",
  "browser/external": "Opening external browser",
  "pairing/connect": "Connecting to phone",
  "pairing/invite": "Preparing pairing code",
  "stations/refresh": "Updating station list",
  "stations/import": "Importing stations",
};

/** Share an in-flight action instead of submitting it twice. Polling stays quiet. */
export function api(path, body) {
  const label = body === undefined ? null : actionLabels[path];
  const key = label ? JSON.stringify([path, body]) : null;
  if (key && pendingActions.has(key)) return pendingActions.get(key);
  const finish = label ? beginActivity(label) : () => {};
  const request = (async () => {
    try {
      const response = await apiResponse(path, body);
      const result = await response.json();
      if (!response.ok)
        throw new Error(
          result.error || "The local service rejected the request.",
        );
      return result;
    } finally {
      finish();
      if (key) pendingActions.delete(key);
    }
  })();
  if (key) pendingActions.set(key, request);
  return request;
}

let toastTimer;
/** Show a transient status message, replacing the previous toast's timer. */
export function showToast(message) {
  clearTimeout(toastTimer);
  $("toast").textContent = message;
  $("toast").classList.remove("hidden");
  toastTimer = setTimeout(() => $("toast").classList.add("hidden"), 3500);
}

/** Open a modal dialog only when it is not already open. */
export function showDialog(id) {
  if (!$(id).open) $(id).showModal();
}

/** Prefer a live public name, then saved metadata, then the destination address. */
export function peerName(address) {
  return (
    model.network.announces.find((entry) => entry.address === address)
      ?.display_name ||
    model.peerNames[address] ||
    `${address.slice(0, 12)}…`
  );
}

/** Format a message timestamp using the user's local clock settings. */
export function shortTime(timestamp) {
  return new Date(timestamp * 1000).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
}
