/** One location fix, with explicit cleanup instead of background tracking. */
export function stationLocation(geolocation) {
  let watch;
  let settled = false;
  let rejectPending;
  const stop = () => {
    if (watch !== undefined) geolocation.clearWatch(watch);
  };
  const promise = new Promise((resolve, reject) => {
    rejectPending = reject;
    if (!geolocation) {
      settled = true;
      reject(new Error("Location is unavailable. Enter coordinates manually."));
      return;
    }
    const finish = (error, position) => {
      if (settled) return;
      settled = true;
      stop();
      if (error) {
        reject(
          new Error(
            error.code === 1
              ? "Location permission declined. Enter coordinates manually."
              : error.code === 3
                ? "Location timed out. Try outdoors or enter coordinates manually."
                : "Could not get a location. Check location services or enter coordinates manually.",
          ),
        );
      } else {
        const { latitude, longitude, accuracy } = position.coords;
        if (
          ![latitude, longitude, accuracy].every(Number.isFinite) ||
          Math.abs(latitude) > 90 ||
          Math.abs(longitude) > 180 ||
          accuracy < 0
        )
          reject(new Error("The device returned an invalid location."));
        else resolve({ latitude, longitude, accuracy });
      }
    };
    try {
      watch = geolocation.watchPosition(
        (position) => finish(null, position),
        (error) => finish(error),
        { enableHighAccuracy: true, maximumAge: 60000, timeout: 30000 },
      );
      if (settled) stop();
    } catch (error) {
      settled = true;
      stop();
      reject(error);
    }
  });
  return {
    promise,
    cancel() {
      if (settled) return;
      settled = true;
      stop();
      rejectPending(new Error("Location request cancelled."));
    },
  };
}
