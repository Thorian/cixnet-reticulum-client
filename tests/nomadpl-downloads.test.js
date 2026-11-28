import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";
import { runInNewContext } from "node:vm";

test("NomadPL blob downloads report byte progress and deliver the complete file to the parent", async () => {
  const reports = [];
  let complete;
  const done = new Promise((resolve) => {
    complete = resolve;
  });
  class Anchor {
    href = "blob:http://page.localhost/file";
    download = "photo.png";
    hasAttribute(name) {
      return name === "download";
    }
    click() {
      assert.fail("WebView must not receive an unsupported blob download");
    }
  }
  const source = await readFile(
    new URL("../ui/nomadpl-bridge.js", import.meta.url),
    "utf8",
  );
  const bytes = new Uint8Array([137, 80, 78, 71, 4, 5]);
  const scope = {
    document: {
      currentScript: {
        dataset: { parent: "http://client.localhost", channel: "test" },
      },
      title: "File",
      addEventListener() {},
    },
    location: {
      href: "http://page.localhost/",
      origin: "http://page.localhost",
    },
    history: { state: {}, replaceState() {}, pushState() {} },
    crypto: { randomUUID: () => "id" },
    parent: {
      postMessage: (data) => {
        reports.push(data);
        if (
          data.type === "cixnet-download-ready" ||
          data.type === "cixnet-download-error"
        )
          complete(data);
      },
    },
    addEventListener() {},
    window: {},
    HTMLAnchorElement: Anchor,
    fetch: async () =>
      new Response(bytes, {
        headers: { "content-length": "6", "content-type": "image/png" },
      }),
    URL,
    Blob,
    AbortController,
    setTimeout,
    clearTimeout,
  };
  runInNewContext(source, scope);
  new Anchor().click();
  const result = await done;
  assert.equal(result.type, "cixnet-download-ready");
  assert.equal(result.name, "photo.png");
  assert.deepEqual(new Uint8Array(await result.blob.arrayBuffer()), bytes);
  assert(
    reports.some(
      (item) =>
        item.type === "cixnet-download-progress" &&
        item.received === 6 &&
        item.total === 6,
    ),
  );
});
