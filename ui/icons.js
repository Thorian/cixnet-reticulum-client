/** Offline MDI rendering and search. Assets keep their upstream license. */
import { $, escapeHTML } from "./core.js";
let iconCatalog = {};
const avatarPalette = {
  green: ["70e7a3", "2e503c"],
  teal: ["9de9de", "204d49"],
  blue: ["b4d5ff", "254566"],
  amber: ["ffdc9b", "574326"],
  purple: ["e1bdff", "49335f"],
  rose: ["ffbfd9", "60364b"],
};
export function iconMarkup(profile) {
  // Resolve only known icon names and validated RGB colors, never remote markup.
  const colors = avatarPalette[profile.color] || avatarPalette.green;
  const fg = /^[0-9a-f]{6}$/i.test(profile.foreground || "")
    ? profile.foreground
    : colors[0];
  const bg = /^[0-9a-f]{6}$/i.test(profile.background || "")
    ? profile.background
    : colors[1];
  const glyph = iconCatalog[profile.icon] || iconCatalog.account || "•";
  return `<svg viewBox="0 0 64 64" aria-hidden="true"><rect width="64" height="64" rx="16" fill="#${bg}"/><text class="mdi-glyph" x="32" y="34" text-anchor="middle" dominant-baseline="central" fill="#${fg}">${escapeHTML(glyph)}</text></svg>`;
}
/** Replace the avatar's contents using the safe bundled icon renderer. */
export function applyAvatar(element, profile) {
  element.innerHTML = iconMarkup(profile);
}
/** Render matching bundled icons and bind an explicit selection action. */
export function renderIconChoices(onSelect) {
  const query = $("manage-icon-search").value.trim().toLowerCase();
  const favorites = [
    "account",
    "account-circle",
    "pine-tree",
    "satellite-variant",
    "radio-handheld",
    "antenna",
    "compass",
    "shield-outline",
    "medical-bag",
    "ambulance",
    "fire-truck",
    "home",
    "tent",
    "hiking",
    "binoculars",
    "fox",
    "cat",
    "dog",
    "owl",
    "earth",
    "mountain",
    "lighthouse",
    "sail-boat",
    "car",
    "bike",
    "star",
    "lightning-bolt",
    "wrench",
    "hammer-wrench",
    "tools",
    "access-point",
    "wifi",
    "lan",
    "server",
    "book-open-page-variant",
    "flower",
    "leaf",
    "paw",
    "rocket-launch",
    "robot",
  ];
  const names = query
    ? Object.keys(iconCatalog)
        .filter((name) => name.includes(query))
        .slice(0, 100)
    : favorites.filter((name) => iconCatalog[name]);
  $("icon-grid").replaceChildren();
  names.forEach((name) => {
    /** Create one accessible choice for the corresponding bundled icon. */

    const button = document.createElement("button");
    button.type = "button";
    button.className = "icon-choice";
    button.title = name;
    button.setAttribute("aria-label", name);
    button.setAttribute(
      "aria-pressed",
      String($("manage-icon").value === name),
    );
    button.innerHTML = `<span class="mdi-glyph">${escapeHTML(iconCatalog[name])}</span>`;
    /** Select this icon and refresh both the preview and picker state. */
    button.onclick = () => {
      $("manage-icon").value = name;
      onSelect();
      renderIconChoices(onSelect);
    };
    $("icon-grid").append(button);
  });
  $("icon-count").textContent = query
    ? `${names.length} shown · ${Object.keys(iconCatalog).length.toLocaleString()} bundled icons`
    : `Suggested icons · ${Object.keys(iconCatalog).length.toLocaleString()} available by search`;
}
/** Load the bundled icon catalog before allowing avatar selection. */
export async function loadIcons() {
  const response = await fetch("vendor/mdi/icons.json");
  if (!response.ok)
    throw new Error("The bundled icon catalog could not be loaded.");
  iconCatalog = await response.json();
}

/** Return a bundled glyph for compact controls without the avatar background. */
export function serviceIcon(name) {
  return `<span class="mdi-glyph" aria-hidden="true">${escapeHTML(iconCatalog[name] || iconCatalog.web || "•")}</span>`;
}
