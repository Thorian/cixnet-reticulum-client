/** Profile editing and explicit key backup; keys are not retained in UI state. */
import { saveBlob } from "./downloads.js";
import {
  $,
  model,
  api,
  apiResponse,
  escapeHTML,
  showDialog,
  showToast,
} from "./core.js";
import { applyAvatar, iconMarkup, renderIconChoices } from "./icons.js";
import { ensureIdentityUnlocked } from "./protection-ui.js";
let onSelectIdentity;
let editingIdentity;
/** Refresh the visible nickname and avatar from the active local profile. */
export function syncIdentityUI() {
  if (!model.active) return;
  $("nickname").textContent = model.active.nickname;
  applyAvatar($("avatar"), model.active);
  $("avatar").dataset.tone = model.active.color || "green";
  $("identity-summary-label").textContent =
    model.active.display_name || model.active.nickname;
  document.title = model.active.nickname + " · ciXnet";
}
/** Show saved identities with separate selection and metadata-edit controls. */
export function renderProfiles() {
  $("profiles").replaceChildren();
  model.profiles.forEach((profile) => {
    /** Build one profile row with its own selection and editing actions. */

    const row = document.createElement("div");
    row.className = "identity-row";
    const select = document.createElement("button");
    select.className = "profile";
    select.innerHTML = `<span class="avatar">${iconMarkup(profile)}</span><span class="profile-label"><strong>${escapeHTML(profile.nickname)}</strong><small>${escapeHTML(profile.id)}</small><small>${profile.locked ? "Locked · Windows Hello" : `${profile.message_count || 0} saved messages`}</small></span><span>→</span>`;
    /** Activate this saved identity without opening its metadata editor. */
    select.onclick = () => onSelectIdentity(profile);
    const edit = document.createElement("button");
    edit.className = "profile-edit";
    edit.textContent = "✎";
    edit.title = "Manage " + profile.nickname;
    edit.setAttribute("aria-label", "Manage identity " + profile.nickname);
    /** Open this profile's editable metadata while preserving its keys. */
    edit.onclick = () => openIdentityManager(profile);
    row.append(select, edit);
    $("profiles").append(row);
  });
}
/** Populate the identity editor with the selected profile's saved metadata. */
export async function openIdentityManager(profile) {
  try {
    await ensureIdentityUnlocked(profile);
  } catch (error) {
    showToast(error.message);
    return;
  }
  editingIdentity = profile;
  $("manage-nickname").value = profile.nickname;
  $("manage-display").value = profile.display_name || profile.nickname;

  $("manage-icon").value = profile.icon || "account";
  $("manage-icon-search").value = "";
  $("manage-color").value = profile.color || "green";
  $("manage-address").textContent = profile.id;
  $("manage-error").textContent = "";
  previewIdentity();
  renderIconChoices(previewIdentity);
  $("manage-dialog").showModal();
}
/** Render the current icon and color draft without saving profile changes. */
function previewIdentity() {
  applyAvatar($("manage-preview-avatar"), {
    icon: $("manage-icon").value,
    color: $("manage-color").value,
  });
  $("manage-preview-name").textContent =
    $("manage-display").value || "Display name";
}
/** Bind profile creation, import, backup and metadata-edit actions. */
export function initIdentities({ onSelect }) {
  onSelectIdentity = onSelect;
  /** Edit the currently active identity's display metadata. */
  $("identity-manage").onclick = () => openIdentityManager(model.active);
  ["manage-nickname", "manage-display", "manage-color"].forEach((id) =>
    $(id).addEventListener("input", previewIdentity),
  );
  /** Validate and save profile metadata without replacing its private key. */
  $("manage-form").onsubmit = async (e) => {
    e.preventDefault();
    $("manage-save").disabled = true;
    $("manage-error").textContent = "";
    try {
      const result = await api("identity/update", {
        id: editingIdentity.id,
        nickname: $("manage-nickname").value,
        display_name: $("manage-display").value,
        symbol: "",
        icon: $("manage-icon").value,
        color: $("manage-color").value,
      });
      Object.assign(editingIdentity, result);
      renderProfiles();
      syncIdentityUI();
      $("manage-dialog").close();
      showToast("Identity updated");
    } catch (error) {
      $("manage-error").textContent = error.message;
    } finally {
      $("manage-save").disabled = false;
    }
  };
  $("manage-icon-search").addEventListener("input", () =>
    renderIconChoices(previewIdentity),
  );
  /** Switch from metadata editing to an explicit identity import. */
  $("manage-import").onclick = () => {
    $("manage-dialog").close();
    openIdentityForm(true);
  };
  /** Export alone returns private bytes; never log or persist them in browser storage. */
  $("manage-export").onclick = async () => {
    const button = $("manage-export");
    button.disabled = true;
    $("manage-error").textContent = "";
    try {
      const response = await apiResponse("identity/export", {
        id: editingIdentity.id,
      });
      if (!response.ok) throw Error("Identity export failed");
      const blob = await response.blob();
      await saveBlob(blob, "cixnet-" + editingIdentity.id + ".identity");
      showToast("Private identity file exported");
    } catch (error) {
      $("manage-error").textContent = error.message;
    } finally {
      button.disabled = false;
    }
  };

  /** Open the form for creating a new independent identity. */
  $("create-open").onclick = () => openIdentityForm(false);
  /** Open the form for restoring an existing identity key. */
  $("import-open").onclick = () => openIdentityForm(true);
  $("identity-form").onsubmit = submitIdentity;
}

let importMode = false;
/** Reset the identity form for either creation or explicit key import. */
export function openIdentityForm(importing) {
  importMode = importing;
  $("identity-form").reset();
  $("identity-error").textContent = "";
  const title = importing ? "Import identity" : "Create identity";
  $("identity-title").textContent = title;
  $("identity-submit").textContent = title;
  $("identity-description").textContent = importing
    ? "Import an existing raw Reticulum private identity file."
    : "Create a genuine Reticulum identity stored on this device.";
  $("import-field").classList.toggle("hidden", !importing);
  $("identity-file").required = importing;
  showDialog("identity-dialog");
}

/** Create or import the chosen identity and update the saved profile list. */
async function submitIdentity(event) {
  event.preventDefault();
  $("identity-error").textContent = "";
  $("identity-submit").disabled = true;
  try {
    const body = { nickname: $("identity-name").value };
    if (importMode) {
      const file = $("identity-file").files[0];
      if (!file || file.size !== 64)
        throw new Error(
          "Choose a raw 64-byte Reticulum private identity file.",
        );
      body.file = btoa(
        String.fromCharCode(...new Uint8Array(await file.arrayBuffer())),
      );
    }
    const profile = await api(
      `identity/${importMode ? "import" : "create"}`,
      body,
    );
    model.profiles.push(profile);
    renderProfiles();
    $("identity-dialog").close();
    await onSelectIdentity(profile);
  } catch (error) {
    $("identity-error").textContent = error.message;
  } finally {
    $("identity-submit").disabled = false;
  }
}
