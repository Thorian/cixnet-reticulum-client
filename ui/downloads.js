import { showToast } from "./core.js";

let nativePort;
let activeDialog;
const pending = new Map();

function progress(name, received, total, phase = "Downloading") {
  if (!activeDialog) {
    activeDialog = document.createElement("dialog");
    const title = document.createElement("p");
    const bar = document.createElement("progress");
    const close = document.createElement("button");
    close.textContent = "Hide";
    close.onclick = () => activeDialog.close();
    activeDialog.append(title, bar, close);
    document.body.append(activeDialog);
    activeDialog.showModal();
  }
  activeDialog.querySelector("p").textContent =
    `${phase}: ${name}${total ? ` · ${Math.min(100, Math.floor((received / total) * 100))}%` : "…"}`;
  const bar = activeDialog.querySelector("progress");
  bar.max = total || 1;
  if (total) bar.value = received;
  else bar.removeAttribute("value");
}

export function downloadProgress(name, received, total) {
  progress(name || "File", received || 0, total || 0);
}

export function finishDownload(error) {
  activeDialog?.remove();
  activeDialog = null;
  if (error) showToast(error);
}

function nativeRequest(message) {
  return new Promise((resolve, reject) => {
    const request = crypto.randomUUID();
    const timeout = setTimeout(() => {
      pending.delete(request);
      reject(new Error("Android did not finish saving the file"));
    }, 30000);
    pending.set(request, (reply) => {
      clearTimeout(timeout);
      reply.error ? reject(new Error(reply.error)) : resolve(reply);
    });
    nativePort.postMessage(JSON.stringify({ ...message, request }));
  });
}

/** The native port is delivered only to the trusted top-level client origin. */
export function initDownloads() {
  addEventListener("message", (event) => {
    const token = document.documentElement.dataset.downloadToken;
    if (!token || event.data !== token || !event.ports?.length) return;
    nativePort?.close();
    nativePort = event.ports[0];
    delete document.documentElement.dataset.downloadToken;
    nativePort.onmessage = ({ data }) => {
      const reply = JSON.parse(data);
      pending.get(reply.request)?.(reply);
      pending.delete(reply.request);
    };
    nativePort.start();
  });
}

/** Stream bounded chunks into Android's public Downloads collection. */
export async function saveBlob(blob, name = "download") {
  const id = crypto.randomUUID();
  try {
    if (nativePort) {
      progress(name, 0, blob.size, "Saving to Downloads/ciXnet");
      await nativeRequest({
        action: "begin",
        id,
        name,
        mime: blob.type,
        size: blob.size,
      });
      for (let offset = 0; offset < blob.size; offset += 32768) {
        const bytes = new Uint8Array(
          await blob.slice(offset, offset + 32768).arrayBuffer(),
        );
        await nativeRequest({
          action: "chunk",
          id,
          data: btoa(String.fromCharCode(...bytes)),
        });
        progress(
          name,
          offset + bytes.length,
          blob.size,
          "Saving to Downloads/ciXnet",
        );
      }
      await nativeRequest({ action: "finish", id });
      showToast("Saved to Downloads/ciXnet");
    } else {
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = name;
      document.body.append(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 30000);
    }
  } catch (error) {
    if (nativePort)
      await nativeRequest({ action: "cancel", id }).catch(() => {});
    showToast(error.message);
    throw error;
  } finally {
    finishDownload();
  }
}

export function offerPhotoSave(image, load, name) {
  image.addEventListener("contextmenu", (event) => {
    event.preventDefault();
    const dialog = document.createElement("dialog");
    const save = document.createElement("button");
    save.textContent = "Save photo";
    const cancel = document.createElement("button");
    cancel.textContent = "Cancel";
    cancel.onclick = () => dialog.close();
    save.onclick = async () => {
      dialog.close();
      try {
        await saveBlob(await load(), name);
      } catch {
        /* Reported by saveBlob. */
      }
    };
    dialog.onclose = () => dialog.remove();
    dialog.append(save, cancel);
    document.body.append(dialog);
    dialog.showModal();
  });
}
