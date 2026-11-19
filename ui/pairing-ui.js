/** Pairing is always explicit: scan, review the desktop, choose identities, approve. */
import qrCode from "./vendor/qrcode.cjs";
import jsQR from "./vendor/jsqr.cjs";
import { $, api, model, showDialog, showToast } from "./core.js";

let timer;
let stream;
let scanFrame;
let remoteAtOpen = false;

function stopScan() {
  cancelAnimationFrame(scanFrame);
  stream?.getTracks().forEach((track) => track.stop());
  stream = null;
  $("pairing-camera").srcObject = null;
  $("pairing-camera").hidden = true;
}

function reviewCode() {
  try {
    const invite = JSON.parse($("pairing-code").value);
    if (invite.cixnet !== 1 || !invite.name || !invite.public)
      throw new Error();
    $("pairing-review").textContent =
      `Connect to ${invite.name} at ${invite.host}:${invite.port}. Desktop fingerprint: ${invite.destination}. Approving shares the selected identities' saved conversations, files, browser and settings. Private identity keys stay on this phone. Only approve a code shown by your own computer.`;
    $("pairing-approve").disabled = false;
  } catch {
    $("pairing-review").textContent =
      "Scan the desktop's ciXnet code, or paste its pairing code below.";
    $("pairing-approve").disabled = true;
  }
}

async function refresh() {
  const state = await api("pairing/status");
  const banner = $("paired-banner");
  banner.hidden = !state.remote;
  document.body.classList.toggle("using-phone", Boolean(state.remote));
  $("paired-label").textContent = state.remote
    ? `Using phone · ${state.remote.name}${state.connected ? "" : " · disconnected"}`
    : "";
  if (!$("pairing-dialog").open) return;
  $("pairing-status").textContent =
    state.error ||
    (state.busy
      ? "Connecting…"
      : state.connected
        ? "Phone connected. Open phone client to continue."
        : state.serving
          ? "Desktop connected. Revoke its access below when needed."
          : "Your receiver keeps running independently.");
  const host = $("pairing-host");
  if (!host.options.length)
    for (const address of state.addresses)
      host.add(new Option(address, address));
  $("paired-devices").replaceChildren();
  if (!state.devices.length) {
    const empty = document.createElement("p");
    empty.className = "pairing-help";
    empty.textContent = "No paired devices yet.";
    $("paired-devices").append(empty);
  }
  for (const device of state.devices) {
    const row = document.createElement("div");
    row.className = "paired-device";
    const name = document.createElement("span");
    name.textContent = device.name;
    const revoke = document.createElement("button");
    revoke.type = "button";
    revoke.textContent = "Revoke";
    revoke.onclick = async () => {
      try {
        await api("pairing/revoke", { id: device.id });
        await refresh();
      } catch (error) {
        showToast(error.message);
      }
    };
    row.append(name, revoke);
    $("paired-devices").append(row);
  }
  $("pairing-use-phone").hidden = !state.connected;
  if (state.connected && !remoteAtOpen)
    $("pairing-status").textContent =
      "Phone approved and connected. Open phone client to see its identities and saved messages.";
}

function selectMode(phone) {
  stopScan();
  $("pairing-computer").hidden = phone;
  $("pairing-phone").hidden = !phone;
  $("pairing-computer-tab").setAttribute("aria-selected", String(!phone));
  $("pairing-phone-tab").setAttribute("aria-selected", String(phone));
}

async function open() {
  remoteAtOpen = !$("paired-banner").hidden;
  $("pairing-owners").replaceChildren();
  if (!remoteAtOpen)
    for (const profile of model.profiles) {
      const label = document.createElement("label");
      const input = document.createElement("input");
      input.type = "checkbox";
      input.value = profile.id;
      input.checked = !profile.locked;
      input.disabled = Boolean(profile.locked);
      label.append(
        input,
        document.createTextNode(
          ` ${profile.display_name || profile.nickname}${profile.locked ? " (unlock on phone first)" : ""}`,
        ),
      );
      $("pairing-owners").append(label);
    }
  selectMode(/Android/i.test(navigator.userAgent));
  showDialog("pairing-dialog");
  await refresh();
  clearInterval(timer);
  timer = setInterval(
    () =>
      refresh().catch((error) => {
        $("pairing-status").textContent = error.message;
      }),
    2000,
  );
}

export function initPairing() {
  $("pairing-computer-tab").onclick = () => selectMode(false);
  $("pairing-phone-tab").onclick = () => selectMode(true);
  for (const id of ["pairing-computer-tab", "pairing-phone-tab"]) {
    $(id).onkeydown = (event) => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key))
        return;
      event.preventDefault();
      const phone =
        event.key === "End" ||
        (event.key !== "Home" && $("pairing-phone").hidden);
      selectMode(phone);
      $(phone ? "pairing-phone-tab" : "pairing-computer-tab").focus();
    };
  }
  for (const id of ["pairing-open", "settings-pairing"])
    $(id).onclick = () => open().catch((error) => showToast(error.message));
  $("pairing-dialog").addEventListener("close", () => {
    clearInterval(timer);
    stopScan();
  });
  $("pairing-code").oninput = reviewCode;
  $("pairing-create").onclick = async () => {
    try {
      const result = await api("pairing/invite", {
        host: $("pairing-host").value,
        name: $("pairing-name").value,
        allowFirewall: $("pairing-firewall").checked,
      });
      const qr = qrCode(0, "M");
      qr.addData(result.code);
      qr.make();
      $("pairing-qr").src = qr.createDataURL(4, 12);
      $("pairing-qr").hidden = false;
      $("pairing-export").value = result.code;
      $("pairing-instructions").textContent =
        `Scan with ciXnet on the phone within 5 minutes. Keep this window open. If Windows asks, allow TCP port ${result.port} on your private LAN only. No VPN is needed. ${result.firewall || ""}`;
    } catch (error) {
      $("pairing-status").textContent = error.message;
    }
  };
  $("pairing-scan").onclick = async () => {
    stopScan();
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: "environment" } },
        audio: false,
      });
      if (!$("pairing-dialog").open) {
        stopScan();
        return;
      }
      const video = $("pairing-camera");
      video.srcObject = stream;
      video.hidden = false;
      await video.play();
      const canvas = document.createElement("canvas");
      const context = canvas.getContext("2d", { willReadFrequently: true });
      let last = 0;
      const scan = (now) => {
        if (!stream || !$("pairing-dialog").open) return;
        if (video.videoWidth && now - last > 200) {
          last = now;
          canvas.width = Math.min(800, video.videoWidth);
          canvas.height = Math.round(
            (video.videoHeight * canvas.width) / video.videoWidth,
          );
          context.drawImage(video, 0, 0, canvas.width, canvas.height);
          const image = context.getImageData(0, 0, canvas.width, canvas.height);
          const code = jsQR(image.data, image.width, image.height);
          if (code) {
            $("pairing-code").value = code.data;
            stopScan();
            reviewCode();
            return;
          }
        }
        scanFrame = requestAnimationFrame(scan);
      };
      scanFrame = requestAnimationFrame(scan);
    } catch (error) {
      stopScan();
      $("pairing-status").textContent =
        "Camera unavailable. You can paste the desktop pairing code instead.";
    }
  };
  $("pairing-approve").onclick = async () => {
    const owners = [
      ...$("pairing-owners").querySelectorAll("input:checked"),
    ].map((input) => input.value);
    try {
      await api("pairing/connect", {
        code: $("pairing-code").value,
        owners,
        name: "ciXnet phone",
      });
      $("pairing-status").textContent = "Connecting to approved desktop…";
    } catch (error) {
      $("pairing-status").textContent = error.message;
    }
  };
  $("pairing-use-phone").onclick = () => location.reload();
  $("paired-disconnect").onclick = async () => {
    try {
      await api("pairing/disconnect", {});
      location.reload();
    } catch (error) {
      showToast(error.message);
    }
  };
  refresh().catch(() => {});
}
