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
