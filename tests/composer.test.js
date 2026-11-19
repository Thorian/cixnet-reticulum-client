import assert from "node:assert/strict";
import test from "node:test";
import { model } from "../ui/core.js";
import { sendMessage } from "../ui/messaging-ui.js";

test("a late send result cannot erase a reopened conversation draft", async () => {
  const savedDocument = globalThis.document,
    savedFetch = globalThis.fetch;
  const previousActive = model.active,
    previousConversation = model.conversation;
  const element = () => ({
    children: [],
    classList: { add() {}, remove() {} },
    setAttribute() {},
    removeAttribute() {},
    append(...items) {
      this.children.push(...items);
      for (const item of items) item.parentElement = this;
    },
    querySelector(selector) {
      return this.children.find((item) => "." + item.className === selector);
    },
  });
  const button = element(),
    oldInput = { value: "Original message", style: {} },
    error = { textContent: "" };
  const originalForm = { querySelectorAll: () => [button, oldInput] };
  const fields = {
    "send-message": button,
    "message-body": oldInput,
    "send-form": originalForm,
    "send-error": error,
  };
  let resolveRequest, markStarted;
  const started = new Promise((resolve) => {
    markStarted = resolve;
  });
  globalThis.document = {
    getElementById: (id) => fields[id],
    createElement: element,
    body: element(),
    querySelectorAll: () => [],
  };
  globalThis.fetch = () => {
    markStarted();
    return new Promise((resolve) => {
      resolveRequest = resolve;
    });
  };
  model.active = { id: "owner" };
  model.conversation = "peer";
  try {
    const sending = sendMessage({ preventDefault() {} });
    await started;
    fields["send-form"] = {};
    fields["message-body"] = { value: "New unsent draft", style: {} };
    resolveRequest({
      ok: true,
      status: 200,
      json: async () => ({ id: "message-id" }),
    });
    await sending;
    assert.equal(fields["message-body"].value, "New unsent draft");
    assert.equal(button.disabled, false);
  } finally {
    globalThis.document = savedDocument;
    globalThis.fetch = savedFetch;
    model.active = previousActive;
    model.conversation = previousConversation;
  }
});
