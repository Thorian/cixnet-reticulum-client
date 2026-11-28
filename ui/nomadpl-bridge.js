(() => {
  /** Install a frame-local navigation bridge without exposing the client's private APIs. */

  const script = document.currentScript;
  const parentOrigin = script.dataset.parent;
  const channel = script.dataset.channel;
  const sourceHref = location.href;
  const sourceId = script.dataset.source;
  const key = "__cixnetNavigation";
  /** Generate a browser-history identifier that is unique to this frame session. */
  const id = () => crypto.randomUUID();
  const downloads = new Set();
  const sendDownload = (type, details) =>
    parent.postMessage({ type, channel, ...details }, parentOrigin);
  async function downloadFile(href, suggestedName) {
    if (downloads.has(href)) return;
    const url = new URL(href, location.href);
    if (
      url.origin !== location.origin ||
      !["http:", "blob:"].includes(url.protocol)
    )
      return;
    downloads.add(href);
    const name =
      suggestedName ||
      decodeURIComponent(url.pathname.split("/").pop()) ||
      "download";
    const abort = new AbortController();
    const deadline = setTimeout(() => abort.abort(), 600000);
    sendDownload("cixnet-download-progress", { name, received: 0, total: 0 });
    try {
      const response = await fetch(url.href, { signal: abort.signal });
      if (!response.ok) throw new Error(`Download failed (${response.status})`);
      const total = Number(response.headers.get("content-length")) || 0;
      if (total > 64 * 1024 * 1024) throw new Error("Download exceeds 64 MB");
      const reader = response.body.getReader();
      const chunks = [];
      let received = 0;
      for (;;) {
        const next = await reader.read();
        if (next.done) break;
        received += next.value.byteLength;
        if (received > 64 * 1024 * 1024) {
          await reader.cancel();
          throw new Error("Download exceeds 64 MB");
        }
        chunks.push(next.value);
        sendDownload("cixnet-download-progress", { name, received, total });
      }
      const blob = new Blob(chunks, {
        type:
          response.headers.get("content-type") || "application/octet-stream",
      });
      sendDownload("cixnet-download-ready", { name, blob });
    } catch (error) {
      sendDownload("cixnet-download-error", {
        error:
          error.name === "AbortError" ? "Download timed out" : error.message,
      });
    } finally {
      clearTimeout(deadline);
      downloads.delete(href);
    }
  }
  const isDownload = (link) =>
    link.hasAttribute("download") ||
    /\.(apk|zip|pdf|epub|gz|7z)(?:[?#]|$)/i.test(link.href);
  document.addEventListener("click", (event) => {
    const link = event.target.closest?.("a[href]");
    if (!link || event.defaultPrevented || !isDownload(link)) return;
    const target = new URL(link.href, location.href);
    if (target.origin !== location.origin) return;
    event.preventDefault();
    downloadFile(link.href, link.download);
  });
  // Blob links created by page scripts are often clicked before they enter the DOM.
  if (typeof HTMLAnchorElement !== "undefined") {
    const click = HTMLAnchorElement.prototype.click;
    HTMLAnchorElement.prototype.click = function () {
      if (
        isDownload(this) &&
        new URL(this.href, location.href).origin === location.origin
      )
        downloadFile(this.href, this.download);
      else click.call(this);
    };
  }
  document.addEventListener("contextmenu", (event) => {
    if (event.target.tagName !== "IMG") return;
    event.preventDefault();
    const image = event.target;
    const dialog = document.createElement("dialog");
    const save = document.createElement("button");
    save.textContent = "Save photo";
    save.onclick = () => {
      dialog.close();
      downloadFile(image.currentSrc || image.src, "");
    };
    const cancel = document.createElement("button");
    cancel.textContent = "Cancel";
    cancel.onclick = () => dialog.close();
    dialog.onclose = () => dialog.remove();
    dialog.append(save, cancel);
    document.body.append(dialog);
    dialog.showModal();
  });
  /** Preserve page-owned history state while adding the bridge's navigation identifier. */
  const stateWithId = (state, fresh = false) => ({
    ...(state && typeof state === "object" ? state : {}),
    [key]: fresh ? id() : state?.[key] || id(),
  });
  const originalPush = history.pushState.bind(history);
  const originalReplace = history.replaceState.bind(history);
  originalReplace(stateWithId(history.state), "");
  /** Report this frame's current navigation to the expected parent origin and channel. */
  const report = (mode = "navigate") =>
    parent.postMessage(
      {
        type: "cixnet-navigation",
        mode,
        channel,
        href: location.href,
        sourceHref,
        sourceId,
        id: history.state?.[key],
        title: document.title,
      },
      parentOrigin,
    );
  /** Preserve normal page history and notify the parent about the new entry. */
  history.pushState = (state, title, url) => {
    originalPush(stateWithId(state, true), title, url);
    report();
  };
  /** Keep the current navigation identifier when the page replaces its state. */
  history.replaceState = (state, title, url) => {
    const next = stateWithId(state);
    next[key] = history.state?.[key] || next[key];
    originalReplace(next, title, url);
    report("replace");
  };
  addEventListener("popstate", () => report());
  addEventListener("hashchange", () => report());
  addEventListener("pageshow", () => report());
  addEventListener("message", (event) => {
    /** Accept bounded history commands only from the expected parent window. */

    if (
      event.source !== parent ||
      event.origin !== parentOrigin ||
      event.data?.channel !== channel
    )
      return;
    if (event.data.type === "cixnet-stop") {
      window.stop();
      pendingNavigation = null;
      loadingReport("cixnet-loaded");
      return;
    }
    if (
      event.data.type === "cixnet-history" &&
      Number.isInteger(event.data.delta) &&
      Math.abs(event.data.delta) <= 30
    )
      history.go(event.data.delta);
  });
  document.addEventListener("click", (event) => {
    /** Hand network and messaging links to the client instead of the iframe. */

    const link = event.target.closest?.("a[href]");
    const raw = link?.getAttribute("href")?.trim() || "";
    const messaging =
      /^lxmf(?:\.delivery)?@[0-9a-f]{32}$/i.test(raw) || /^lxmf:/i.test(raw);
    if (link && (link.href.startsWith("nomadpl://") || messaging)) {
      event.preventDefault();
      parent.postMessage(
        { type: "cixnet-open", channel, href: messaging ? raw : link.href },
        parentOrigin,
      );
    }
  });
  let pendingNavigation = null;
  const loadingReport = (type) =>
    parent.postMessage({ type, channel }, parentOrigin);
  // Bubble listeners leave page-owned handlers free to cancel or replace navigation.
  const beginNavigation = (event, target) => {
    if (event.defaultPrevented) return;
    if (pendingNavigation === target) {
      event.preventDefault();
      return;
    }
    pendingNavigation = target;
    loadingReport("cixnet-loading");
  };
  document.addEventListener("click", (event) => {
    if (
      event.button !== 0 ||
      event.ctrlKey ||
      event.metaKey ||
      event.shiftKey ||
      event.altKey
    )
      return;
    const link = event.target.closest?.("a[href]");
    if (!link || link.download || (link.target && link.target !== "_self"))
      return;
    let next;
    try {
      next = new URL(link.href, location.href);
    } catch {
      return;
    }
    const current = new URL(location.href);
    if (
      next.origin !== current.origin ||
      (next.pathname === current.pathname && next.search === current.search)
    )
      return;
    beginNavigation(event, next.href);
  });
  document.addEventListener("submit", (event) => {
    const form = event.target;
    const target = event.submitter?.formTarget || form.target;
    if (target && target !== "_self") return;
    beginNavigation(event, form);
  });
  addEventListener("pageshow", () => {
    pendingNavigation = null;
    loadingReport("cixnet-loaded");
  });
  // Dynamic pages can submit work without navigating the frame.
  let pendingRequests = 0;
  const requestStarted = () => {
    if (pendingRequests++ === 0) loadingReport("cixnet-loading");
  };
  const requestFinished = () => {
    if (--pendingRequests === 0 && pendingNavigation === null)
      loadingReport("cixnet-loaded");
  };
  if (typeof window !== "undefined" && window.fetch) {
    const originalFetch = window.fetch;
    window.fetch = async function (...args) {
      requestStarted();
      try {
        return await originalFetch.apply(this, args);
      } finally {
        requestFinished();
      }
    };
  }
  if (typeof XMLHttpRequest !== "undefined") {
    const originalSend = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.send = function (...args) {
      requestStarted();
      let finished = false;
      const finish = () => {
        if (finished) return;
        finished = true;
        this.removeEventListener("loadend", finish);
        requestFinished();
      };
      this.addEventListener("loadend", finish);
      try {
        return originalSend.apply(this, args);
      } catch (error) {
        finish();
        throw error;
      }
    };
  }
  report();
})();
