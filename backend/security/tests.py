from django.test import TestCase

from cryptography.exceptions import InvalidTag


from .aes_service import (
    build_file_aad,
    decrypt_bytes,
    encrypt_bytes,
    generate_dek,
    get_master_key,
    unwrap_dek,
    wrap_dek,
)


class EncryptionServiceTests(TestCase):

    def setUp(self):
        self.plaintext = (
            b"SecureDrive encryption test."
        )

        self.aad = build_file_aad(
            owner_id=1,
            file_id=1,
            version=1,
        )

    def test_encrypt_decrypt(self):

        dek = generate_dek()

        ciphertext, nonce = encrypt_bytes(
            self.plaintext,
            dek,
            self.aad,
        )

        self.assertNotEqual(
            ciphertext,
            self.plaintext,
        )

        result = decrypt_bytes(
            ciphertext,
            nonce,
            dek,
            self.aad,
        )

        self.assertEqual(
            result,
            self.plaintext,
        )

    def test_dek_wrap_unwrap(self):

        master_key = get_master_key()

        dek = generate_dek()

        wrapped_dek, dek_nonce = wrap_dek(
            dek,
            master_key,
        )

        recovered_dek = unwrap_dek(
            wrapped_dek,
            dek_nonce,
            master_key,
        )

        self.assertEqual(
            recovered_dek,
            dek,
        )

    def test_tampered_ciphertext_is_rejected(self):

        dek = generate_dek()

        ciphertext, nonce = encrypt_bytes(
            self.plaintext,
            dek,
            self.aad,
        )

        tampered = bytearray(ciphertext)

        # Thay đổi 1 byte
        tampered[0] ^= 1

        with self.assertRaises(InvalidTag):

            decrypt_bytes(
                bytes(tampered),
                nonce,
                dek,
                self.aad,
            )

    def test_wrong_aad_is_rejected(self):

        dek = generate_dek()

        ciphertext, nonce = encrypt_bytes(
            self.plaintext,
            dek,
            self.aad,
        )

        wrong_aad = build_file_aad(
            owner_id=999,
            file_id=999,
            version=1,
        )

        with self.assertRaises(InvalidTag):

            decrypt_bytes(
                ciphertext,
                nonce,
                dek,
                wrong_aad,
            )

    def test_wrong_master_key_cannot_unwrap_dek(self):

        master_key = get_master_key()

        dek = generate_dek()

        wrapped_dek, dek_nonce = wrap_dek(
            dek,
            master_key,
        )

        wrong_master_key = generate_dek()

        with self.assertRaises(InvalidTag):

            unwrap_dek(
                wrapped_dek,
                dek_nonce,
                wrong_master_key,
            )
    def test_wrong_dek_cannot_decrypt(self):
        dek = generate_dek()
        ciphertext, nonce = encrypt_bytes(
            self.plaintext,
            dek,
            self.aad,
        )

        with self.assertRaises(InvalidTag):
            decrypt_bytes(
                ciphertext,
                nonce,
                generate_dek(),
                self.aad,
            )

    def test_tampered_nonce_is_rejected(self):
        dek = generate_dek()
        ciphertext, nonce = encrypt_bytes(
            self.plaintext,
            dek,
            self.aad,
        )
        tampered_nonce = bytearray(nonce)
        tampered_nonce[0] ^= 1

        with self.assertRaises(InvalidTag):
            decrypt_bytes(
                ciphertext,
                bytes(tampered_nonce),
                dek,
                self.aad,
            )

    def test_wrapped_dek_is_not_plaintext_dek(self):
        master_key = get_master_key()
        dek = generate_dek()
        wrapped_dek, _ = wrap_dek(dek, master_key)
        self.assertNotEqual(wrapped_dek, dek)

    def test_aad_is_bound_to_file_identity(self):
        dek = generate_dek()
        ciphertext, nonce = encrypt_bytes(
            self.plaintext,
            dek,
            self.aad,
        )
        different_file_aad = build_file_aad(
            owner_id=1,
            file_id=2,
            version=1,
        )

        with self.assertRaises(InvalidTag):
            decrypt_bytes(
                ciphertext,
                nonce,
                dek,
                different_file_aad,
            )

