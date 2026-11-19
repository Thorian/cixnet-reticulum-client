/** Application entry point: explicit navigation, startup, and one polling loop.
 * Feature modules export functions instead of replacing each other's functions.
 */
import { $, model, api, showDialog, showToast } from "./core.js";
import { loadIcons } from "./icons.js";
import { initPairing } from "./pairing-ui.js";
import { initAbout } from "./about-ui.js";
import { ensureIdentityUnlocked, initProtection } from "./protection-ui.js";
import {
  initIdentities,
  renderProfiles,
  syncIdentityUI,
  openIdentityManager,
} from "./identity-ui.js";
import {
  initMessaging,
  clearMessageDraft,
  activateMessaging,
  refreshHistory,
  renderConversations,
  renderMessages,
  showCompose,
  openConversation,
} from "./messaging-ui.js";
import {
  initBrowser,
  renderBrowse,
  renderDNS,
  renderBrowseNodes,
  leaveBrowser,
  openBrowserURL,
} from "./browser-ui.js";
import {
  refreshNetwork,
  initAnnounces,
  renderAnnounces,
  updateAnnounceTimes,
  openContactAnnounce,
} from "./network-ui.js";
import { initSettings } from "./settings.js";
import {
  renderWelcome,
  renderAnnounceWelcome,
  updateWelcomeStatus,
} from "./shell.js";

let lastPollError = "";

/** Switch views while clearing navigation state that belongs to the old tab. */
function showTab(tab) {
  leaveBrowser();
  model.tab = tab;
  model.conversation = null;
  $("search").value = "";
  document
    .querySelectorAll("[data-tab]")
    .forEach((button) =>
      button.classList.toggle("active", button.dataset.tab === tab),
    );
  $("list-title").textContent = {
    contacts: "Messages",
    browse: "Browse",
    announces: "Announces",
  }[tab];
  $("compose").classList.toggle("hidden", tab !== "contacts");
  $("search").placeholder = {
    contacts: "Search contacts and messages",
    browse: "Search services",
    announces: "Filter announces",
  }[tab];
  $("search").setAttribute("aria-label", $("search").placeholder);
  document
    .querySelector(".app-body")
    .classList.toggle("mobile-content", tab === "browse");
  if (tab === "contacts") {
    renderWelcome(showCompose);
    renderConversations();
  } else if (tab === "browse") {
    renderBrowse();
  } else {
    renderAnnounceWelcome();
    renderAnnounces();
  }
}

/** Activate one profile and discard the previous identity's visible history. */
async function selectIdentity(profile) {
  try {
    await ensureIdentityUnlocked(profile);
  } catch (error) {
    showToast(error.message);
    return;
  }
  model.active = profile;
  model.messages = [];
  model.appearances = {};
  model.peerNames = {};
  model.draftPeer = null;
  model.ownAddress = null;
  $("identity-screen").classList.add("hidden");
  $("client").classList.remove("hidden");
  syncIdentityUI();
  showTab("contacts");
  try {
    await activateMessaging(profile);
    await refreshHistory();
    renderConversations();
    const notification = (
      new URLSearchParams(location.hash.slice(1)).get("message") || ""
    ).match(/^([0-9a-f]{32}):([0-9a-f]{32})$/);
    if (notification && notification[1] === profile.id) {
      openConversation(notification[2]);
      history.replaceState(
        null,
        "",
        location.pathname +
          (model.accessKey ? "#client=" + model.accessKey : ""),
      );
    }
  } catch (error) {
    showToast(`Messaging: ${error.message}`);
  }
}

/** Schedule the next poll only after this one ends. Slow links must not produce
 * overlapping requests or duplicate timers after identity switches.
 */
async function poll() {
  try {
    await refreshNetwork();
    if (model.active) {
      const owner = model.active.id;
      const protection = await api("identity/protection/status", { owner });
      if (model.active?.id !== owner) return;
      if (protection.locked) {
        await $("identity-switch").onclick();
        return;
      }
      await refreshHistory();
      if (model.tab === "contacts") {
        renderConversations();
        renderMessages();
        updateWelcomeStatus();
      } else if (model.tab === "announces") renderAnnounces();
      else if (model.tab === "browse") renderBrowseNodes();
    }
    lastPollError = "";
  } catch (error) {
    $("connection-open").textContent = "Core unavailable";
    document.querySelector(".sidebar-footer").textContent =
      "Cannot reach the local client process";
    if (model.active && lastPollError !== error.message)
      showToast(error.message);
    lastPollError = error.message;
  } finally {
    setTimeout(poll, 2000);
  }
}

/** Initialize feature modules and restore the receiver's current client state. */
async function start() {
  initAbout();
  initProtection();
  window.addEventListener("hashchange", async () => {
    const notification = (
      new URLSearchParams(location.hash.slice(1)).get("message") || ""
    ).match(/^([0-9a-f]{32}):([0-9a-f]{32})$/);
    if (!notification || !model.active) return;
    if (model.active.id === notification[1]) {
      showTab("contacts");
      openConversation(notification[2]);
      history.replaceState(
        null,
        "",
        location.pathname +
          (model.accessKey ? "#client=" + model.accessKey : ""),
      );
    } else {
      await $("identity-switch").onclick();
      showToast("Select the identity for this message");
    }
  });
  initIdentities({ onSelect: selectIdentity });
  initMessaging({
    onBack: () => showTab("contacts"),
  });
  const onMessage = (address) => {
    showTab("contacts");
    openConversation(address);
  };
  initBrowser({ onMessage });
  initAnnounces({
    onMessage,
    onDNS: (address) => {
      showTab("browse");
      renderDNS(address);
    },
  });
  document.addEventListener("cixnet-open-contact", (event) => {
    showTab("announces");
    openContactAnnounce(event.detail);
  });
  document.addEventListener("cixnet-open-node", (event) => {
    /** Open an announced destination using its matching browsing protocol. */

    showTab("browse");
    openBrowserURL(
      event.detail.startsWith("nomadpl://")
        ? event.detail
        : `${event.detail}:/page/index.mu`,
    );
  });
  setInterval(updateAnnounceTimes, 1000);
  initSettings({ onManageIdentity: openIdentityManager });
  document.addEventListener("click", (event) => {
    /** Close the containing dialog when one of its close controls is clicked. */

    const close = event.target.closest("[data-close]");
    if (close) close.closest("dialog").close();
  });
  document.querySelectorAll("[data-tab]").forEach((button) => {
    /** Bind each navigation button to its own tab. */

    /** Open the tab associated with this navigation button. */
    button.onclick = () => showTab(button.dataset.tab);
  });
  /** Open the connection settings dialog. */
  $("connection-open").onclick = () => showDialog("connection-dialog");
  /** Refresh only the list belonging to the currently selected tab. */
  $("search").oninput = () => {
    if (model.tab === "contacts") renderConversations();
    else if (model.tab === "announces") renderAnnounces();
    else if (model.tab === "browse") renderBrowseNodes();
  };
  /** Return to identity selection without carrying over the active conversation. */
  $("identity-switch").onclick = async () => {
    if (model.active) {
      try {
        await api("identity/lock", { owner: model.active.id });
      } catch (error) {
        showToast(error.message);
        return;
      }
    }
    document
      .querySelectorAll("dialog[open]")
      .forEach((dialog) => dialog.close());
    leaveBrowser();
    clearMessageDraft();
    model.active = null;
    model.conversation = null;
    model.messages = [];
    model.appearances = {};
    model.peerNames = {};
    $("detail").replaceChildren();
    $("list-content").replaceChildren();
    $("client").classList.add("hidden");
    $("identity-screen").classList.remove("hidden");
    document.title = "ciXnet · Client";
    try {
      const state = await api("state");
      model.profiles = state.profiles;
      renderProfiles();
    } catch (error) {
      showToast(error.message);
    }
  };
  try {
    const state = await api("state");
    model.token = state.token;
    model.profiles = state.profiles;
    model.settings = state.settings;
    model.pairedPhone = state.paired_phone || null;
    if (model.pairedPhone) {
      for (const id of ["create-open", "import-open"]) {
        $(id).disabled = true;
        $(id).title = "Create or import identities on the phone";
      }
    }
    initPairing();
    await loadIcons();
    renderProfiles();
    poll();
  } catch (error) {
    $("profiles").textContent = `Could not start the client: ${error.message}`;
    $("create-open").disabled = true;
    $("import-open").disabled = true;
  }
}

start().catch((error) => {
  /** Keep startup failures visible and prevent actions that require initialized state. */

  $("profiles").textContent =
    `Could not initialize the interface: ${error.message}`;
  $("create-open").disabled = true;
  $("import-open").disabled = true;
});
