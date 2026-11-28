import assert from "node:assert/strict";
import test from "node:test";
import { initDownloads, saveBlob } from "../ui/downloads.js";

class Element {
  children = [];
  classList = { add() {}, remove() {} };
  append(...children) {
    this.children.push(...children);
  }
  querySelector(tag) {
    return this.children.find((child) => child.tag === tag);
  }
  showModal() {}
  close() {}
  remove() {}
  removeAttribute() {}
}

test("Android saves wait for chunk acknowledgements, preserve bytes and cancel failed writes", async () => {
  const toast = new Element();
  globalThis.document = {
    documentElement: { dataset: { downloadToken: "native-secret" } },
    body: new Element(),
    createElement: (tag) => Object.assign(new Element(), { tag }),
    getElementById: () => toast,
  };
  let receivePort;
  globalThis.addEventListener = (_, callback) => {
    receivePort = callback;
  };
  const requests = [];
  let outstanding = 0;
  let fail = false;
  const port = {
    start() {},
    close() {},
    postMessage(text) {
      const request = JSON.parse(text);
      assert.equal(
        outstanding++,
        0,
        "Only one chunk may await acknowledgement",
      );
      requests.push(request);
      queueMicrotask(() => {
        outstanding--;
        port.onmessage({
          data: JSON.stringify({
            request: request.request,
            error: fail && request.action === "chunk" ? "Disk full" : undefined,
          }),
        });
      });
    },
  };
  initDownloads();
  const impostor = {
    start() {
      assert.fail("An untrusted frame must not supply the native port");
    },
  };
  receivePort({ data: "wrong-token", ports: [impostor] });
  receivePort({ data: "native-secret", ports: [port] });
  const bytes = Uint8Array.from({ length: 70000 }, (_, index) => index % 251);
  await saveBlob(new Blob([bytes], { type: "image/png" }), "photo.png");
  assert.equal(requests[0].action, "begin");
  assert.equal(requests.at(-1).action, "finish");
  const chunks = requests.filter((request) => request.action === "chunk");
  assert.equal(chunks.length, 3);
  assert.deepEqual(
    Buffer.concat(chunks.map((request) => Buffer.from(request.data, "base64"))),
    Buffer.from(bytes),
  );
  fail = true;
  await assert.rejects(saveBlob(new Blob([bytes]), "failed.bin"), /Disk full/);
  assert.equal(requests.at(-1).action, "cancel");
});
