/** Pure rendering tests complement the real-process Python integration tests. */
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { escapeHTML, model, peerName } from "../ui/core.js";
import { iconMarkup, loadIcons } from "../ui/icons.js";

// Load the bundled catalog without depending on an HTTP server or the internet.
const originalFetch = globalThis.fetch;
/** Provide the bundled icon catalog without making an external network request. */
globalThis.fetch = async () => ({
  ok: true,
  json: /** Decode the local icon catalog used by avatar-rendering fixtures. */ async () =>
    JSON.parse(
      await readFile(
        new URL("../ui/vendor/mdi/icons.json", import.meta.url),
        "utf8",
      ),
    ),
});
await loadIcons();
globalThis.fetch = originalFetch;

test("settings startup handlers have matching controls in the shipped page", async () => {
  const page = await readFile(
    new URL("../ui/index.html", import.meta.url),
    "utf8",
  );
  const settings = await readFile(
    new URL("../ui/settings.js", import.meta.url),
    "utf8",
  );
  for (const [, id] of settings.matchAll(/\$\("([\w-]+)"\)/g)) {
    assert.ok(page.includes(`id="${id}"`), `Missing settings control: ${id}`);
  }
});

test("untrusted names cannot break out of HTML text", () => {
  const escaped = escapeHTML("<img src=x onerror=\"run()\"> & 'quoted'");
  assert.equal(
    escaped,
    "&lt;img src=x onerror=&quot;run()&quot;&gt; &amp; &#39;quoted&#39;",
  );
});

test("avatar colors and unknown icon names cannot inject markup", () => {
  const markup = iconMarkup({
    icon: "<script>run()</script>",
    foreground: '" onload="run()',
    background: "url(https://unrelated.example)",
  });
  assert.ok(!markup.includes("<script>"));
  assert.ok(!markup.includes("onload"));
  assert.ok(!markup.includes("unrelated.example"));
  assert.ok(markup.includes('fill="#70e7a3"'));
  assert.ok(markup.includes('fill="#2e503c"'));
});

test("received RGB appearance renders with a bundled glyph", () => {
  const markup = iconMarkup({
    icon: "pine-tree",
    foreground: "ffffff",
    background: "123456",
  });
  assert.ok(markup.includes('fill="#ffffff"'));
  assert.ok(markup.includes('fill="#123456"'));
  assert.ok(!markup.includes("http"));
  assert.ok(!markup.includes(">•<"));
});

test("contact names use current announces with an address fallback", () => {
  const address = "0123456789abcdef0123456789abcdef";
  model.network.announces = [];
  assert.equal(peerName(address), "0123456789ab…");
  model.network.announces = [{ address, display_name: "Field station" }];
  assert.equal(peerName(address), "Field station");
});

import { connectionStatus } from "../ui/connection-status.js";

test("connection status distinguishes test links, LAN peers, and server verification", () => {
  const running = { phase: "running", interfaces: [] };
  assert.equal(connectionStatus(running).connected, false);
  assert.equal(
    connectionStatus({
      ...running,
      interfaces: [{ type: "TCPServerInterface", online: true, peers: 9 }],
    }).connected,
    false,
  );
  assert.equal(
    connectionStatus({
      ...running,
      interfaces: [{ type: "AutoInterface", online: true, peers: 1 }],
    }).label,
    "LAN peers found · server unverified",
  );
  assert.equal(
    connectionStatus({
      ...running,
      interfaces: [
        {
          type: "TCPClientInterface",
          online: true,
          name: "Local test connection",
        },
      ],
    }).label,
    "Local test link active",
  );
  assert.equal(
    connectionStatus({
      ...running,
      interfaces: [
        {
          type: "TCPClientInterface",
          online: false,
          name: "Local test connection",
        },
      ],
    }).connected,
    false,
  );
  assert.equal(
    connectionStatus({
      ...running,
      interfaces: [
        { type: "TCPClientInterface", online: true, name: "Gateway" },
      ],
    }).label,
    "TCP link active · server unverified",
  );
  assert.equal(
    connectionStatus({ ...running, phase: "error" }).connected,
    false,
  );
});

test("TCP peers count on both accepted and outgoing connections without counting the listener", async () => {
  const { connectionCounts } = await import("../ui/connection-status.js");
  assert.deepEqual(
    connectionCounts({
      interfaces: [
        { type: "TCPServerInterface", online: true, peers: 0 },
        { type: "TCPClientInterface", online: true, peers: 0 },
        { type: "TCPClientInterface", online: false, peers: 0 },
        { type: "AutoInterface", online: true, peers: 2 },
      ],
    }),
    { lan: 2, tcp: 1, total: 3 },
  );
});

import {
  fittedDimensions,
  validateSelection,
  formatSize,
} from "../ui/attachments-ui.js";
test("image reduction fits the longest edge without stretching or upscaling", () => {
  assert.deepEqual(fittedDimensions(4000, 2000, 1280), {
    width: 1280,
    height: 640,
  });
  assert.deepEqual(fittedDimensions(1000, 4000, 640), {
    width: 160,
    height: 640,
  });
  assert.deepEqual(fittedDimensions(200, 100, 640), {
    width: 200,
    height: 100,
  });
});
test("attachment picker rejects oversized batches and shows useful sizes", () => {
  assert.throws(
    /** Submit an oversized attachment to check that selection validation rejects it. */ () =>
      validateSelection([{ size: 8 * 1024 * 1024 + 1 }]),
  );
  assert.throws(
    /** Submit too many files to exercise the attachment-count limit. */ () =>
      validateSelection(Array(9).fill({ size: 0 })),
  );
  assert.doesNotThrow(
    /** Accept a selection exactly at the supported byte limit. */ () =>
      validateSelection([{ size: 8 * 1024 * 1024 }]),
  );
  assert.equal(formatSize(2048), "2.0 KiB");
});

import { stopCamera } from "../ui/camera-ui.js";
test("closing or changing camera stops every video track", () => {
  let stopped = 0;
  stopCamera({
    getTracks:
      /** Provide controllable camera tracks so cleanup can be observed. */ () => [
        {
          stop: /** Provide controllable camera tracks so cleanup can be observed. */ () =>
            stopped++,
        },
        {
          stop: /** Provide controllable camera tracks so cleanup can be observed. */ () =>
            stopped++,
        },
      ],
  });
  assert.equal(stopped, 2);
  assert.doesNotThrow(
    /** Check that camera cleanup also accepts an absent stream. */ () =>
      stopCamera(null),
  );
});

import { api } from "../ui/core.js";
import { refreshHistory } from "../ui/messaging-ui.js";
test("an open page renews its token after service restart and retries the rejected history request once", async () => {
  const savedFetch = globalThis.fetch;
  const calls = [];
  model.token = "expired-token";
  model.accessKey = "private-test-key";
  /** Simulate token renewal and record the credentials used for each API attempt. */
  globalThis.fetch = async (url, options = {}) => {
    calls.push({
      url,
      token: options.headers?.["X-Cixnet-Token"],
      authorization: options.headers?.Authorization,
    });
    if (url === "/api/state")
      return {
        ok: true,
        status: 200,
        json: /** Return the renewed mutation token from the fixture's state endpoint. */ async () => ({
          token: "new-token",
        }),
      };
    if (options.headers["X-Cixnet-Token"] === "expired-token")
      return { ok: false, status: 403 };
    return {
      ok: true,
      status: 200,
      json: /** Return saved message data after the fixture accepts the renewed token. */ async () => ({
        messages: [{ id: "persisted" }],
      }),
    };
  };
  try {
    const result = await api("messaging/history", { owner: "owner" });
    assert.equal(result.messages[0].id, "persisted");
    assert.deepEqual(
      calls.map(
        /** Extract the requested endpoint sequence for the token-retry assertion. */ (
          call,
        ) => call.url,
      ),
      ["/api/messaging/history", "/api/state", "/api/messaging/history"],
    );
    assert.equal(calls[2].token, "new-token");
    assert.ok(
      calls.every((call) => call.authorization === "Bearer private-test-key"),
    );
    model.accessKey = null;
  } finally {
    globalThis.fetch = savedFetch;
  }
});
test("failed history requests preserve the displayed saved messages and are not replayed on network errors", async () => {
  const savedFetch = globalThis.fetch;
  let calls = 0;
  model.active = { id: "owner" };
  model.messages = [{ id: "saved-message" }];
  /** Simulate a receiver outage while counting attempted history requests. */
  globalThis.fetch = async () => {
    calls++;
    throw new Error("Service offline");
  };
  try {
    await assert.rejects(refreshHistory(), /Service offline/);
    assert.equal(model.messages[0].id, "saved-message");
    assert.equal(calls, 1);
  } finally {
    globalThis.fetch = savedFetch;
    model.active = null;
  }
});
test("a still-rejected request is not retried indefinitely", async () => {
  const savedFetch = globalThis.fetch;
  let calls = 0;
  /** Return a fresh token followed by a still-rejected mutation response. */
  globalThis.fetch = async (url) => {
    calls++;
    return url === "/api/state"
      ? {
          ok: true,
          status: 200,
          json: /** Provide the replacement token used in the bounded retry test. */ async () => ({
            token: "fresh",
          }),
        }
      : {
          ok: false,
          status: 403,
          json: /** Return the explicit rejection body after the retry limit is reached. */ async () => ({
            error: "Request rejected",
          }),
        };
  };
  try {
    await assert.rejects(
      api("messaging/history", { owner: "owner" }),
      /Request rejected/,
    );
    assert.equal(calls, 3);
  } finally {
    globalThis.fetch = savedFetch;
  }
});

test("saved contact names remain available after live announces are cleared", () => {
  const address = "fedcba9876543210fedcba9876543210";
  model.network.announces = [];
  model.peerNames = { [address]: "Saved station" };
  assert.equal(peerName(address), "Saved station");
  model.network.announces = [{ address, display_name: "Updated station" }];
  assert.equal(peerName(address), "Updated station");
  model.peerNames = {};
  model.network.announces = [];
});

import { parseMicron, micronColor } from "../ui/micron.js";
test("native Micron formatting persists across lines and resets explicitly", () => {
  const page = parseMicron(
    ">Heading\n`!Bold\nstill bold`! normal\n`*Italic`* `_Underlined`_\n`F123Color`f reset\n`cCentered\nnext line\n``Reset",
  );
  assert.equal(page.blocks[0].type, "heading");
  assert.equal(page.blocks[0].anchor, "heading");
  assert.equal(page.blocks[2].inlines[0].style.bold, true);
  assert.equal(page.blocks[2].inlines[1].style.bold, false);
  assert.equal(page.blocks[4].inlines[0].style.fg, "#123");
  assert.equal(page.blocks[6].align, "center");
  assert.equal(page.blocks[7].align, "left");
});
test("Micron links, form fields, literal blocks, tables, and hostile text are data", () => {
  const page = parseMicron(
    "#!bg=123\n# comment\n`[Send`/page/result.mu`*|mode=test]\n`<!24|password`secret>\n`<?|choice|yes|*`Yes>\n`=\n>not a heading <script>\n`=\n`t\n| Name | State |\n| --- | --- |\n| ciXnet | Ready |\n`t\nHTML: <img src=x onerror=run()>",
  );
  assert.equal(page.bg, "#123");
  assert.equal(page.blocks[0].inlines[0].target, "/page/result.mu");
  assert.deepEqual(page.blocks[0].inlines[0].fields, ["*", "mode=test"]);
  assert.equal(page.blocks[1].inlines[0].kind, "password");
  assert.equal(page.blocks[2].inlines[0].checked, true);
  assert.equal(page.blocks[3].type, "pre");
  assert.ok(page.blocks[3].text.includes("<script>"));
  assert.equal(page.blocks[4].type, "table");
  assert.equal(page.blocks[4].header, true);
  assert.equal(
    page.blocks[5].inlines[0].text,
    "HTML: <img src=x onerror=run()>",
  );
  assert.equal(micronColor("url(evil)"), null);
});
test("Micron section depth resets, escaped commands stay text, and headings can fold", () => {
  const page = parseMicron(
    ">>>Deep\ninside\n<Outside\n\\>literal\n`->Closed\nfolded content\n>Next",
  );
  assert.equal(page.blocks[1].depth, 3);
  assert.equal(page.blocks[2].depth, 0);
  assert.equal(page.blocks[3].type, "line");
  assert.equal(page.blocks[3].inlines[0].text, ">literal");
  assert.equal(page.blocks[4].folded, true);
});

test("announce ages use seconds for five minutes then local time", async () => {
  const { announceTime } = await import("../ui/announce-time.js");
  assert.equal(announceTime(1000, 1000), "0s ago");
  assert.equal(announceTime(1000, 1299.9), "299s ago");
  assert.equal(announceTime(1001, 1000), "0s ago");
  assert.equal(
    announceTime(1000, 1300),
    new Date(1000000).toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
    }),
  );
});

test("HTML navigation bridge reports state and rejects unrelated history commands", async () => {
  const { readFile } = await import("node:fs/promises");
  const { runInNewContext } = await import("node:vm");
  const source = await readFile(
    new URL("../ui/nomadpl-bridge.js", import.meta.url),
    "utf8",
  );
  const listeners = {};
  const reports = [];
  const moves = [];
  const parent = {
    postMessage:
      /** Collect the navigation reports emitted by the bridge under test. */ (
        data,
        origin,
      ) => reports.push({ data, origin }),
  };
  const history = {
    state: null,
    pushState(state) {
      /** Save the fixture's history state when a new entry is pushed. */
      this.state = state;
    },
    replaceState(state) {
      /** Replace the fixture's current history state in place. */
      this.state = state;
    },
    go(delta) {
      /** Record the requested history offset without running a real browser. */
      moves.push(delta);
    },
  };
  let count = 0;
  runInNewContext(source, {
    document: {
      currentScript: {
        dataset: { parent: "http://127.0.0.1:8765", channel: "test" },
      },
      title: "Guide",
      addEventListener() {
        /** Provide deterministic identifiers and event listeners to the frame fixture. */
      },
    },
    location: { href: "http://site.localhost:8000/guide/?a=1#part" },
    parent,
    history,
    crypto: {
      randomUUID:
        /** Provide deterministic identifiers and event listeners to the frame fixture. */ () =>
          String(++count),
    },
    addEventListener: (name, fn) => {
      /** Provide deterministic identifiers and event listeners to the frame fixture. */
      listeners[name] = fn;
    },
  });
  assert.equal(
    reports[0].data.href,
    "http://site.localhost:8000/guide/?a=1#part",
  );
  assert.equal(reports[0].origin, "http://127.0.0.1:8765");
  history.pushState({}, "", "/other");
  assert.notEqual(reports[0].data.id, reports[1].data.id);
  listeners.message({
    source: parent,
    origin: "http://evil.example",
    data: { type: "cixnet-history", channel: "test", delta: -1 },
  });
  assert.equal(moves.length, 0);
  listeners.message({
    source: parent,
    origin: "http://127.0.0.1:8765",
    data: { type: "cixnet-history", channel: "test", delta: -1 },
  });
  assert.deepEqual(moves, [-1]);
});

test("camera capture reviews before attaching, retakes and stops the stream", async () => {
  const { openCamera } = await import("../ui/camera-ui.js");
  const previousDocument = globalThis.document;
  const navigatorDescriptor = Object.getOwnPropertyDescriptor(
    globalThis,
    "navigator",
  );
  let stopped = 0;
  let attached = null;
  const controls = new Map();
  const control = (selector) => {
    if (!controls.has(selector))
      controls.set(selector, {
        hidden: false,
        value: "user",
        removeAttribute(name) {
          delete this[name];
        },
      });
    return controls.get(selector);
  };
  Object.assign(control("video"), {
    videoWidth: 640,
    videoHeight: 480,
    play: async () => {},
  });
  const dialog = {
    open: false,
    querySelector: control,
    showModal() {
      this.open = true;
    },
    close() {
      this.open = false;
      this.onclose();
    },
    remove() {},
  };
  globalThis.document = {
    body: { append() {} },
    createElement: (name) =>
      name === "dialog"
        ? dialog
        : {
            getContext: () => ({ drawImage() {} }),
            toBlob: (done) => done(new Blob(["photo"], { type: "image/jpeg" })),
          },
  };
  Object.defineProperty(globalThis, "navigator", {
    configurable: true,
    value: {
      mediaDevices: {
        getUserMedia: async () => ({
          getTracks: () => [
            {
              stop() {
                stopped++;
              },
            },
          ],
        }),
      },
    },
  });
  try {
    await openCamera(
      (file) => {
        attached = file;
      },
      () => {},
    );
    await control(".camera-shutter").onclick();
    assert.equal(attached, null);
    assert.equal(control(".camera-review").hidden, false);
    assert.equal(control("video").srcObject, null);
    assert.equal(stopped, 1);
    control(".camera-retake").onclick();
    await new Promise(setImmediate);
    assert.equal(control("video").hidden, false);
    await control(".camera-shutter").onclick();
    control(".camera-use").onclick();
    assert.equal(attached.type, "image/jpeg");
    assert.equal(dialog.open, false);
    assert.equal(control("video").srcObject, null);
  } finally {
    globalThis.document = previousDocument;
    if (navigatorDescriptor)
      Object.defineProperty(globalThis, "navigator", navigatorDescriptor);
    else delete globalThis.navigator;
  }
});

test("delivery marks distinguish relay storage from recipient receipt without claiming read status", async () => {
  const { deliveryStatus } = await import("../ui/delivery-status.js");
  assert.equal(deliveryStatus("stored_on_relays").mark, "✓");
  assert.equal(deliveryStatus("delivered").mark, "✓✓");
  assert.notEqual(
    deliveryStatus("stored_on_relays").tone,
    deliveryStatus("delivered").tone,
  );
  assert.match(deliveryStatus("delivered").label, /recipient client/);
  assert.equal(deliveryStatus("failed").tone, "failed");
});

test("announced contacts and DNS authorities expose the matching direct action", async () => {
  const { initAnnounces, renderAnnounces } = await import(
    "../ui/network-ui.js"
  );
  const savedDocument = globalThis.document;
  const previousNetwork = model.network;
  const classes = { add() {}, toggle() {}, remove() {} };
  const element = () => ({
    children: [],
    dataset: {},
    classList: classes,
    setAttribute() {},
    querySelector() {
      return null;
    },
    get lastChild() {
      return this.children.at(-1);
    },
    insertBefore(child, sibling) {
      this.children.splice(this.children.indexOf(sibling), 0, child);
    },
    value: "",
    append(child) {
      this.children.push(child);
    },
    replaceChildren() {
      this.children = [];
    },
  });
  const list = element(),
    panel = element(),
    pre = element(),
    detail = element(),
    back = element();
  detail.querySelector = (selector) => (selector === "pre" ? pre : panel);
  const controls = {
    search: element(),
    "list-content": list,
    detail,
    "announce-back": back,
  };
  globalThis.document = {
    getElementById: (id) => controls[id],
    createElement: element,
    querySelector: () => ({ classList: classes }),
  };
  const calls = [];
  initAnnounces({
    onMessage: (address) => calls.push(["message", address]),
    onDNS: (address) => calls.push(["dns", address]),
  });
  try {
    for (const [kind, label] of [
      ["lxmf", "Message"],
      ["dns", "Add DNS server"],
    ]) {
      panel.children = [];
      model.network = {
        announces: [
          {
            kind,
            address: "a".repeat(32),
            identity: "b".repeat(32),
            received: 1,
            display_name: "Peer",
            data: "",
          },
        ],
      };
      renderAnnounces();
      list.children[1].onclick();
      assert.equal(panel.children[0].textContent, label);
      panel.children[0].onclick();
    }
    assert.deepEqual(calls, [
      ["message", "a".repeat(32)],
      ["dns", "a".repeat(32)],
    ]);
  } finally {
    globalThis.document = savedDocument;
    model.network = previousNetwork;
  }
});

test("conversation search finds older message text and previews that match", async () => {
  const { conversationMatches } = await import("../ui/conversation-search.js");
  const messages = [
    { id: "old", peer: "a", content: "Bring the antenna", timestamp: 1 },
    { id: "new", peer: "a", content: "Thanks", timestamp: 3 },
    { id: "other", peer: "b", content: "No match", timestamp: 2 },
  ];
  assert.deepEqual(
    conversationMatches(messages, "ANTENNA", () => "Peer").map((x) => x.id),
    ["old"],
  );
  assert.deepEqual(
    conversationMatches(messages, "thorian", (peer) =>
      peer === "a" ? "Thorian" : "Other",
    ).map((x) => x.id),
    ["new"],
  );
  assert.deepEqual(
    conversationMatches(messages, "", () => "Peer").map((x) => x.id),
    ["new", "other"],
  );
  const older = {
    id: "archived",
    peer: "c",
    content: "Archived antenna",
    timestamp: 0,
  };
  assert.deepEqual(
    conversationMatches(messages, "antenna", () => "Peer", null, [older]).map(
      (x) => x.id,
    ),
    ["old", "archived"],
  );
});

test("pairing QR round-trips through the offline phone scanner", async () => {
  const { default: qrCode } = await import("../ui/vendor/qrcode.cjs");
  const { default: jsQR } = await import("../ui/vendor/jsqr.cjs");
  const payload = JSON.stringify({
    cixnet: 1,
    host: "192.168.50.12",
    port: 4242,
    name: "ciXnet desktop",
    public: "ab".repeat(64),
    destination: "cd".repeat(16),
    secret: "ef".repeat(32),
    expires: 1900000000,
  });
  const qr = qrCode(0, "M");
  qr.addData(payload);
  qr.make();
  const scale = 5,
    quiet = 4,
    count = qr.getModuleCount();
  const width = (count + quiet * 2) * scale;
  const pixels = new Uint8ClampedArray(width * width * 4).fill(255);
  for (let row = 0; row < count; row++)
    for (let col = 0; col < count; col++) {
      if (!qr.isDark(row, col)) continue;
      for (let y = 0; y < scale; y++)
        for (let x = 0; x < scale; x++) {
          const offset =
            (((row + quiet) * scale + y) * width + (col + quiet) * scale + x) *
            4;
          pixels[offset] = pixels[offset + 1] = pixels[offset + 2] = 0;
        }
    }
  assert.equal(jsQR(pixels, width, width).data, payload);
});
import { imageMime } from "../ui/micron-images.js";

test("Micron images preserve alt text, native path and layout", () => {
  const block = parseMicron("`(A picture`w=320`h=240`a=c`/file/photo.png)")
    .blocks[0];
  assert.equal(block.type, "image");
  assert.equal(block.target, "/file/photo.png");
  assert.equal(block.width, "320");
  assert.equal(block.align, "center");
  assert.equal(block.alt, "A picture");
});
test("embedded images accept raster signatures and reject active content", () => {
  assert.equal(
    imageMime(new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10])),
    "image/png",
  );
  assert.equal(
    imageMime(new TextEncoder().encode("<svg onload='evil()'>")),
    null,
  );
  assert.equal(imageMime(new Uint8Array()), null);
});
import { loadMicronImage, AUTO_IMAGE_BYTES } from "../ui/micron-images.js";
test("small images load automatically with a transfer limit and cached images avoid requests", async () => {
  const savedFetch = globalThis.fetch,
    savedDocument = globalThis.document,
    savedActive = model.active;
  const opens = [];
  let downloads = 0;
  const png = new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10]);
  globalThis.document = { createElement: () => ({}) };
  model.active = { id: "image-test" };
  globalThis.fetch = async (url, options) => {
    const body = JSON.parse(options.body);
    if (url.endsWith("/open")) {
      opens.push(body);
      return { ok: true, json: async () => ({ id: "image-job" }) };
    }
    if (url.endsWith("/status"))
      return {
        ok: true,
        json: async () => ({ phase: "done", download: { size: png.length } }),
      };
    if (url.endsWith("/download")) {
      downloads++;
      return { ok: true, arrayBuffer: async () => png.buffer };
    }
    return { ok: true, json: async () => ({}) };
  };
  const image = () => ({
    isConnected: true,
    after() {},
    set src(value) {
      this.loaded = value;
      this.onload();
    },
  });
  const wait = async (node) => {
    for (let n = 0; n < 50 && !node.loaded; n++)
      await new Promise((resolve) => setTimeout(resolve, 1));
    assert.ok(node.loaded);
  };
  try {
    const page = { url: "a".repeat(32) + ":/page/index.mu" };
    const first = image();
    loadMicronImage(page, ":/file/photo.webp", first);
    await wait(first);
    assert.equal(opens[0].max_bytes, AUTO_IMAGE_BYTES);
    assert.equal(opens[0].url, "/file/photo.webp");
    const second = image();
    loadMicronImage(page, ":/file/photo.webp", second);
    await wait(second);
    assert.equal(opens.length, 1);
    assert.equal(downloads, 1);
  } finally {
    globalThis.fetch = savedFetch;
    globalThis.document = savedDocument;
    model.active = savedActive;
  }
});

test("automatic images are not skipped after four entries or an earlier render", async () => {
  const previousFetch = globalThis.fetch,
    previousDocument = globalThis.document,
    previousActive = model.active;
  let opens = 0;
  globalThis.document = { createElement: () => ({}) };
  model.active = { id: "auto-retry" };
  globalThis.fetch = async (url) => {
    if (url.endsWith("/open")) {
      opens++;
      return { ok: true, json: async () => ({ id: "retry" }) };
    }
    return {
      ok: true,
      json: async () => ({ phase: "error", error: "Too large" }),
    };
  };
  try {
    const page = {
      url: "a".repeat(32) + ":/page/index.mu",
      autoImages: new Set(["/media/a.webp", "b", "c", "d"]),
    };
    const buttons = [];
    for (let index = 0; index < 6; index++)
      loadMicronImage(page, "/media/a.webp", {
        isConnected: true,
        after(button) {
          buttons.push(button);
        },
      });
    for (let n = 0; n < 100 && opens < 6; n++)
      await new Promise((resolve) => setTimeout(resolve, 1));
    assert.equal(opens, 6);
    assert.ok(
      buttons.every((button) =>
        button.textContent.includes("larger or unavailable"),
      ),
    );
  } finally {
    globalThis.fetch = previousFetch;
    globalThis.document = previousDocument;
    model.active = previousActive;
  }
});
