"""Đối chiếu HPKE độc lập bằng PyCA, chỉ trao đổi fixture trong pipe."""
import hashlib
import json
import sys

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.hpke import AEAD, KDF, KEM, Suite


def main():
    suite = Suite(KEM.P256, KDF.HKDF_SHA256, AEAD.AES_256_GCM)
    info = b"BlueDrive/P6.1/interop"
    request = json.loads(sys.stdin.readline())
    if request["action"] == "seal":
        public = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), bytes.fromhex(request["public"]))
        ciphertext = suite.encrypt(bytes.fromhex(request["fixture"]), public, info=info)
        print(json.dumps({"wire": ciphertext.hex()}))
    elif request["action"] == "open":
        key = serialization.load_der_private_key(bytes.fromhex(request["fixturePkcs8"]), password=None)
        plaintext = suite.decrypt(bytes.fromhex(request["wire"]), key, info=info)
        print(json.dumps({"digest": hashlib.sha256(plaintext).hexdigest()}))
    else:
        raise ValueError("Unknown fixture operation")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(type(error).__name__, file=sys.stderr)
        sys.exit(1)
