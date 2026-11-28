/** Attachment selection and authenticated downloads. Remote files never execute. */
import { apiResponse } from "./core.js";
import { saveBlob, offerPhotoSave } from "./downloads.js";

export const MAX_ATTACHMENT_BYTES = 8 * 1024 * 1024;

/** Fit an image within the chosen edge limit without stretching or upscaling it. */
export function fittedDimensions(width, height, maxEdge) {
  const scale = Math.min(1, maxEdge / Math.max(width, height));
  return {
    width: Math.max(1, Math.round(width * scale)),
    height: Math.max(1, Math.round(height * scale)),
  };
}

/** Work on a new file; never overwrite the user's original photograph. */
export async function reduceImage(file, maxEdge) {
  const bitmap = await createImageBitmap(file);
  try {
    const size = fittedDimensions(bitmap.width, bitmap.height, maxEdge);
    const canvas = document.createElement("canvas");
    canvas.width = size.width;
    canvas.height = size.height;
    canvas.getContext("2d").drawImage(bitmap, 0, 0, size.width, size.height);
    const blob = await new Promise((resolve) =>
      canvas.toBlob(resolve, "image/webp", 0.8),
    );
    if (!blob) throw new Error("This image could not be reduced.");
    // Some browsers fall back to PNG. Use the actual encoder output format.
    const extension = blob.type === "image/webp" ? "webp" : "png";
    if (blob.size >= file.size) return file;
    return new File(
      [blob],
      `${file.name.replace(/\.[^.]+$/, "")}.${extension}`,
      { type: blob.type },
    );
  } finally {
    bitmap.close();
  }
}

/** Format an attachment size with a readable binary unit. */
export function formatSize(bytes) {
  return bytes < 1024
    ? `${bytes} B`
    : bytes < 1024 * 1024
      ? `${(bytes / 1024).toFixed(1)} KiB`
      : `${(bytes / (1024 * 1024)).toFixed(1)} MiB`;
}

/** Enforce attachment count and total-size limits before creating a draft. */
export function validateSelection(files) {
  if (files.length > 8) throw new Error("Choose at most 8 attachments.");
  if (files.reduce((sum, file) => sum + file.size, 0) > MAX_ATTACHMENT_BYTES)
    throw new Error("Attachments must total at most 8 MiB per message.");
}

/** Read an attachment into the bounded upload representation used by the API. */
export function encodeFile(file, image) {
  return new Promise((resolve, reject) => {
    /** Bridge FileReader completion and failure into the upload promise. */

    const reader = new FileReader();
    /** Reject the pending upload conversion when the browser cannot read the file. */
    reader.onerror = () => reject(new Error(`Could not read ${file.name}`));
    /** Return the selected file's name, encoded bytes and image flag. */
    reader.onload = () =>
      resolve({ name: file.name, data: reader.result.split(",")[1], image });
    reader.readAsDataURL(file);
  });
}

/** Fetch file bytes through the authenticated, owner-scoped attachment endpoint. */
async function fetchAttachment(owner, message, position) {
  const response = await apiResponse("messaging/attachment", {
    owner,
    message,
    position,
  });
  if (!response.ok)
    throw new Error((await response.json()).error || "Attachment unavailable");
  return response.blob();
}

let previewURLs = [];
/** Release object URLs retained by the previous conversation's previews. */
export function clearAttachmentPreviews() {
  previewURLs.forEach((url) => URL.revokeObjectURL(url));
  previewURLs = [];
}

/** Build an attachment row with explicit download and optional preview controls. */
export function attachmentView(owner, message, item) {
  const row = document.createElement("div");
  row.className = "attachment";
  const label = document.createElement("span");
  label.textContent = `${item.name} · ${formatSize(item.size)}`;
  const download = document.createElement("button");
  download.type = "button";
  download.textContent = "Download";
  const error = document.createElement("small");
  error.className = "error";
  /** Fetch the attachment once and present either a raster preview or a download. */
  async function load(button, preview) {
    button.disabled = true;
    error.textContent = "";
    try {
      const blob = await fetchAttachment(owner, message, item.position);
      // A conversation/identity switch must not paint late data into a new view.
      if (!row.isConnected) return;
      const url = URL.createObjectURL(blob);
      if (preview) {
        previewURLs.push(url);
        const image = document.createElement("img");
        image.alt = item.name;
        image.className = "message-image";
        image.src = url;
        offerPhotoSave(image, async () => blob, item.name);
        row.append(image);
        button.remove();
      } else {
        URL.revokeObjectURL(url);
        await saveBlob(blob, item.name);
      }
    } catch (failure) {
      error.textContent = failure.message;
    } finally {
      button.disabled = false;
    }
  }
  /** Download this attachment without opening an inline preview. */
  download.onclick = () => load(download, false);
  row.append(label, download);
  if (item.image) {
    const preview = document.createElement("button");
    preview.type = "button";
    preview.textContent = "Show image";
    /** Load a permitted image preview for this attachment. */
    preview.onclick = () => load(preview, true);
    row.append(preview);
  }
  row.append(error);
  return row;
}
