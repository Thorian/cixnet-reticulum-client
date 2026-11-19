import assert from "node:assert/strict";
import test from "node:test";
import { lxmfAddress } from "../ui/lxmf-links.js";
const address = "ABCDEF0123456789ABCDEF0123456789";
test("LXMF links recognise native and URI forms", () => {
  for (const link of [
    `lxmf@${address}`,
    `lxmf.delivery@${address}`,
    `lxmf://${address}`,
    `lxmf:${address}`,
    `lxmf://${address}/`,
    `lxmf://${address}?name=Test`,
  ])
    assert.equal(lxmfAddress(link), address.toLowerCase());
});
test("LXMF links reject unrelated URLs and malformed destinations", () => {
  for (const link of [
    address,
    `https://example.com/lxmf@${address}`,
    `lxmf://${address}/page`,
    `lxmf://user@${address}`,
    "lxmf://1234",
    null,
  ])
    assert.equal(lxmfAddress(link), null);
});
