/** Saved public radio advertisements; positions are used locally, never announced. */
import { $, api, model, escapeHTML, showDialog } from "./core.js";
import { stationLocation } from "./station-location.js";

export function initStations() {
  const dialog = document.createElement("dialog");
  dialog.id = "stations-dialog";
  dialog.innerHTML = `<div class="dialog-top"><h2>Radio stations</h2><button type="button" aria-label="Close">×</button></div>
    <p>Nearby radio profiles to try. An advertisement does not confirm reception or coverage.</p>
    <label>Latitude<input id="stations-lat" type="number" min="-90" max="90" step="any"></label>
    <label>Longitude<input id="stations-lon" type="number" min="-180" max="180" step="any"></label>
    <button type="button" id="stations-sort">Sort by distance</button>
    <button type="button" id="stations-locate">Use my location</button>
    <p id="stations-location-status" role="status"></p>
    <p class="muted">Position stays on this client. Leave both fields empty to sort by last heard.</p>
    <button type="button" id="stations-web">Update from ciXnet</button>
    <label>Import compiled list<input type="file" id="stations-file" accept=".json,application/json"></label>
    <label>Reticulum file address<input id="stations-url" placeholder="destination:/file/stations-v1.json"></label>
    <button type="button" id="stations-radio">Fetch list over Reticulum</button>
    <p class="muted">Updates use bandwidth. Reticulum files may be up to 4 MiB; allow time on slow links. No automatic refresh or tuning.</p>
    <p id="stations-status" role="status"></p><div id="stations-results"></div>`;
  document.body.append(dialog);
  dialog.querySelector("button").onclick = () => dialog.close();
  let timer;
  let locationRequest;
  dialog.addEventListener("close", () => {
    clearTimeout(timer);
    locationRequest?.cancel();
  });
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) locationRequest?.cancel();
  });
  async function render() {
    const lat = $("stations-lat").value.trim();
    const lon = $("stations-lon").value.trim();
    const position =
      lat || lon
        ? {
            latitude: lat ? Number(lat) : null,
            longitude: lon ? Number(lon) : null,
          }
        : {};
    try {
      const result = await api("stations/list", position);
      $("stations-status").textContent =
        `${result.stations.length} stations · ${result.profiles.length} radio profiles. Directory: ${result.compiled_at ? new Date(result.compiled_at * 1000).toLocaleDateString() : "not imported"}. ${result.refresh.phase === "loading" ? "Updating…" : result.refresh.error || ""}`;
      $("stations-results").innerHTML =
        result.stations
          .slice(0, 200)
          .map(
            (
              s,
            ) => `<article class="announce-item"><strong>${escapeHTML(s.name)}</strong>
        <p>${s.distance_km === undefined ? "" : `${s.distance_km} km · `}${s.frequency / 1e6} MHz · ${s.bandwidth / 1000} kHz · SF${s.sf} · 4/${s.cr}</p>
        <small>${escapeHTML(s.sources.join(" + "))} · advertised · last heard ${escapeHTML(new Date(s.last_seen * 1000).toLocaleString())}</small>
        <details><summary>Radio profile</summary><pre>${escapeHTML(JSON.stringify({ frequency: s.frequency, bandwidth: s.bandwidth, spreadingfactor: s.sf, codingrate: s.cr }, null, 2))}</pre></details></article>`,
          )
          .join("") ||
        "No stations saved yet. Compatible discovery announces will be learned while the receiver runs.";
      if (result.stations.length > 200)
        $("stations-results").insertAdjacentText(
          "beforeend",
          "Showing the first 200 stations. Enter a position to see the nearest first.",
        );
      if (result.refresh.phase === "loading" && dialog.open)
        timer = setTimeout(render, 1000);
    } catch (error) {
      $("stations-status").textContent = error.message;
    }
  }
  $("stations-open").onclick = () => {
    showDialog("stations-dialog");
    render();
  };
  $("stations-sort").onclick = render;
  $("stations-locate").onclick = async () => {
    const button = $("stations-locate");
    button.disabled = true;
    $("stations-location-status").textContent = "Getting your location…";
    locationRequest = stationLocation(navigator.geolocation);
    try {
      const position = await locationRequest.promise;
      if (!dialog.open) return;
      $("stations-lat").value = position.latitude;
      $("stations-lon").value = position.longitude;
      $("stations-location-status").textContent =
        `Position accuracy: about ${Math.ceil(position.accuracy)} m. Used locally; not announced.`;
      await render();
    } catch (error) {
      $("stations-location-status").textContent = error.message;
    } finally {
      locationRequest = null;
      button.disabled = false;
    }
  };
  $("stations-web").onclick = async () => {
    try {
      await api("stations/refresh", {});
      await render();
    } catch (error) {
      $("stations-status").textContent = error.message;
    }
  };
  $("stations-file").onchange = async (event) => {
    const file = event.target.files[0];
    if (!file) return;
    try {
      if (file.size > 4 * 1024 * 1024)
        throw new Error("Station list exceeds 4 MiB");
      await api("stations/import", { document: await file.text() });
      await render();
    } catch (error) {
      $("stations-status").textContent = error.message;
    } finally {
      event.target.value = "";
    }
  };
  $("stations-radio").onclick = async () => {
    const button = $("stations-radio");
    button.disabled = true;
    try {
      const owner = model.active.id;
      let job = await api("browser/open", {
        owner,
        url: $("stations-url").value,
      });
      while (!["done", "error", "cancelled"].includes(job.phase)) {
        if (!dialog.open) {
          await api("browser/cancel", { owner, id: job.id });
          return;
        }
        $("stations-status").textContent = `Reticulum list: ${job.phase}`;
        await new Promise((resolve) => setTimeout(resolve, 1000));
        job = await api("browser/status", { owner, id: job.id });
      }
      if (job.phase !== "done")
        throw new Error(job.error || "Transfer cancelled");
      await api("stations/from-download", { owner, id: job.id });
      await render();
    } catch (error) {
      $("stations-status").textContent = error.message;
    } finally {
      button.disabled = false;
    }
  };
}
