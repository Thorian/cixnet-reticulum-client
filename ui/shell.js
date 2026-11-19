/** Static client views. Planned services stay clearly labelled as unavailable. */
import { $, model, escapeHTML } from "./core.js";

/** Show the contacts welcome panel and its new-conversation action. */
export function renderWelcome(onCompose) {
  $("detail").innerHTML =
    `<div class="welcome"><div class="eyebrow small">WELCOME TO YOUR NETWORK</div>
    <h1>Good connections start here.</h1><p class="muted">A place for your people, wherever the network takes you.<br>
    Choose a contact to open a conversation.</p><button class="primary" id="welcome-compose">＋ New conversation</button>
    <div class="welcome-note"><span>◌</span><div id="welcome-status"></div></div></div>`;
  $("welcome-compose").onclick = onCompose;
  updateWelcomeStatus();
}

/** Refresh connectivity text without rebuilding the rest of the welcome view. */
export function updateWelcomeStatus() {
  if (!$("welcome-status")) return;
  const running = model.network.phase === "running";
  $("welcome-status").innerHTML = `<strong>Your identity is ready.</strong><br>
    Reticulum is ${escapeHTML(model.network.phase)}.
    ${running ? "LXMF direct messaging is enabled." : "Waiting for the local networking core."}`;
}

/** Explain discovery while the announcement list has no selected destination. */
export function renderAnnounceWelcome() {
  $("detail").innerHTML =
    `<div class="welcome"><div class="eyebrow small">NETWORK DISCOVERY</div>
    <h1>See who’s out there.</h1><p class="muted">Select a received announce to see its destination and identity.</p>
    <div class="welcome-note"><span>◌</span><div>Live announces appear as they arrive.
    An empty list means none have been received.</div></div></div>`;
}
