/** OS authentication opens the interface; receiving stays in the service. */
import { $, model, api, showToast } from "./core.js";

let busy = false;

async function verify(profile, action) {
  if (busy) throw new Error("Finish the current Windows Hello prompt first");
  busy = true;
  try {
    const { job } = await api(`identity/protection/${action}`, {
      owner: profile.id,
    });
    showToast("Complete the Windows Hello prompt on your device");
    while (true) {
      const result = await api("identity/protection/result", {
        owner: profile.id,
        job,
      });
      if (result.state === "failed") throw new Error(result.error);
      if (result.state === "complete") return result;
      await new Promise((resolve) => setTimeout(resolve, 700));
    }
  } finally {
    busy = false;
  }
}

export async function ensureIdentityUnlocked(profile) {
  const status = await api("identity/protection/status", { owner: profile.id });
  if (status.locked && model.pairedPhone)
    throw new Error("Unlock this identity on your phone, then try again.");
  if (status.locked) await verify(profile, "unlock");
}

export async function refreshProtection() {
  if (!model.active) return;
  if (model.pairedPhone) {
    $("protection-enable").disabled = true;
    $("protection-disable").disabled = true;
    $("protection-status").textContent =
      "Manage identity protection directly on your phone.";
    return;
  }
  const status = await api("identity/protection/status", {
    owner: model.active.id,
  });
  $("protection-enable").disabled = status.protected || !status.available;
  $("protection-disable").disabled = !status.protected;
  $("protection-status").textContent = status.protected
    ? "Windows Hello protection is enabled for this identity."
    : status.available
      ? "Use your device's Windows Hello fingerprint, face or PIN verification."
      : "Windows Hello is available in the Windows desktop build. Android biometric integration will follow.";
}

export function initProtection() {
  for (const action of ["enable", "disable"]) {
    $(`protection-${action}`).onclick = async () => {
      try {
        await verify(model.active, action);
        await refreshProtection();
        showToast(
          action === "enable"
            ? "Identity protection enabled"
            : "Identity protection disabled",
        );
      } catch (error) {
        $("protection-status").textContent = error.message;
      }
    };
  }
}
