/** Recognise messaging destinations without treating arbitrary URLs as contacts. */
export function lxmfAddress(value) {
  if (typeof value !== "string" || value.length > 2048) return null;
  const link = value.trim();
  const match =
    link.match(/^lxmf(?:\.delivery)?@([0-9a-f]{32})$/i) ||
    link.match(/^lxmf:(?:\/\/)?([0-9a-f]{32})\/?(?:[?#].*)?$/i);
  return match ? match[1].toLowerCase() : null;
}
