import assert from "node:assert/strict";
import test from "node:test";
import { stationLocation } from "../ui/station-location.js";

test("location stops after one fix and does not request until invoked", async () => {
  let success, options;
  const cleared = [];
  const gps = {
    watchPosition(ok, fail, opts) {
      success = ok;
      options = opts;
      return 12;
    },
    clearWatch(id) {
      cleared.push(id);
    },
  };
  const request = stationLocation(gps);
  success({ coords: { latitude: 44, longitude: -63, accuracy: 1500 } });
  assert.equal((await request.promise).accuracy, 1500);
  assert.deepEqual(cleared, [12]);
  assert.equal(options.timeout, 30000);
  request.cancel();
  assert.deepEqual(cleared, [12]);
});

test("closing cancels tracking and ignores a late fix", async () => {
  let success;
  const cleared = [];
  const request = stationLocation({
    watchPosition(ok) {
      success = ok;
      return 4;
    },
    clearWatch(id) {
      cleared.push(id);
    },
  });
  request.cancel();
  success({ coords: { latitude: 44, longitude: -63, accuracy: 5 } });
  await assert.rejects(request.promise, /cancelled/);
  assert.deepEqual(cleared, [4]);
});

test("denied, unavailable and timed out location retain manual fallback", async () => {
  await assert.rejects(stationLocation(null).promise, /manually/);
  for (const code of [1, 2, 3]) {
    let fail;
    const cleared = [];
    const request = stationLocation({
      watchPosition(ok, error) {
        fail = error;
        return 1;
      },
      clearWatch(id) {
        cleared.push(id);
      },
    });
    fail({ code });
    await assert.rejects(request.promise, /manually/);
    assert.deepEqual(cleared, [1]);
  }
});
