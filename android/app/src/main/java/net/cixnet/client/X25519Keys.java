package net.cixnet.client;

import org.bouncycastle.math.ec.rfc7748.X25519;

/** Keep public-key multiplication in one call across the Python/Java bridge. */
public final class X25519Keys {
  private X25519Keys() {}

  public static byte[] publicKey(byte[] secret) {
    if (secret.length != X25519.SCALAR_SIZE) {
      throw new IllegalArgumentException("X25519 requires a 32-byte private key");
    }
    byte[] result = new byte[X25519.POINT_SIZE];
    X25519.scalarMultBase(secret, 0, result, 0);
    return result;
  }
}
