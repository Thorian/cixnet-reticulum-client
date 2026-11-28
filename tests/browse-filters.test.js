import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";
import {
  loadBrowseKinds,
  saveBrowseKinds,
  discoveredNodes,
  bookmarkName,
} from "../ui/browse-filters.js";

test("address-only bookmarks use announce names without replacing custom labels", () => {
  const address = "a".repeat(32);
  const url = `nomadpl://${address}/`;
  const announces = [{ address, display_name: "ciXnet - Search" }];
  assert.equal(bookmarkName({ url, name: url }, announces), "ciXnet - Search");
  assert.equal(
    bookmarkName({ url, name: "My search" }, announces),
    "My search",
  );
  assert.equal(bookmarkName({ url }, []), url);
});

test("browse choices survive reload, including hiding every type", () => {
  let saved = null;
  const storage = {
    getItem: () => saved,
    setItem: (_, value) => {
      saved = value;
    },
  };
  assert.equal(loadBrowseKinds(storage).size, 3);
  saveBrowseKinds(storage, new Set(["nomadpl"]));
  assert.deepEqual([...loadBrowseKinds(storage)], ["nomadpl"]);
  saveBrowseKinds(storage, new Set());
  assert.equal(loadBrowseKinds(storage).size, 0);
  saved = "not json";
  assert.equal(loadBrowseKinds(storage).size, 3);
});

test("discovered services filter by type and sort names alphabetically with numeric order", () => {
  const nodes = [
    { address: "1", kind: "node", display_name: "Zebra" },
    { address: "2", kind: "nomadpl", display_name: "alpha 10" },
    { address: "3", kind: "lxmf", display_name: "Alpha 2" },
    { address: "4", kind: "transport", display_name: "Gateway" },
  ];
  assert.deepEqual(
    discoveredNodes(nodes, new Set(["node", "nomadpl", "lxmf"])).map(
      (item) => item.address,
    ),
    ["3", "2", "1"],
  );
  assert.deepEqual(
    discoveredNodes(nodes, new Set(["node"])).map((item) => item.address),
    ["1"],
  );
  assert.equal(nodes[0].address, "1");
});

test("transport announces have their own visible label and colour", async () => {
  const source = await readFile(
    new URL("../ui/network-ui.js", import.meta.url),
    "utf8",
  );
  assert.match(source, /transport: "transport"/);
  assert.match(source, /transport: "Transport"/);
  const css = await readFile(
    new URL("../ui/style.css", import.meta.url),
    "utf8",
  );
  assert.match(css, /\.entry-transport\s*\{/);
});
