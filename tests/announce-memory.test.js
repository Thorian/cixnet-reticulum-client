import assert from "node:assert/strict";
import test from "node:test";
import { model } from "../ui/core.js";
import { renderAnnounces } from "../ui/network-ui.js";
import { trimImageCaches } from "../ui/micron-images.js";

test("image history releases older bytes when the shared budget is reached", () => {
  const old = { images: new Map([["old", { size: 8 }]]) };
  const recent = { images: new Map([["recent", { size: 8 }]]) };
  trimImageCaches([old, recent], 10);
  assert.equal(old.images.size, 0);
  assert.equal(recent.images.size, 1);
});

class Element {
  children = [];
  dataset = {};
  classList = { add() {}, toggle() {} };
  append(child) {
    this.children.push(child);
  }
  replaceChildren() {
    this.children = [];
  }
  setAttribute() {}
  get lastChild() {
    return this.children.at(-1);
  }
  insertBefore(child, sibling) {
    this.children.splice(this.children.indexOf(sibling), 0, child);
  }
  querySelector(selector) {
    return this.children.find((child) => `.${child.className}` === selector);
  }
}

test("10,000 announces render at most 100 rows, reuse unchanged rows and remain searchable", () => {
  const previous = globalThis.document;
  const list = new Element();
  const search = { value: "" };
  globalThis.document = {
    getElementById: (id) => (id === "search" ? search : list),
    createElement: () => new Element(),
  };
  const network = model.network;
  try {
    model.network = {
      phase: "running",
      announces: Array.from({ length: 10000 }, (_, i) => ({
        address: String(i).padStart(32, "0"),
        display_name: `Node ${i}`,
        kind: "node",
        received: 100,
      })),
    };
    renderAnnounces();
    assert.equal(list.children.length, 101);
    const first = list.children[1];
    renderAnnounces();
    assert.equal(list.children[1], first);
    list.children[0].lastChild.onclick();
    assert.match(list.children[1].title, /00000000000000000000000000000100$/);
    search.value = "Node 9999";
    renderAnnounces();
    assert.equal(list.children.length, 2);
    assert.match(list.children[1].title, /00000000000000000000000000009999$/);
  } finally {
    globalThis.document = previous;
    model.network = network;
  }
});
