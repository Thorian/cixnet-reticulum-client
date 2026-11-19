/** Camera access starts only after Take photo. Never retain an idle camera stream. */
export function stopCamera(stream) {
  stream?.getTracks().forEach((track) => track.stop());
}

/** Open capture controls and release the stream whenever the dialog is closed. */
export async function openCamera(onPhoto, onPicker) {
  const dialog = document.createElement("dialog");
  dialog.className = "camera-dialog";
  dialog.innerHTML = `<div class="dialog-top"><h2>Take a photo</h2><button type="button" aria-label="Close camera">×</button></div>
    <video autoplay muted playsinline aria-label="Camera preview"></video>
    <img class="camera-review" alt="Captured photo" hidden style="max-width:100%;max-height:55vh;object-fit:contain">
    <p class="camera-status" role="status">Starting camera…</p>
    <div class="camera-actions"><select aria-label="Camera direction"><option value="user">Front camera · selfie</option><option value="environment">Rear camera</option></select>
    <button type="button" class="primary camera-shutter" disabled>Take photo</button>
    <button type="button" class="camera-retake" hidden>Retake</button><button type="button" class="primary camera-use" hidden>Use photo</button>
    <button type="button" class="camera-picker">Use camera/file picker</button></div>`;
  const video = dialog.querySelector("video");
  const status = dialog.querySelector(".camera-status");
  const shutter = dialog.querySelector(".camera-shutter");
  const direction = dialog.querySelector("select");
  const review = dialog.querySelector(".camera-review");
  const retake = dialog.querySelector(".camera-retake");
  const use = dialog.querySelector(".camera-use");
  let captured = null;
  let previewURL = null;
  let stream = null;
  let attempt = 0;
  /** Close the capture dialog through its normal cleanup path. */
  dialog.querySelector('[aria-label="Close camera"]').onclick = () =>
    dialog.close();
  /** Invalidate pending camera startup and release active video resources. */
  dialog.onclose = () => {
    attempt++;
    stopCamera(stream);
    video.srcObject = null;
    if (previewURL) URL.revokeObjectURL(previewURL);
    dialog.remove();
  };
  /** Close the live camera and fall back to the platform's image picker. */
  dialog.querySelector(".camera-picker").onclick = () => {
    dialog.close();
    onPicker();
  };
  /** Acquire the chosen camera while ignoring results from superseded attempts. */
  async function start() {
    const currentAttempt = ++attempt;
    stopCamera(stream);
    shutter.disabled = true;
    status.textContent = "Starting camera…";
    try {
      if (!navigator.mediaDevices?.getUserMedia)
        throw new Error("Camera capture is unavailable in this browser.");
      const opened = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: direction.value } },
        audio: false,
      });
      if (!dialog.open || currentAttempt !== attempt) {
        stopCamera(opened);
        return;
      }
      stream = opened;
      video.srcObject = stream;
      await video.play();
      if (!dialog.open || currentAttempt !== attempt) return;
      shutter.disabled = false;
      status.textContent =
        "Nothing is sent until you attach and send the photo.";
    } catch (error) {
      if (dialog.open && currentAttempt === attempt) {
        stopCamera(stream);
        status.textContent =
          "Camera unavailable or permission declined. You can use the camera/file picker instead.";
      }
    }
  }
  direction.onchange = start;
  /** Capture a ready video frame and pass the resulting image to the draft. */
  shutter.onclick = async () => {
    shutter.disabled = true;
    try {
      if (!video.videoWidth || !video.videoHeight)
        throw new Error("The camera is not ready yet.");
      const canvas = document.createElement("canvas");
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
      canvas.getContext("2d").drawImage(video, 0, 0);
      const blob = await new Promise((resolve) =>
        canvas.toBlob(resolve, "image/jpeg", 0.92),
      );
      if (!blob) throw new Error("Could not capture the photo.");
      if (!dialog.open) return;
      const file = new File(
        [blob],
        `photo-${new Date().toISOString().replace(/[:.]/g, "-")}.jpg`,
        { type: "image/jpeg" },
      );
      captured = file;
      stopCamera(stream);
      video.srcObject = null;
      video.hidden = shutter.hidden = direction.hidden = true;
      previewURL = URL.createObjectURL(file);
      review.src = previewURL;
      review.hidden = retake.hidden = use.hidden = false;
      status.textContent =
        "Review your photo. Use photo adds it to your draft; Send sends it.";
    } catch (error) {
      if (dialog.open) {
        status.textContent = error.message;
        shutter.disabled = false;
      }
    }
  };
  retake.onclick = () => {
    if (previewURL) URL.revokeObjectURL(previewURL);
    previewURL = null;
    captured = null;
    review.removeAttribute("src");
    review.hidden = retake.hidden = use.hidden = true;
    video.hidden = shutter.hidden = direction.hidden = false;
    start();
  };
  use.onclick = () => {
    const file = captured;
    if (!file) return;
    dialog.close();
    onPhoto(file);
  };
  document.body.append(dialog);
  dialog.showModal();
  await start();
}
