import assert from "node:assert/strict";
import test from "node:test";
import { api } from "../ui/core.js";

test("slow actions share one request, clear feedback on failure, and allow retry", async () => {
  const originalDocument = globalThis.document;
  const originalFetch = globalThis.fetch;
  function element() {
    const children = [];
    return {
      children,
      setAttribute() {},
      append(...items) {
        children.push(...items);
        for (const item of items) item.parentElement = this;
      },
      querySelector(selector) {
        return children.find((child) => "." + child.className === selector);
      },
    };
  }
  const body = element();
  globalThis.document = {
    body,
    createElement: element,
    querySelectorAll: () => [],
  };
  let resolve;
  let calls = 0;
  globalThis.fetch = () => {
    calls++;
    return new Promise((done) => {
      resolve = done;
    });
  };
  try {
    const first = api("dns/save", { suffix: "cix" });
    const second = api("dns/save", { suffix: "cix" });
    assert.equal(first, second);
    assert.equal(calls, 1);
    assert.equal(body.children[0].hidden, false);
    resolve({
      ok: false,
      status: 500,
      json: async () => ({ error: "Test failure" }),
    });
    await assert.rejects(first, /Test failure/);
    assert.equal(body.children[0].hidden, true);
    const retry = api("dns/save", { suffix: "cix" });
    assert.equal(calls, 2);
    resolve({ ok: true, status: 200, json: async () => ({ saved: true }) });
    assert.deepEqual(await retry, { saved: true });
    assert.equal(body.children[0].hidden, true);
  } finally {
    globalThis.document = originalDocument;
    globalThis.fetch = originalFetch;
  }
});
