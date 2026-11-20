package net.cixnet.client;

import android.app.Activity;
import android.app.Instrumentation;
import android.os.Bundle;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

/** Exercise the packaged provider and upstream production-strength stamp worker. */
public final class CryptoInstrumentation extends Instrumentation {
  @Override
  public void onCreate(Bundle arguments) {
    super.onCreate(arguments);
    start();
  }

  @Override
  public void onStart() {
    Bundle report = new Bundle();
    try {
      if (!Python.isStarted()) Python.start(new AndroidPlatform(getTargetContext()));
      Python python = Python.getInstance();
      python.getModule("builtins").callAttr("exec", """
          import json, os, time
          import android_crypto
          import RNS.Cryptography, RNS.Stamps
          from RNS.Cryptography.X25519 import curve25519_base
          android_crypto.install()
          RNS.Stamps.job_android = RNS.Stamps.job_simple
          for _ in range(8):
              key = RNS.Cryptography.X25519PrivateKey.generate()
              assert key.public_key().public_bytes() == curve25519_base(key.private_bytes())
          start = time.monotonic()
          for _ in range(1000):
              RNS.Cryptography.X25519PrivateKey.generate().public_key().public_bytes()
          derivations_seconds = time.monotonic() - start
          material = b'ciXnet packaged Android stamp test'
          start = time.monotonic()
          pair, value = RNS.Stamps.generate_stamped_key(material, 12.5)
          assert pair and RNS.Stamps.stamp_valid(pair[1], 12.5, material)
          assert RNS.Cryptography.X25519PrivateKey.from_private_bytes(pair[0]).public_key().public_bytes() == pair[1]
          print(json.dumps({'x25519_1000_seconds': derivations_seconds,
                            'production_stamp_seconds': time.monotonic() - start,
                            'stamp_value': value}), flush=True)
          """);
      report.putString("crypto", "passed");
      finish(Activity.RESULT_OK, report);
    } catch (Throwable error) {
      report.putString("failure", error.toString());
      finish(Activity.RESULT_CANCELED, report);
    }
  }
}
