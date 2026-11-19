import { lxmfAddress } from "./lxmf-links.js";
import {
  browseKinds,
  loadBrowseKinds,
  saveBrowseKinds,
  discoveredNodes,
} from "./browse-filters.js";
import { serviceIcon } from "./icons.js";
import { beginActivity } from "./activity.js";
import { loadMicronImage } from "./micron-images.js";
/** Native NomadNet navigation. Requests are asynchronous jobs in the service. */
import { $, model, api, apiResponse, escapeHTML, showToast } from "./core.js";
import { renderMicron, collectMicronFields } from "./micron.js";

const sessions = new Map();
let generation = 0;
let timer = null;
let currentJob = null;
let finishLoading = () => {};
let pendingNavigation = null;
let onMessage;
let nodeSignature = "";
let selectedBrowseKinds;
function browseSelection() {
  if (!selectedBrowseKinds) {
    try {
      selectedBrowseKinds = loadBrowseKinds(localStorage);
    } catch {
      selectedBrowseKinds = new Set(browseKinds.map((item) => item.kind));
    }
  }
  return selectedBrowseKinds;
}
let frameContext = null;

/** Return the active identity's independent browser history and bookmark state. */
function session() {
  const owner = model.active.id;
  if (!sessions.has(owner))
    sessions.set(owner, {
      history: [],
      index: -1,
      bookmarks: [],
    });
  return sessions.get(owner);
}

/** Connect browser navigation, frame messages and sidebar resizing controls. */
export function initBrowser(callbacks) {
  onMessage = callbacks.onMessage;
  window.addEventListener("message", receiveFrameNavigation);
  const body = document.querySelector(".app-body");
  const resize = $("sidebar-resize");
  /** Clamp and persist the sidebar width while updating its accessible value. */
  const saveWidth = (value) => {
    const width = Math.max(180, Math.min(430, value));
    body.style.setProperty("--sidebar-width", width + "px");
    resize.setAttribute("aria-valuenow", String(width));
    try {
      localStorage.setItem("cixnet-sidebar-width", String(width));
    } catch {
      /* Storage may be disabled. */
    }
  };
  try {
    saveWidth(Number(localStorage.getItem("cixnet-sidebar-width")) || 260);
    body.classList.toggle(
      "sidebar-collapsed",
      localStorage.getItem("cixnet-sidebar-hidden") === "true",
    );
  } catch {
    saveWidth(260);
  }
  $("sidebar-toggle").onclick = toggleSidebar;
  /** Start a captured sidebar drag so resizing continues outside the handle. */
  resize.onpointerdown = (event) => {
    resize.setPointerCapture(event.pointerId);
    /** Update sidebar width from the pointer's position within the application. */
    resize.onpointermove = (move) =>
      saveWidth(move.clientX - body.getBoundingClientRect().left);
    /** Stop resizing when the captured pointer is released. */
    resize.onpointerup = () => {
      resize.onpointermove = null;
    };
    /** Clear the drag handler if pointer capture ends unexpectedly. */
    resize.onlostpointercapture = () => {
      resize.onpointermove = null;
    };
  };
  /** Resize the sidebar with keyboard controls and suppress page scrolling. */
  resize.onkeydown = (event) => {
    if (["ArrowLeft", "ArrowRight"].includes(event.key)) {
      event.preventDefault();
      saveWidth(
        Number(resize.getAttribute("aria-valuenow")) +
          (event.key === "ArrowLeft" ? -10 : 10),
      );
    }
  };
}

/** Cancel active page work and invalidate callbacks from the previous navigation. */
export function leaveBrowser() {
  finishLoading();
  frameContext?.finishActivity?.();
  pendingNavigation = null;
  generation++;
  clearTimeout(timer);
  if (currentJob)
    api("browser/cancel", currentJob).catch(() => {
      /** Ignore cancellation errors after the user has already left the page. */
    });
  currentJob = null;
}

/** Build the selected identity's browser controls and restore its current page. */
export function renderBrowse() {
  const state = session();
  $("detail").innerHTML =
    `<section class="nomad-browser"><header class="browser-toolbar">
    <div class="browser-topline"><button type="button" id="browser-nodes" title="Show sites" aria-label="Show sites">☰</button><button type="button" id="browser-back" title="Back" aria-label="Previous page">←</button><button type="button" id="browser-forward" title="Forward" aria-label="Next page">→</button><button type="button" id="browser-reload" title="Refresh" aria-label="Reload page">↻</button>
    <form id="browser-address-form" class="address-bar"><input id="browser-address" aria-label="Network address" placeholder="Enter a name or address" autocomplete="off" required><button type="button" id="browser-identify" aria-label="Identify to site" aria-pressed="false" title="Identify to site as ${escapeHTML(model.active.nickname)}"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="7" r="3.5"/><path d="M5 21v-3a7 7 0 0 1 14 0v3"/></svg></button><button type="button" id="browser-bookmark" aria-label="Bookmark page" title="Bookmark page">☆</button></form>
    <button type="button" id="browser-external" title="Open in external browser" aria-label="Open in external browser">↗</button><button type="button" id="browser-dns" title="Name servers">DNS</button><button type="button" id="browser-source" title="View source" aria-label="View source">&lt;/&gt;</button><button type="button" id="browser-stop" hidden aria-label="Stop loading">×</button></div><p id="browser-status" role="status"></p></header>
    <div id="browser-document" class="micron-document"><h1>Browse the network</h1><p>Choose a discovered node or enter its page destination address.</p><p>Use the node address, not its identity hash or messaging address.</p></div></section>`;
  $("browser-dns").onclick = () => renderDNS();
  $("browser-external").onclick = async () => {
    const page = state.history[state.index];
    if (!page?.frame) return;
    try {
      const named = page.url.startsWith("nomadpl://")
        ? page.url
        : page.resolved;
      const result = await api("browser/external", {
        owner: model.active.id,
        url: named,
        identify: page.identify,
        launch: true,
      });
      if (result.launched) {
        showToast("External browser bridge opened. Keep ciXnet running.");
        return;
      }
      const link = document.createElement("a");
      link.href = result.url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = "Open local browser bridge";
      $("browser-status").replaceChildren(link);
    } catch (error) {
      showToast(error.message);
    }
  };
  $("browser-identify").setAttribute(
    "aria-pressed",
    String(state.history[state.index]?.identify || false),
  );
  $("browser-identify").onclick = async () => {
    const page = state.history[state.index];
    if (!page) return;
    try {
      const choice = await api("browser/identify", {
        owner: model.active.id,
        url: page.identityURL || page.url,
        identify: !page.identify,
      });
      page.identify = choice.identify;
      $("browser-identify").setAttribute("aria-pressed", String(page.identify));
      showToast(
        page.identify
          ? "Identify enabled for this page"
          : "Identify disabled for this page",
      );
    } catch (error) {
      showToast(error.message);
    }
  };
  /** Navigate to the entered address without submitting the form to the web server. */
  $("browser-address-form").onsubmit = (event) => {
    event.preventDefault();
    openBrowserURL($("browser-address").value);
  };
  $("browser-nodes").onclick = toggleSidebar;
  /** Move to the previous entry in this identity's browser history. */
  $("browser-back").onclick = () => showHistory(state.index - 1);
  /** Move to the next entry in this identity's browser history. */
  $("browser-forward").onclick = () => showHistory(state.index + 1);
  /** Fetch the current history entry again without adding a duplicate entry. */
  $("browser-reload").onclick = () => {
    if (state.index >= 0)
      openBrowserURL(state.history[state.index].url, null, true);
  };
  /** Cancel the pending request and show that navigation has stopped. */
  $("browser-stop").onclick = () => {
    if (frameContext?.frame.isConnected && frameContext.channel) {
      frameContext.frame.contentWindow.postMessage(
        { type: "cixnet-stop", channel: frameContext.channel },
        frameContext.origin,
      );
    }
    leaveBrowser();
    $("browser-status").textContent = "Request cancelled";
    $("browser-stop").hidden = true;
  };
  $("browser-bookmark").onclick = bookmarkCurrent;
  /** Display retained page source without issuing another remote request. */
  $("browser-source").onclick = async () => {
    if (state.index < 0) return;
    const page = state.history[state.index];
    const owner = model.active.id;
    try {
      const source = page.frame
        ? (
            await api("browser/source", {
              owner,
              url: page.sourceResolved || page.resolved,
              source_id: page.sourceId,
              identify: page.identify,
            })
          ).source
        : page.source;
      if (model.active?.id !== owner || model.tab !== "browse") return;
      const dialog = document.createElement("dialog");
      dialog.className = "source-dialog";
      const close = document.createElement("button");
      close.textContent = "Close source";
      const pre = document.createElement("pre");
      pre.textContent = source;
      /** Close the temporary page-source dialog. */
      close.onclick = () => dialog.close();
      /** Remove the temporary source dialog after it closes. */
      dialog.onclose = () => dialog.remove();
      dialog.append(close, pre);
      document.body.append(dialog);
      dialog.showModal();
    } catch (error) {
      showToast(error.message);
    }
  };
  renderBrowseNodes();
  if (state.index >= 0) paint(state.history[state.index]);
  updateButtons();
  const owner = model.active.id;
  api("browser/bookmarks", { owner })
    .then((result) => {
      /** Restore bookmarks only if the same identity is still active. */

      if (model.active?.id !== owner) return;
      state.bookmarks = result.bookmarks;
      if (model.tab === "browse") {
        renderBrowseNodes();
        updateButtons();
      }
    })
    .catch((error) => showToast(error.message));
}

/** Synchronize browser controls with the current history and bookmark state. */
function updateButtons() {
  if (!$("browser-back")) return;
  const state = session();
  const unsynced = Boolean(
    state.history[state.index]?.frame &&
      frameContext?.frame.isConnected &&
      frameContext.unsynced,
  );
  $("browser-source").disabled = state.index < 0 || unsynced;
  $("browser-external").disabled =
    !state.history[state.index]?.frame || unsynced;
  $("browser-back").disabled = state.index <= 0;
  $("browser-forward").disabled = state.index >= state.history.length - 1;
  $("browser-reload").disabled = state.index < 0;
  $("browser-bookmark").disabled = state.index < 0 || unsynced;
  const marked =
    state.index >= 0 &&
    state.bookmarks.some((item) => item.url === state.history[state.index].url);
  $("browser-bookmark").textContent = marked ? "★" : "☆";
  $("browser-bookmark").title = marked ? "Remove bookmark" : "Bookmark page";
  $("browser-bookmark").setAttribute(
    "aria-label",
    marked ? "Remove bookmark" : "Bookmark page",
  );
}

/** Render discoverable sites, stations and saved destinations matching the search. */
export function renderBrowseNodes() {
  if (model.tab !== "browse" || !model.active) return;
  const state = session();
  const query = $("search").value.toLowerCase();
  const selectedKinds = browseSelection();
  const nodes = discoveredNodes(model.network.announces, selectedKinds);
  const signature = JSON.stringify([
    state.bookmarks,
    [...selectedKinds],
    state.history[state.index]?.url,
    nodes.map(
      /** Index announced display names by their destination address. */ ({
        address,
        display_name,
        kind,
      }) => ({ address, display_name, kind }),
    ),
    query,
    model.active.id,
  ]);
  if (
    signature === nodeSignature &&
    $("list-content").querySelector(".browser-list-heading")
  )
    return;
  nodeSignature = signature;
  $("list-content").dataset.browserNodes = "true";
  $("list-content").replaceChildren();
  for (const [title, entries] of [
    ["Bookmarks", state.bookmarks],
    [
      "Discovered nodes",
      nodes.map((item) => ({
        name: item.display_name || "Unnamed station",
        kind: item.kind,
        address: item.address,
        url:
          item.kind === "nomadpl"
            ? `nomadpl://${item.address}/`
            : `${item.address}:/page/index.mu`,
      })),
    ],
  ]) {
    const heading = document.createElement("h3");
    heading.className = "browser-list-heading";
    heading.textContent = title;
    $("list-content").append(heading);
    if (title === "Discovered nodes") {
      const filters = document.createElement("div");
      filters.className = "browse-kind-filters";
      filters.setAttribute("role", "group");
      filters.setAttribute("aria-label", "Show discovered services");
      for (const item of browseKinds) {
        const toggle = document.createElement("button");
        toggle.type = "button";
        toggle.className =
          "browse-kind-filter entry-" +
          { lxmf: "station", node: "nomadnet", nomadpl: "nomadpl" }[item.kind];
        const enabled = selectedKinds.has(item.kind);
        toggle.setAttribute("aria-label", item.label);
        toggle.setAttribute("aria-pressed", String(enabled));
        toggle.title = `${enabled ? "Hide" : "Show"} ${item.label}`;
        toggle.innerHTML = serviceIcon(item.icon);
        toggle.onclick = () => {
          if (selectedKinds.has(item.kind)) selectedKinds.delete(item.kind);
          else selectedKinds.add(item.kind);
          try {
            saveBrowseKinds(localStorage, selectedKinds);
          } catch {
            /* Storage may be disabled. */
          }
          renderBrowseNodes();
          $("list-content")
            .querySelector(`[aria-label="${item.label}"]`)
            ?.focus();
        };
        filters.append(toggle);
      }
      heading.classList.add("browser-discovered-heading");
      heading.append(filters);
    }
    let count = 0;
    for (const entry of entries.filter((item) =>
      `${item.name} ${item.url}`.toLowerCase().includes(query),
    )) {
      const button = document.createElement("button");
      button.className = "browser-site";
      button.title = entry.url;
      const name = document.createElement("strong");
      name.textContent = entry.name
        .replace(/^nomadpl:\/\//, "")
        .replace(/\/$/, "")
        .replace(/[0-9a-f]{32}/gi, (hash) => hash.slice(0, 6) + "…");
      const address = document.createElement("small");
      const kind =
        entry.kind === "lxmf"
          ? "station"
          : entry.url.startsWith("nomadpl://")
            ? "nomadpl"
            : "nomadnet";
      button.classList.add("entry-" + kind);
      const selected = entry.url === state.history[state.index]?.url;
      button.classList.toggle("entry-selected", selected);
      button.setAttribute("aria-current", selected ? "page" : "false");
      address.className = "entry-kind";
      address.textContent = {
        station: "Station",
        nomadpl: "NomadPL",
        nomadnet: "NomadNet",
      }[kind];
      button.append(name, address);
      /** Open a conversation for a station or navigate to the selected site. */
      button.onclick = () =>
        kind === "station"
          ? onMessage(entry.address)
          : openBrowserURL(entry.url);
      $("list-content").append(button);
      count++;
    }
    if (!count) {
      const empty = document.createElement("p");
      empty.className = "browser-list-empty";
      empty.textContent = query
        ? "No matches"
        : title === "Bookmarks"
          ? "Use ☆ to save a page."
          : !selectedKinds.size
            ? "All service types are hidden."
            : "No matching services discovered yet.";
      $("list-content").append(empty);
    }
  }
}

/** Display a stored page using the appropriate native renderer or isolated frame. */
function paint(page) {
  $("browser-address").value = page.url;
  $("browser-identify").setAttribute(
    "aria-pressed",
    String(page.identify || false),
  );
  $("browser-document").dataset.source = "false";
  if (page.sourceView) {
    const pre = document.createElement("pre");
    pre.textContent = page.source;
    $("browser-document").replaceChildren(pre);
    $("browser-status").textContent = "Page source";
    updateButtons();
    return;
  }
  if (page.frame) {
    const frame = document.createElement("iframe");
    frame.title = "NomadPL page";
    frame.className = "nomadpl-frame";
    frame.setAttribute(
      "sandbox",
      "allow-scripts allow-forms allow-same-origin allow-downloads",
    );
    frameContext = {
      frame,
      owner: model.active.id,
      origin: new URL(page.frame).origin,
      id: crypto.randomUUID(),
      logicalHost: new URL(page.url).hostname,
      destination: new URL(page.resolved || page.url).hostname,
    };
    const context = frameContext;
    context.finishActivity = beginActivity("Loading NomadPL page");
    finishLoading = () => context.finishActivity();
    /** Wait briefly for the frame's navigation report before applying the fallback state. */
    frame.onload = () => {
      if (frameContext !== context || !frame.isConnected) return;
      context.finishActivity();
      context.loading = false;
      $("browser-stop").hidden = true;
      const loaded = Date.now();
      setTimeout(() => {
        /** Apply a load fallback only if the frame has not reported newer navigation. */

        if (
          frameContext !== context ||
          !frame.isConnected ||
          (context.reportAt && context.reportAt >= loaded - 1000)
        )
          return;
        context.unsynced = true;
        $("browser-status").textContent =
          "Navigation sync unavailable: this page may block scripts or have left NomadPL.";
        updateButtons();
      }, 1200);
    };
    page.frameRun = frameContext.id;
    page.navId = null;
    frame.src = page.frame;
    $("browser-document").replaceChildren(frame);
    $("browser-status").textContent = "Loading NomadPL page…";
    $("browser-stop").hidden = false;
    updateButtons();
    renderBrowseNodes();
    return;
  }
  try {
    renderMicron(
      $("browser-document"),
      page.source,
      (target, fields) => navigateLink(target, fields),
      (target, image) => loadMicronImage(page, target, image),
    );
  } catch (error) {
    $("browser-document").textContent = error.message;
    $("browser-status").textContent =
      "This page could not be rendered. View source is still available.";
    updateButtons();
    return;
  }
  $("browser-status").textContent = "";
  updateButtons();
  renderBrowseNodes();
}

/** Restore a valid history entry without mixing native and framed navigation. */
function showHistory(index) {
  const state = session();
  if (index < 0 || index >= state.history.length) return;
  leaveBrowser();
  const target = state.history[index];
  if (
    frameContext?.frame.isConnected &&
    target.frameRun === frameContext.id &&
    target.navId
  ) {
    frameContext.frame.contentWindow.postMessage(
      {
        type: "cixnet-history",
        channel: frameContext.channel,
        delta: index - state.index,
      },
      frameContext.origin,
    );
    return;
  }
  state.index = index;
  paint(target);
}

/** Scroll to a native page anchor while treating malformed escapes literally. */
function jump(anchor) {
  try {
    anchor = decodeURIComponent(anchor);
  } catch {
    /* Invalid percent escapes are literal anchors. */
  }
  const root = $("browser-document");
  const target = [...root.querySelectorAll("[data-micron-anchor]")].find(
    (item) => item.dataset.micronAnchor === anchor,
  );
  if (!anchor) root.scrollTop = 0;
  else if (target) {
    target.closest("details")?.setAttribute("open", "");
    target.scrollIntoView({ block: "start" });
  }
}

/** Handle in-page anchors and messaging links before opening a normal page. */
function navigateLink(target, fields = []) {
  if (target.startsWith("#")) {
    jump(target.slice(1));
    return;
  }
  const message = lxmfAddress(target);
  if (message) {
    onMessage(message);
    return;
  }
  const data = fields.length
    ? collectMicronFields($("browser-document"), fields)
    : null;
  openBrowserURL(target, data);
}

/** Start navigation and ignore results that belong to a superseded request. */
export async function openBrowserURL(
  url,
  data = null,
  replace = false,
  sourceView = false,
) {
  if (model.tab !== "browse" || !$("browser-document")) return;
  const recipient = lxmfAddress(url);
  if (recipient) {
    onMessage(recipient);
    return;
  }
  const navigationKey = JSON.stringify([
    model.active.id,
    url,
    data,
    sourceView,
  ]);
  if (pendingNavigation === navigationKey) return;
  leaveBrowser();
  pendingNavigation = navigationKey;
  const ticket = generation;
  const owner = model.active.id;
  const state = session();
  const base =
    state.history[state.index]?.resolved || state.history[state.index]?.url;
  const anchor = url.includes("#") ? url.slice(url.indexOf("#") + 1) : null;
  document.querySelector(".app-body").classList.add("mobile-content");
  $("browser-stop").hidden = false;
  $("browser-status").textContent = "Finding node…";
  const endActivity = beginActivity("Loading page");
  const finish = () => {
    endActivity();
    if (ticket === generation) pendingNavigation = null;
  };
  finishLoading = finish;
  /** Check that this request still belongs to the visible identity and navigation. */
  const active = () =>
    ticket === generation &&
    model.active?.id === owner &&
    model.tab === "browse";
  try {
    const choice = await api("browser/identify", { owner, url, base });
    if (!active()) return;
    const identify = choice.identify;
    $("browser-identify").setAttribute("aria-pressed", String(identify));
    const job = await api("browser/open", {
      owner,
      url,
      base,
      data,
      identify,
      source: sourceView,
    });
    if (!active()) {
      api("browser/cancel", { owner, id: job.id }).catch(() => {
        /** Ignore cancellation failure once a superseding navigation owns the display. */
      });
      return;
    }
    currentJob = { owner, id: job.id };
    /** Read the page job's progress until it completes, fails or is replaced. */
    const poll = async () => {
      if (!active()) return;
      try {
        const result = await api("browser/status", { owner, id: job.id });
        if (!active()) return;
        if (result.phase === "done") {
          if (result.download) {
            const response = await apiResponse("browser/download", {
              owner,
              id: job.id,
            });
            if (!response.ok)
              throw new Error("Could not retrieve the downloaded file");
            if (!active()) return;
            const blob = await response.blob();
            const url = URL.createObjectURL(blob);
            const link = document.createElement("a");
            link.href = url;
            link.download = result.download.name;
            link.click();
            setTimeout(() => URL.revokeObjectURL(url), 30000);
            currentJob = null;
            $("browser-stop").hidden = true;
            finish();
            $("browser-status").textContent =
              `Downloaded ${result.download.name} · ${result.download.size.toLocaleString()} bytes`;
            return;
          }
          const page = {
            url: result.requested_url || result.url,
            resolved: result.url,
            source: result.source,
            frame: result.frame,
            sourceView,
            identify,
            identityURL: choice.url,
          };
          if (replace && state.index >= 0) state.history[state.index] = page;
          else {
            state.history.splice(state.index + 1);
            state.history.push(page);
            if (state.history.length > 30) state.history.shift();
            state.index = state.history.length - 1;
          }
          currentJob = null;
          $("browser-stop").hidden = true;
          finish();
          paint(page);
          if (anchor !== null) jump(anchor);
          return;
        }
        if (["error", "cancelled"].includes(result.phase))
          throw new Error(result.error || "Request cancelled");
        $("browser-status").textContent =
          `${{ finding_path: "Finding route", connecting: "Establishing encrypted link", requesting: "Waiting for page", receiving: "Receiving page" }[result.phase] || result.phase}… ${result.progress ? `${Math.round(result.progress * 100)}%` : ""}`;
        timer = setTimeout(poll, 700);
      } catch (error) {
        if (active()) {
          $("browser-status").textContent = error.message;
          $("browser-stop").hidden = true;
          finish();
          currentJob = null;
        }
      }
    };
    await poll();
  } catch (error) {
    if (active()) {
      $("browser-status").textContent = error.message;
      $("browser-stop").hidden = true;
      finish();
    }
  }
}

/** Save or remove the visible page in the current identity's bookmarks. */
async function bookmarkCurrent() {
  const state = session();
  const page = state.history[state.index];
  if (!page) return;
  const owner = model.active.id;
  const existing = state.bookmarks.find((item) => item.url === page.url);
  const name =
    existing?.name ||
    page.title?.slice(0, 100) ||
    $("browser-document")
      .querySelector("h1,h2,h3,summary")
      ?.textContent.slice(0, 100) ||
    page.url.slice(0, 100);
  try {
    const result = await api("browser/bookmark", {
      owner,
      url: page.url,
      name,
      remove: Boolean(existing),
    });
    state.bookmarks = result.bookmarks;
    if (model.active?.id === owner && model.tab === "browse") {
      renderBrowseNodes();
      updateButtons();
    }
  } catch (error) {
    showToast(error.message);
  }
}

/** Show saved DNS suffixes and discovered authority candidates. */
export async function renderDNS(address = null) {
  leaveBrowser();
  $("browser-stop").hidden = true;
  const owner = model.active.id;
  try {
    const result = await api("dns/list", { owner });
    if (owner !== model.active?.id || model.tab !== "browse") return;
    const root = $("browser-document");
    root.innerHTML = `<h1>Name servers</h1><p>Saved servers apply to all identities on this client and survive restarts. A local suffix selects a server: home.cix asks the .cix server for home. For a record named home.ret, use home.ret.cix.</p><form id="dns-form"><label>Server destination<input id="dns-address" required pattern="[a-fA-F0-9]{32}" maxlength="32"></label><label>Local suffix<input id="dns-suffix" value=".cix" required maxlength="33"></label><button class="primary">Save DNS server</button></form><h2>Saved servers</h2><div id="dns-saved"></div><h2>Discovered servers</h2><div id="dns-discovered"></div><p>Discovery listens for announcements; servers are never selected automatically.</p>`;
    if (address) {
      $("dns-address").value = address;
      $("dns-suffix").focus();
    }
    for (const server of result.saved) {
      const row = document.createElement("p");
      const remove = document.createElement("button");
      row.textContent = `.${server.suffix} → ${server.address} `;
      remove.textContent = "Remove";
      /** Remove this explicitly selected DNS authority suffix. */
      remove.onclick = async () => {
        try {
          await api("dns/save", { owner, suffix: server.suffix, remove: true });
          await renderDNS();
        } catch (error) {
          showToast(error.message);
        }
      };
      row.append(remove);
      $("dns-saved").append(row);
    }
    for (const server of result.discovered) {
      const button = document.createElement("button");
      button.textContent = `${server.name} · ${server.address}`;
      /** Copy a discovered authority address into the form without trusting it automatically. */
      button.onclick = () => {
        $("dns-address").value = server.address;
        $("dns-suffix").focus();
      };
      $("dns-discovered").append(button);
    }
    if (!result.discovered.length)
      $("dns-discovered").textContent =
        "No DNS announcements yet. You can add a known server address.";
    /** Save the user's explicit suffix and authority selection. */
    $("dns-form").onsubmit = async (event) => {
      event.preventDefault();
      try {
        await api("dns/save", {
          owner,
          address: $("dns-address").value.trim(),
          suffix: $("dns-suffix").value.trim(),
        });
        await renderDNS();
        showToast("DNS server saved");
      } catch (error) {
        showToast(error.message);
      }
    };
  } catch (error) {
    showToast(error.message);
  }
}

/** Toggle the destination list using the layout appropriate to the screen width. */
function toggleSidebar() {
  const body = document.querySelector(".app-body");
  if (window.matchMedia("(max-width: 760px)").matches) {
    body.classList.remove("sidebar-collapsed");
    body.classList.toggle("mobile-content");
  } else {
    body.classList.toggle("sidebar-collapsed");
    try {
      localStorage.setItem(
        "cixnet-sidebar-hidden",
        String(body.classList.contains("sidebar-collapsed")),
      );
    } catch {
      /* Optional preference. */
    }
  }
}

/** Only the active, isolated frame can report its own navigation. */
function receiveFrameNavigation(event) {
  const context = frameContext;
  if (
    !context ||
    !context.frame.isConnected ||
    event.source !== context.frame.contentWindow ||
    event.origin !== context.origin ||
    model.active?.id !== context.owner ||
    model.tab !== "browse"
  )
    return;
  const data = event.data;
  if (
    !data ||
    typeof data !== "object" ||
    typeof data.channel !== "string" ||
    !/^\/\.cixnet-navigation-[a-f0-9]{32}\.js$/.test(data.channel)
  )
    return;
  if (context.channel && context.channel !== data.channel) return;
  context.channel = data.channel;
  if (data.type === "cixnet-loading") {
    if (!context.loading) {
      context.finishActivity();
      context.finishActivity = beginActivity("Loading NomadPL page");
      context.loading = true;
    }
    $("browser-status").textContent = "Waiting for NomadPL page…";
    $("browser-stop").hidden = false;
    return;
  }
  if (data.type === "cixnet-loaded") {
    context.finishActivity();
    context.loading = false;
    $("browser-status").textContent = "";
    $("browser-stop").hidden = true;
    return;
  }
  if (data.type === "cixnet-open") {
    if (typeof data.href !== "string" || data.href.length > 2048) return;
    const recipient = lxmfAddress(data.href);
    if (recipient) onMessage(recipient);
    else if (data.href.startsWith("nomadpl://")) openBrowserURL(data.href);
    return;
  }

  if (
    data.type !== "cixnet-navigation" ||
    typeof data.href !== "string" ||
    data.href.length > 8192 ||
    typeof data.id !== "string" ||
    data.id.length > 100
  )
    return;
  let actual;
  try {
    actual = new URL(data.href);
  } catch {
    return;
  }
  if (actual.origin !== context.origin) return;
  context.reportAt = Date.now();
  context.unsynced = false;
  let sourceURL;
  try {
    sourceURL = new URL(data.sourceHref || data.href);
  } catch {
    return;
  }
  if (sourceURL.origin !== context.origin) return;
  const sourceResolved = `nomadpl://${context.destination}${sourceURL.pathname}${sourceURL.search}`;
  const path = actual.pathname + actual.search + actual.hash;
  const resolved = `nomadpl://${context.destination}${path}`;
  const state = session();
  const current = state.history[state.index];
  if (!current?.frame || current.frameRun !== context.id) return;
  const page = {
    ...current,
    url: `nomadpl://${context.logicalHost}${path}`,
    resolved,
    frame: actual.href,
    navId: data.id,
    sourceResolved,
    sourceId:
      typeof data.sourceId === "string" && /^[a-f0-9]{32}$/.test(data.sourceId)
        ? data.sourceId
        : undefined,
    title: typeof data.title === "string" ? data.title.slice(0, 100) : "",
  };
  const prior = state.history.findIndex(
    (entry) =>
      entry.frameRun === context.id &&
      entry.navId === data.id &&
      entry.resolved === resolved,
  );
  if (data.mode === "replace") {
    state.history[state.index] = page;
  } else if (prior >= 0) {
    state.index = prior;
    state.history[prior] = page;
  } else if (
    !current.navId ||
    (current.navId === data.id && current.resolved === resolved)
  )
    state.history[state.index] = page;
  else {
    state.history.splice(state.index + 1);
    state.history.push(page);
    if (state.history.length > 30) state.history.shift();
    state.index = state.history.length - 1;
  }
  $("browser-address").value = page.url;
  $("browser-status").textContent = "";
  updateButtons();
  renderBrowseNodes();
}
