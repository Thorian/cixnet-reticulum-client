import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";
import { runInNewContext } from "node:vm";

test("NomadPL reports form navigation, suppresses repeat submission and tracks dynamic requests", async () => {
  const source = await readFile(
    new URL("../ui/nomadpl-bridge.js", import.meta.url),
    "utf8",
  );
  const events = {};
  const reports = [];
  const pending = [];
  const on = (name, callback) => (events[name] ||= []).push(callback);
  const window = {
    fetch: () =>
      new Promise((resolve, reject) => pending.push({ resolve, reject })),
    stop() {},
  };
  runInNewContext(source, {
    document: {
      currentScript: {
        dataset: { parent: "http://client.localhost", channel: "test" },
      },
      title: "Test",
      addEventListener: on,
    },
    location: { href: "http://page.localhost/start" },
    history: { state: {}, replaceState() {}, pushState() {}, go() {} },
    crypto: { randomUUID: () => "id" },
    parent: { postMessage: (data) => reports.push(data) },
    addEventListener: on,
    window,
    URL,
  });
  const messagingAddress = "abcdef0123456789abcdef0123456789";
  for (const href of [
    `lxmf://${messagingAddress}`,
    `lxmf@${messagingAddress}`,
  ]) {
    let blocked = false;
    const link = { href, getAttribute: () => href };
    const event = {
      button: 0,
      target: { closest: () => link },
      preventDefault() {
        blocked = true;
        this.defaultPrevented = true;
      },
    };
    events.click.forEach((fn) => fn(event));
    assert.equal(blocked, true);
    assert.equal(reports.at(-1).type, "cixnet-open");
    assert.equal(reports.at(-1).href, href);
  }
  const form = { target: "" };
  let prevented = 0;
  const submit = () =>
    events.submit.forEach((fn) =>
      fn({
        target: form,
        preventDefault() {
          prevented++;
        },
      }),
    );
  submit();
  assert.equal(reports.at(-1).type, "cixnet-loading");
  submit();
  assert.equal(prevented, 1);
  events.pageshow.forEach((fn) => fn());
  assert.equal(reports.at(-1).type, "cixnet-loaded");
  submit();
  assert.equal(prevented, 1);
  events.pageshow.forEach((fn) => fn());
  const first = window.fetch("/first");
  const second = window.fetch("/second");
  assert.equal(reports.at(-1).type, "cixnet-loading");
  pending[0].resolve("first");
  await first;
  assert.equal(reports.at(-1).type, "cixnet-loading");
  pending[1].reject(new Error("Connection lost"));
  await assert.rejects(second, /Connection lost/);
  assert.equal(reports.at(-1).type, "cixnet-loaded");
});
