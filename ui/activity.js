/** Visible feedback for user actions, independent of background polling. */
const activities = new Map();
let indicator;
let clock;

function paint() {
  if (!indicator) {
    indicator = document.createElement("div");
    indicator.className = "activity-indicator";
    indicator.setAttribute("role", "status");
    indicator.setAttribute("aria-live", "polite");
    const label = document.createElement("span");
    label.className = "activity-label";
    const elapsed = document.createElement("span");
    elapsed.className = "activity-elapsed";
    elapsed.setAttribute("aria-hidden", "true");
    indicator.append(label, elapsed);
  }
  const entries = [...activities.values()];
  indicator.hidden = !entries.length;
  if (!entries.length) return;
  // A modal is in the browser's top layer; keep its feedback there too.
  const dialogs = document.querySelectorAll("dialog[open]");
  const host = dialogs[dialogs.length - 1] || document.body;
  if (indicator.parentElement !== host) host.append(indicator);
  const latest = entries[entries.length - 1];
  indicator.querySelector(".activity-label").textContent = latest.label + "…";
  const seconds = Math.floor((Date.now() - latest.started) / 1000);
  indicator.querySelector(".activity-elapsed").textContent = seconds
    ? `${seconds}s`
    : "";
}

/** Return an idempotent completion function; always call it in finally. */
export function beginActivity(label) {
  const id = Symbol();
  activities.set(id, { label, started: Date.now() });
  paint();
  if (!clock) clock = setInterval(paint, 1000);
  return () => {
    activities.delete(id);
    paint();
    if (!activities.size) {
      clearInterval(clock);
      clock = null;
    }
  };
}
