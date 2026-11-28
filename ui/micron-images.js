import { api, apiResponse, model } from "./core.js";
import { offerPhotoSave } from "./downloads.js";

/** Raster signatures prevent remote HTML or SVG from becoming app content. */
export function imageMime(bytes) {
  const starts = (values) =>
    values.every((value, index) => bytes[index] === value);
  if (starts([137, 80, 78, 71, 13, 10, 26, 10])) return "image/png";
  if (starts([255, 216, 255])) return "image/jpeg";
  const text = (start, end) => String.fromCharCode(...bytes.slice(start, end));
  if (["GIF87a", "GIF89a"].includes(text(0, 6))) return "image/gif";
  if (text(0, 4) === "RIFF" && text(8, 12) === "WEBP") return "image/webp";
  return null;
}

export const AUTO_IMAGE_BYTES = 64 * 1024;
// Serialize image jobs because the native browser permits one request per identity.
let imageQueue = Promise.resolve();

/** Keep recent image bytes within a shared budget across browser histories. */
export function trimImageCaches(pages, limit = 16 * 1024 * 1024) {
  let retained = 0;
  for (const page of [...pages].reverse()) {
    if (!page.images) continue;
    for (const [target, blob] of page.images) {
      if (retained + blob.size > limit) page.images.delete(target);
      else retained += blob.size;
    }
  }
}

/** Native file transfers are explicit on slow links and cached with page history. */
export function loadMicronImage(page, target, image, trimCache = () => {}) {
  // NomadNet uses :/path for an asset on the current node.
  if (target.startsWith(":/")) target = target.slice(1);
  const owner = model.active.id;
  const active = () => image.isConnected && model.active?.id === owner;
  page.images ||= new Map();
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = "Load image";
  image.after(button);
  const load = async (automatic = false) => {
    if (!active()) return;
    button.disabled = true;
    button.textContent = "Loading image…";
    let request;
    try {
      if (!/^(?:[0-9a-f]{32}:)?\/(?:file|media)\//i.test(target))
        throw new Error("Image must use a native /media/ or /file/ address");
      let blob = page.images.get(target);
      if (!blob) {
        if (page.images.size >= 8) throw new Error("Page image limit reached");
        const job = await api("browser/open", {
          owner,
          url: target,
          base: page.resolved || page.url,
          identify: page.identify,
          max_bytes: automatic ? AUTO_IMAGE_BYTES : null,
        });
        request = { owner, id: job.id };
        for (;;) {
          if (!active()) return;
          const result = await api("browser/status", request);
          if (result.phase === "done") {
            if (!result.download)
              throw new Error("The image did not return a file");
            const response = await apiResponse("browser/download", request);
            if (!response.ok) throw new Error("Could not retrieve image");
            const bytes = new Uint8Array(await response.arrayBuffer());
            const mime = imageMime(bytes);
            if (!mime) throw new Error("Unsupported image format");
            const total = [...page.images.values()].reduce(
              (sum, item) => sum + item.size,
              0,
            );
            if (total + bytes.length > 8 * 1024 * 1024 || page.images.size >= 8)
              throw new Error("Page image limit reached");
            blob = new Blob([bytes], { type: mime });
            page.images.set(target, blob);
            trimCache();
            break;
          }
          if (["error", "cancelled"].includes(result.phase))
            throw new Error(result.error || "Image request cancelled");
          await new Promise((resolve) => setTimeout(resolve, 700));
        }
      }
      if (!active()) return;
      const url = URL.createObjectURL(blob);
      image.onload = () => URL.revokeObjectURL(url);
      image.onerror = () => {
        URL.revokeObjectURL(url);
        button.hidden = false;
        button.textContent = "Image could not be decoded";
      };
      image.src = url;
      offerPhotoSave(
        image,
        async () => blob,
        target.split("/").pop() || "photo",
      );
      button.hidden = true;
    } catch (error) {
      if (active()) {
        button.textContent = automatic
          ? "Load image (larger or unavailable)"
          : error.message;
        button.disabled = false;
      }
    } finally {
      if (request) api("browser/cancel", request).catch(() => {});
    }
  };
  const enqueue = (automatic) => {
    button.disabled = true;
    imageQueue = imageQueue.catch(() => {}).then(() => load(automatic));
  };
  button.onclick = () => enqueue(false);
  // Each rendered image gets a fresh automatic attempt; successful bytes stay cached.
  // The response-size limit, rather than image order, decides what needs a click.
  enqueue(!page.images.has(target));
}
