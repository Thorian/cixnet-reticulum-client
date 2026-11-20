"""Use CPython's bundled OpenSSL for Android X25519 public-key multiplication."""


def install():
    import ctypes

    import RNS.Cryptography

    crypto = ctypes.CDLL("libcrypto_python.so")
    create = crypto.EVP_PKEY_new_raw_private_key_ex
    create.argtypes = [
        ctypes.c_void_p,
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.c_size_t,
    ]
    create.restype = ctypes.c_void_p
    read = crypto.EVP_PKEY_get_raw_public_key
    read.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t)]
    read.restype = ctypes.c_int
    free = crypto.EVP_PKEY_free
    free.argtypes = [ctypes.c_void_p]
    free.restype = None
    private_key = RNS.Cryptography.X25519PrivateKey
    public_key = RNS.Cryptography.X25519PublicKey

    def derive(key):
        if len(key) != 32:
            raise ValueError("X25519 requires a 32-byte private key")
        handle = create(None, b"X25519", None, key, len(key))
        if not handle:
            raise RuntimeError("OpenSSL could not load the X25519 key")
        try:
            output = ctypes.create_string_buffer(32)
            size = ctypes.c_size_t(32)
            if read(handle, output, ctypes.byref(size)) != 1 or size.value != 32:
                raise RuntimeError("OpenSSL could not derive the X25519 public key")
            return output.raw
        finally:
            free(handle)

    # RFC 7748, section 6.1: check the native bridge before changing the provider.
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
