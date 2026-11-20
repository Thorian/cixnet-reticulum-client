"""Accelerate Reticulum's X25519 public keys using the bundled Java provider."""


def install():
    import RNS.Cryptography
    from java import jclass

    native_key = jclass("org.bouncycastle.crypto.params.X25519PrivateKeyParameters")
    private_key = RNS.Cryptography.X25519PrivateKey
    public_key = RNS.Cryptography.X25519PublicKey

    def derive(key):
        return bytes(native_key(key, 0).generatePublicKey().getEncoded())

    # RFC 7748, section 6.1: check the Java bridge before changing the provider.
    secret = bytes.fromhex(
        "77076d0a7318a57d3c16c17251b26645df4c2f87ebc0992ab177fba51db92c2a"
    )
    expected = bytes.fromhex(
        "8520f0098930a754748b7ddcb43ef75a0dbf3a0d26381af4eba4a98eaa9b4e6a"
    )
    if derive(secret) != expected:
        raise RuntimeError("Android X25519 provider self-test failed")

    def accelerated_public_key(self):
        return public_key.from_public_bytes(derive(self.private_bytes()))

    # Keep upstream randomness, key exchange, stamp search and verification.
    # Public-key multiplication dominates the link-request proof-of-work loop.
    private_key.public_key = accelerated_public_key
