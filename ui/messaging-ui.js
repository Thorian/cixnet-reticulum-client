import { beginActivity } from "./activity.js";
/** Conversations and LXMF UI. Transport work stays in the Python service. */
import { conversationMatches } from "./conversation-search.js";
import { deliveryStatus } from "./delivery-status.js";
import {
  $,
  model,
  api,
  escapeHTML,
  peerName,
  shortTime,
  showDialog,
  showToast,
} from "./core.js";
import { iconMarkup } from "./icons.js";
import { openCamera } from "./camera-ui.js";
import {
  attachmentView,
  clearAttachmentPreviews,
  validateSelection,
  encodeFile,
  formatSize,
  reduceImage,
} from "./attachments-ui.js";

let onBack;
let listSignature = "";
let selectedFiles = [];
let searchTimer;
let searchVersion = 0;
let searchState = { key: "", matches: [] };
let searchContext = null;
let contextVersion = 0;

/** Fetch all-history matches only after typing pauses, ignoring stale responses. */
function scheduleSearch(query) {
  const owner = model.active?.id;
  const key = `${owner}:${query}:${model.messages.length}:${model.messages[model.messages.length - 1]?.id}`;
  if (searchState.key === key) return;
  clearTimeout(searchTimer);
  const version = ++searchVersion;
  searchState = { key, matches: [] };
  if (!query || !owner) return;
  searchTimer = setTimeout(async () => {
    try {
      const result = await api("messaging/search", { owner, query });
      if (
        version !== searchVersion ||
        model.active?.id !== owner ||
        model.tab !== "contacts" ||
        $("search").value.trim().toLocaleLowerCase() !== query
      )
        return;
      searchState.matches = result.matches;
      renderConversations();
    } catch (error) {
      if (version === searchVersion && model.active?.id === owner)
        showToast(error.message);
    }
  }, 250);
}

/** Opening an old hit loads its conversation context instead of losing it at the snapshot limit. */
async function openSearchResult(message) {
  const owner = model.active?.id;
  const version = ++contextVersion;
  const query = $("search").value;
  try {
    const result = await api("messaging/history", {
      owner,
      around: message.id,
    });
    if (
      model.active?.id !== owner ||
      version !== contextVersion ||
      $("search").value !== query ||
      model.tab !== "contacts"
    )
      return;
    openConversation(message.peer, {
      messages: result.messages,
      focusId: message.id,
    });
  } catch (error) {
    if (model.active?.id === owner) showToast(error.message);
  }
}

/** Hide attachment controls and keep their expanded state accessible. */
function closeAttachmentMenu() {
  if ($("attachment-menu")) $("attachment-menu").hidden = true;
  $("attach-open")?.setAttribute("aria-expanded", "false");
}

/** Bind conversation actions and dismiss attachment menus outside their controls. */
export function initMessaging(callbacks) {
  onBack = callbacks.onBack;
  $("compose").onclick = showCompose;
  document.addEventListener("click", (event) => {
    /** Dismiss the attachment menu when the user clicks outside its controls. */

    if (!event.target.closest(".attachment-controls")) closeAttachmentMenu();
  });
  document.addEventListener("keydown", (event) => {
    /** Dismiss an open attachment menu when Escape is pressed. */

    if (
      event.key === "Escape" &&
      $("attachment-menu") &&
      !$("attachment-menu").hidden
    ) {
      closeAttachmentMenu();
      $("attach-open").focus();
    }
  });
}

/** Activate the profile's router before loading its message history. */
export async function activateMessaging(profile) {
  const result = await api("messaging/activate", { owner: profile.id });
  // Identity switching can happen while a request is in flight.
  if (model.active?.id === profile.id) model.ownAddress = result.address;
}

/** Fetch history for the selected identity and ignore stale identity responses. */
export async function refreshHistory() {
  const owner = model.active?.id;
  if (!owner) return;
  const result = await api("messaging/history", { owner });
  if (model.active?.id !== owner) return;
  if (
    searchContext?.owner === owner &&
    searchContext.peer === model.conversation
  ) {
    const combined = new Map(
      [...searchContext.messages, ...result.messages].map((message) => [
        message.id,
        message,
      ]),
    );
    model.messages = [...combined.values()].sort(
      (a, b) => a.timestamp - b.timestamp,
    );
  } else {
    searchContext = null;
    model.messages = result.messages;
  }
  const sync = result.propagation;
  if (sync && $("propagation-status") && $("settings-dialog").open) {
    const label =
      sync.state === 0
        ? "Idle"
        : sync.state === 7
          ? "Mailbox check complete"
          : sync.state >= 240
            ? "Relay unavailable or access denied; will retry"
            : "Checking relay mailbox";
    $("propagation-status").textContent =
      label +
      (sync.state > 0 && sync.state < 7
        ? ` · ${Math.round(sync.progress * 100)}%`
        : "");
  }
  model.blockedContacts = result.blocked || [];
  model.appearances = result.appearances || {};
  model.peerNames = result.names || {};
}

/** Render the peer's validated appearance or a neutral bundled fallback. */
function peerAvatar(peer) {
  return iconMarkup(
    model.appearances[peer] || { icon: "account", color: "green" },
  );
}

/** Update the filtered conversation list without replacing unchanged rows. */
export function renderConversations() {
  if (model.tab !== "contacts") return;
  const query = $("search").value.trim().toLocaleLowerCase();
  scheduleSearch(query);
  const signature = JSON.stringify([
    model.messages,
    model.conversation,
    model.draftPeer,
    model.ownAddress,
    model.appearances,
    model.peerNames,
    searchState.matches,
    model.network.announces,
    query,
  ]);
  // Leave unchanged rows in place, preserving focus and click targets during polling.
  if (
    signature === listSignature &&
    $("list-content").firstElementChild?.dataset.conversationList
  )
    return;
  listSignature = signature;
  const latestMessages = conversationMatches(
    model.messages,
    query,
    peerName,
    model.draftPeer,
    searchState.matches,
  );

  $("list-content").replaceChildren();
  if (!latestMessages.length) {
    $("list-content").innerHTML = `<div class="list-empty">
      <strong>${query ? "No matches" : "Your conversations start here"}</strong>
      Use ＋ to enter an LXMF address.
      ${model.ownAddress ? `<p>Your messaging address:</p><p class="address-text">${escapeHTML(model.ownAddress)}</p>` : ""}
    </div>`;
  }
  for (const message of latestMessages) {
    const button = document.createElement("button");
    button.className = `conversation-item${message.peer === model.conversation ? " selected" : ""}`;
    button.innerHTML = `<span class="avatar">${peerAvatar(message.peer)}</span>
      <span class="conversation-label"><strong>${escapeHTML(peerName(message.peer))}</strong>
      <small>${escapeHTML(message.content || (message.attachments?.length ? `${message.attachments.length} attachment(s)` : ""))}</small></span><time>${shortTime(message.timestamp)}</time>`;
    /** Open the conversation associated with this row. */
    button.onclick = () =>
      query && message.id
        ? openSearchResult(message)
        : openConversation(message.peer);
    $("list-content").append(button);
  }
  if ($("list-content").firstElementChild)
    $("list-content").firstElementChild.dataset.conversationList = "true";
}

/** Show one peer's messages and start with a clean attachment draft. */
export function openConversation(peer, context = null) {
  contextVersion++;
  searchContext = context
    ? { ...context, owner: model.active.id, peer, focusPending: true }
    : null;
  if (context) {
    const combined = new Map(
      [...context.messages, ...model.messages].map((message) => [
        message.id,
        message,
      ]),
    );
    model.messages = [...combined.values()].sort(
      (a, b) => a.timestamp - b.timestamp,
    );
  }
  selectedFiles = [];
  clearAttachmentPreviews();
  model.conversation = peer;
  model.draftPeer = peer;
  document.querySelector(".app-body").classList.add("mobile-content");
  $("detail").innerHTML = `<header class="chat-header">
    <button id="chat-back" aria-label="Back to contacts">←</button>
    <button id="chat-contact" class="chat-contact" title="View contact announce" aria-label="View contact announce"><span id="chat-peer-avatar" class="avatar">${peerAvatar(peer)}</span>
    <div><strong id="chat-peer-name">${escapeHTML(peerName(peer))}</strong>
    <small>${escapeHTML(peer)} · Encrypted LXMF · direct delivery</small></div>
    </button>
    </header><div id="chat-messages" class="chat-messages"></div>
    <form id="send-form" class="send-form"><div id="selected-files"></div><div class="composer-input"><textarea id="message-body" rows="1"
      placeholder="Message" aria-label="Message"></textarea>
      <div class="composer-actions"><div class="attachment-controls">
      <button type="button" id="attach-open" aria-label="Add attachment" aria-expanded="false" aria-controls="attachment-menu" title="Attach">
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path transform="rotate(35 12 12)" d="M8 9v8a4 4 0 0 0 8 0V7a3 3 0 0 0-6 0v10a1 1 0 0 0 2 0V8"/></svg></button>
      <div id="attachment-menu" class="attachment-menu" hidden><button type="button" id="attach-file">File</button><button type="button" id="attach-image">Image</button><button type="button" id="take-photo">Take photo</button><small>Up to 8 files · 8 MiB total</small></div>
      <input type="file" id="file-picker" multiple hidden><input type="file" id="image-picker" accept="image/png,image/jpeg,image/gif,image/webp" multiple hidden>
      <input type="file" id="camera-picker" accept="image/*" capture="user" hidden>
      </div><button class="primary" id="send-message" aria-label="Send message" title="Send message"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 19V5m-7 7 7-7 7 7"/></svg></button></div></div>
      <p id="send-error" role="alert" class="error"></p></form>`;
  $("send-form").hidden = (model.blockedContacts || []).includes(peer);
  $("chat-contact").onclick = () =>
    document.dispatchEvent(
      new CustomEvent("cixnet-open-contact", { detail: peer }),
    );
  $("chat-back").onclick = onBack;
  $("send-form").onsubmit = sendMessage;
  /** Resize the composer within its allowed height as text changes. */
  $("message-body").oninput = () => {
    const field = $("message-body");
    field.style.height = "auto";
    field.style.height = `${Math.min(160, Math.max(52, field.scrollHeight))}px`;
  };
  /** Toggle the attachment menu and its accessible expanded state. */
  $("attach-open").onclick = () => {
    const menu = $("attachment-menu");
    menu.hidden = !menu.hidden;
    $("attach-open").setAttribute("aria-expanded", String(!menu.hidden));
    if (!menu.hidden) $("attach-file").focus();
  };
  /** Open the generic file picker after closing the attachment menu. */
  $("attach-file").onclick = () => {
    closeAttachmentMenu();
    $("file-picker").click();
  };
  /** Open the image picker after closing the attachment menu. */
  $("attach-image").onclick = () => {
    closeAttachmentMenu();
    $("image-picker").click();
  };
  const cameraOwner = model.active.id;
  /** Attach a captured image only while its original identity and conversation remain active. */
  const addPhoto = (file) => {
    if (model.active?.id !== cameraOwner || model.conversation !== peer) return;
    if (selectedFiles.length >= 8) {
      $("send-error").textContent = "Choose at most 8 attachments.";
      return;
    }
    selectedFiles.push({
      file,
      original: file,
      image: true,
      sizeChoice: "original",
    });
    renderSelectedFiles();
  };
  /** Add the selected capture and reset the picker for a later selection. */
  $("camera-picker").onchange = () => {
    const file = $("camera-picker").files[0];
    if (file) addPhoto(file);
    $("camera-picker").value = "";
  };
  /** Choose the native capture picker or desktop camera flow for this device. */
  $("take-photo").onclick = () => {
    closeAttachmentMenu();
    /** Open the platform image-capture picker when that control is available. */
    const picker = () => $("camera-picker")?.click();
    if (/Android|iPhone|iPad/i.test(navigator.userAgent)) picker();
    else openCamera(addPhoto, picker);
  };
  for (const [id, image] of [
    ["file-picker", false],
    ["image-picker", true],
  ]) {
    /** Validate newly picked files before adding them to the current draft. */
    $(id).onchange = () => {
      const added = [...$(id).files].map((file) => ({
        file,
        original: file,
        image,
        sizeChoice: "original",
      }));
      try {
        if (selectedFiles.length + added.length > 8)
          throw new Error("Choose at most 8 attachments.");
        selectedFiles.push(...added);
        renderSelectedFiles();
        $("send-error").textContent = "";
      } catch (error) {
        $("send-error").textContent = error.message;
      }
      $(id).value = "";
    };
  }
  renderMessages();
  renderConversations();
}

/** Display attachment drafts and their remove or image-size controls. */
function renderSelectedFiles() {
  $("selected-files").replaceChildren();
  selectedFiles.forEach((item, index) => {
    /** Create controls for one selected file without sending it yet. */

    const row = document.createElement("div");
    row.className = "selected-file";
    const label = document.createElement("span");
    label.textContent = `${item.file.name} · ${formatSize(item.file.size)}`;
    if (item.processing) label.textContent += " · Reducing…";
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "Remove";
    /** Remove this attachment draft and refresh the remaining selection. */
    remove.onclick = () => {
      selectedFiles.splice(index, 1);
      renderSelectedFiles();
    };
    row.append(label, remove);
    if (item.image) {
      const size = document.createElement("select");
      size.setAttribute("aria-label", `Image size for ${item.original.name}`);
      for (const [value, text] of [
        ["original", "Original image"],
        ["640", "Small · 640 px"],
        ["1280", "Medium · 1280 px"],
        ["1920", "Large · 1920 px"],
      ]) {
        size.add(new Option(text, value));
      }
      size.value = item.sizeChoice;
      size.disabled = item.processing;
      /** Create the requested image-size copy while keeping the original available. */
      size.onchange = async () => {
        item.sizeChoice = size.value;
        item.processing = true;
        renderSelectedFiles();
        try {
          item.file =
            item.sizeChoice === "original"
              ? item.original
              : await reduceImage(item.original, Number(item.sizeChoice));
        } catch (error) {
          item.file = item.original;
          item.sizeChoice = "original";
          if (selectedFiles.includes(item))
            $("send-error").textContent = error.message;
        } finally {
          item.processing = false;
          if (selectedFiles.includes(item)) renderSelectedFiles();
        }
      };
      const note = document.createElement("small");
      note.textContent =
        item.sizeChoice === "original"
          ? "Optional: reduce before sending"
          : `${formatSize(item.original.size)} → ${formatSize(item.file.size)} · WebP, 80% quality · still image. Original kept if smaller.`;
      row.append(size, note);
    }
    $("selected-files").append(row);
  });
}

/** Submit the current text and validated attachments under the selected identity. */
export async function sendMessage(event) {
  event.preventDefault();
  if ($("send-message").disabled) return;
  const owner = model.active.id;
  const peer = model.conversation;
  const composer = $("send-form");
  const content = $("message-body").value;
  const files = [...selectedFiles];
  if (files.some((item) => item.processing)) {
    $("send-error").textContent = "Wait for image reduction to finish.";
    return;
  }
  try {
    validateSelection(files.map((item) => item.file));
  } catch (error) {
    $("send-error").textContent = error.message;
    return;
  }
  const finishPreparing = beginActivity("Preparing message");
  $("send-message").classList.add("is-busy");
  $("send-message").setAttribute("aria-busy", "true");
  const sendButton = $("send-message");
  $("send-message").disabled = true;
  const controls = [
    ...$("send-form").querySelectorAll("input, textarea, select, button"),
  ];
  controls.forEach((control) => {
    /** Prevent duplicate composer actions while the message is being submitted. */

    control.disabled = true;
  });
  $("send-error").textContent = "";
  /** Check whether the original composer still owns this asynchronous send result. */
  const stillHere = () =>
    model.active?.id === owner &&
    model.conversation === peer &&
    $("send-form") === composer;
  try {
    const attachments = await Promise.all(
      files.map((item) => encodeFile(item.file, item.image)),
    );
    await api("messaging/send", { owner, peer, content, attachments });
    if (stillHere()) {
      $("message-body").value = "";
      $("message-body").style.height = "52px";
      selectedFiles = [];
      renderSelectedFiles();
      await refreshHistory();
      if (stillHere()) {
        renderMessages();
        renderConversations();
      }
    }
  } catch (error) {
    if (stillHere() && $("send-error"))
      $("send-error").textContent = error.message;
  } finally {
    finishPreparing();
    sendButton.classList.remove("is-busy");
    sendButton.removeAttribute("aria-busy");
    controls.forEach((control) => {
      /** Re-enable the original composer after its send request finishes. */

      control.disabled = false;
    });
  }
}

/** Render the active peer's history with safe text and bounded attachment controls. */
export function renderMessages() {
  const box = $("chat-messages");
  if (!box || !model.conversation) return;
  $("chat-peer-avatar").innerHTML = peerAvatar(model.conversation);
  $("chat-peer-name").textContent = peerName(model.conversation);
  const relevant = model.messages.filter(
    (message) => message.peer === model.conversation,
  );
  const signature = JSON.stringify(relevant);
  if (box.dataset.signature === signature) return;
  const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 70;
  box.dataset.signature = signature;
  clearAttachmentPreviews();
  box.replaceChildren();
  for (const message of relevant) {
    const bubble = document.createElement("article");
    bubble.className = `bubble ${message.direction}`;
    bubble.dataset.messageId = message.id;
    bubble.classList.toggle(
      "search-match",
      message.id === searchContext?.focusId,
    );
    const content = document.createElement("p");
    // Message content is text, never executable HTML.
    content.textContent = message.content;
    const meta = document.createElement("small");
    const status = deliveryStatus(message.status);
    const time = document.createElement("span");
    time.textContent = shortTime(message.timestamp);
    meta.append(time);
    if (message.direction === "out") {
      const mark = document.createElement("span");
      mark.className = "delivery-mark delivery-" + status.tone;
      mark.textContent = status.mark;
      mark.setAttribute("role", "img");
      mark.setAttribute("aria-label", status.label);
      mark.title = status.label;
      meta.append(mark);
    }
    const relay =
      message.relay_target && message.status !== "delivered"
        ? ` · ${message.relay_copies}/${message.relay_target} relay copies`
        : "";
    meta.title =
      status.label +
      relay +
      (message.queue_error ? " · " + message.queue_error : "");
    if (message.queued) {
      const cancel = document.createElement("button");
      cancel.type = "button";
      cancel.className = "message-cancel";
      cancel.textContent = "×";
      cancel.setAttribute("aria-label", "Stop retries");
      cancel.title =
        "Stops pending work; already delivered copies cannot be recalled";
      /** Cancel this queued outgoing message and refresh its displayed state. */
      cancel.onclick = async () => {
        try {
          await api("messaging/cancel", {
            owner: model.active.id,
            id: message.id,
          });
          await refreshHistory();
          renderMessages();
        } catch (error) {
          showToast(error.message);
        }
      };
      meta.append(cancel);
    }
    bubble.append(content);
    for (const item of message.attachments || [])
      bubble.append(attachmentView(model.active.id, message.id, item));
    bubble.append(meta);
    box.append(bubble);
  }
  const hit =
    searchContext?.focusPending &&
    [...box.children].find(
      (bubble) => bubble.dataset.messageId === searchContext.focusId,
    );
  if (hit) {
    hit.scrollIntoView({ block: "center" });
    searchContext.focusPending = false;
  } else if (atBottom || !box.dataset.loaded) box.scrollTop = box.scrollHeight;
  box.dataset.loaded = "true";
}

/** Open the destination form for starting a new conversation. */
export function showCompose() {
  const modal = $("compose-dialog");
  modal.innerHTML = `<div class="dialog-top"><h2>New conversation</h2>
    <button data-close aria-label="Close">×</button></div>
    <form id="conversation-form"><label>LXMF destination address
    <input id="destination" placeholder="32 hexadecimal characters" maxlength="32" required autocomplete="off"></label>
    <p class="muted">Use the recipient’s messaging address, not their identity hash.</p>
    <p class="error" id="compose-error"></p><button class="primary">Open conversation</button></form>
    ${model.ownAddress ? `<p class="muted">Your messaging address:</p><p class="address-text">${escapeHTML(model.ownAddress)}</p>` : ""}`;
  /** Validate the destination before opening its conversation. */
  $("conversation-form").onsubmit = (event) => {
    event.preventDefault();
    const peer = $("destination").value.trim().toLowerCase();
    if (!/^[0-9a-f]{32}$/.test(peer)) {
      $("compose-error").textContent =
        "Enter a valid 32-character hexadecimal LXMF address.";
      return;
    }
    if (peer === model.ownAddress) {
      $("compose-error").textContent =
        "Choose another identity’s messaging address.";
      return;
    }
    modal.close();
    openConversation(peer);
  };
  showDialog("compose-dialog");
}

/** Discard private attachment drafts when leaving an identity. */
export function clearMessageDraft() {
  clearTimeout(searchTimer);
  searchVersion++;
  contextVersion++;
  searchState = { key: "", matches: [] };
  searchContext = null;
  selectedFiles = [];
  clearAttachmentPreviews();
}
