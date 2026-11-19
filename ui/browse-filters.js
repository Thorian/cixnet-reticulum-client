/** Browse filters apply to discovered nodes; bookmarks remain visible. */
export const browseKinds = [
  { kind: "lxmf", label: "Stations", icon: "account" },
  { kind: "node", label: "NomadNet", icon: "text-box-outline" },
  { kind: "nomadpl", label: "NomadPL", icon: "web" },
];
const storageKey = "cixnet-browse-kinds";
export function loadBrowseKinds(storage) {
  try {
    const saved = JSON.parse(storage.getItem(storageKey));
    if (Array.isArray(saved))
      return new Set(
        saved.filter((kind) => browseKinds.some((item) => item.kind === kind)),
      );
  } catch {
    /* Use all services if preferences are unavailable. */
  }
  return new Set(browseKinds.map((item) => item.kind));
}
export function saveBrowseKinds(storage, selected) {
  try {
    storage.setItem(storageKey, JSON.stringify([...selected]));
  } catch {
    /* Filtering still works when browser storage is unavailable. */
  }
}
export function discoveredNodes(announces, selected) {
  return announces
    .filter((item) => selected.has(item.kind))
    .sort(
      (a, b) =>
        (a.display_name || "Unnamed station").localeCompare(
          b.display_name || "Unnamed station",
          undefined,
          { sensitivity: "base", numeric: true },
        ) || a.address.localeCompare(b.address),
    );
}
